"""Gestor de base de datos SQLite con soporte WAL para lecturas concurrentes.

Diseñado para soportar alta tasa de escritura en el recolector y consultas
concurrentes fluidas desde el dashboard de usuario sin bloqueos.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.common.models import AggregateReading, Alert, Circuit, Reading
from src.common.paths import apply_secure_permissions, get_database_path

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Administrador de base de datos SQLite optimizado para concurrencia con WAL."""

    def __init__(self, db_path: Optional[Union[Path, str]] = None) -> None:
        """Inicializa el administrador de base de datos.

        Args:
            db_path: Ruta al archivo SQLite. Si es None, usa la ruta predeterminada del sistema.
                     Se admite ':memory:' para pruebas en memoria.
        """
        self._raw_path = db_path if db_path is not None else get_database_path()
        self._is_memory = str(self._raw_path) == ":memory:"
        self._db_path = ":memory:" if self._is_memory else Path(self._raw_path)

        self._lock = threading.RLock()
        self._local = threading.local()
        self._shared_memory_conn: Optional[sqlite3.Connection] = None

        if not self._is_memory:
            try:
                target_dir = self._db_path.parent
                target_dir.mkdir(parents=True, exist_ok=True)
                apply_secure_permissions(target_dir, is_directory=True)
            except (PermissionError, OSError) as exc:
                logger.error(
                    "Error al crear directorio para base de datos '%s': %s. Conmutando a base de datos en memoria.",
                    self._db_path,
                    exc,
                )
                self._is_memory = True
                self._db_path = ":memory:"

        try:
            self._init_database()
        except (sqlite3.Error, OSError) as exc:
            if not self._is_memory:
                logger.warning(
                    "Error al inicializar base de datos en disco '%s': %s. Conmutando a base de datos en memoria.",
                    self._db_path,
                    exc,
                )
                self._is_memory = True
                self._db_path = ":memory:"
                self._local = threading.local()
                self._shared_memory_conn = None
                self._init_database()
            else:
                logger.critical("Error fatal al inicializar base de datos: %s", exc)
                raise

    @property
    def db_path(self) -> Union[Path, str]:
        """Ruta física o URI de la base de datos."""
        return self._db_path

    def _create_connection(self) -> sqlite3.Connection:
        """Crea y configura una nueva conexión SQLite con PRAGMAs óptimos."""
        target = ":memory:" if self._is_memory else str(self._db_path)
        try:
            conn = sqlite3.connect(
                target,
                timeout=30.0,
                check_same_thread=False,
            )
        except (sqlite3.Error, OSError) as exc:
            if not self._is_memory:
                logger.warning("Fallo al conectar a '%s': %s. Conmutando a memoria.", target, exc)
                self._is_memory = True
                self._db_path = ":memory:"
                conn = sqlite3.connect(":memory:", timeout=30.0, check_same_thread=False)
            else:
                raise

        conn.row_factory = sqlite3.Row

        # Configuración de rendimiento y concurrencia
        if not self._is_memory:
            # WAL mode permite múltiples lectores simultáneos mientras un proceso escribe
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")
            except sqlite3.Error as exc:
                logger.warning("No se pudo configurar PRAGMA WAL/synchronous: %s", exc)

            # Proteger el archivo de base de datos en sistemas POSIX
            if isinstance(self._db_path, Path):
                try:
                    if self._db_path.exists():
                        apply_secure_permissions(self._db_path, is_directory=False)
                except OSError:
                    pass

        conn.execute("PRAGMA busy_timeout = 10000;")  # Espera hasta 10 segundos ante bloqueos
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA temp_store = MEMORY;")

        return conn

    def get_connection(self) -> sqlite3.Connection:
        """Obtiene la conexión correspondiente al hilo actual."""
        if self._is_memory:
            with self._lock:
                if self._shared_memory_conn is None:
                    self._shared_memory_conn = self._create_connection()
                return self._shared_memory_conn

        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._create_connection()
            self._local.conn = conn
        return conn

    def _init_database(self) -> None:
        """Crea las tablas e índices necesarios si no existen."""
        with self._lock:
            conn = self.get_connection()
            try:
                with conn:
                    # 1. Tabla de Circuitos
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS circuits (
                            id TEXT PRIMARY KEY,
                            name TEXT NOT NULL,
                            location TEXT,
                            nominal_power_w REAL NOT NULL DEFAULT 0.0,
                            icon TEXT NOT NULL DEFAULT 'zap',
                            is_active INTEGER NOT NULL DEFAULT 1,
                            min_power_w REAL NOT NULL DEFAULT 0.0,
                            max_power_w REAL NOT NULL DEFAULT 0.0,
                            daily_kwh_target REAL NOT NULL DEFAULT 0.0
                        );
                    """)
                    for col_def in (
                        "min_power_w REAL DEFAULT 0.0",
                        "max_power_w REAL DEFAULT 0.0",
                        "daily_kwh_target REAL DEFAULT 0.0",
                    ):
                        try:
                            conn.execute(f"ALTER TABLE circuits ADD COLUMN {col_def};")
                        except sqlite3.OperationalError:
                            pass

                    # 2. Tabla de Lecturas Crudas (Optimizada para millones de registros)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS readings (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            timestamp REAL NOT NULL,
                            circuit_id TEXT NOT NULL,
                            voltage REAL NOT NULL,
                            current REAL NOT NULL,
                            power_w REAL NOT NULL,
                            energy_kwh REAL NOT NULL,
                            FOREIGN KEY(circuit_id) REFERENCES circuits(id) ON DELETE CASCADE
                        );
                    """)

                    # Índices para acelerar búsquedas por tiempo y combinadas
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_readings_circuit_timestamp
                        ON readings (circuit_id, timestamp);
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_readings_timestamp
                        ON readings (timestamp);
                    """)

                    # 3. Tablas de Agregados Estadísticos (Horario, Diario, Mensual)
                    for period in ("hourly", "daily", "monthly"):
                        conn.execute(f"""
                            CREATE TABLE IF NOT EXISTS {period}_aggregates (
                                period_start REAL NOT NULL,
                                circuit_id TEXT NOT NULL,
                                avg_power_w REAL NOT NULL,
                                min_power_w REAL NOT NULL,
                                max_power_w REAL NOT NULL,
                                total_energy_kwh REAL NOT NULL,
                                reading_count INTEGER NOT NULL,
                                PRIMARY KEY (period_start, circuit_id),
                                FOREIGN KEY(circuit_id) REFERENCES circuits(id) ON DELETE CASCADE
                            );
                        """)
                        conn.execute(f"""
                            CREATE INDEX IF NOT EXISTS idx_{period}_circuit_period
                            ON {period}_aggregates (circuit_id, period_start);
                        """)

                    # 4. Tabla de Alertas
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS alerts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            timestamp REAL NOT NULL,
                            circuit_id TEXT,
                            alert_type TEXT NOT NULL,
                            severity TEXT NOT NULL,
                            message TEXT NOT NULL,
                            value REAL NOT NULL DEFAULT 0.0,
                            threshold REAL NOT NULL DEFAULT 0.0,
                            is_acknowledged INTEGER NOT NULL DEFAULT 0,
                            FOREIGN KEY(circuit_id) REFERENCES circuits(id) ON DELETE SET NULL
                        );
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_alerts_timestamp
                        ON alerts (timestamp);
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_alerts_unack
                        ON alerts (is_acknowledged, timestamp);
                    """)

                logger.info("Esquema de base de datos inicializado correctamente en %s", self._db_path)
            except sqlite3.Error as exc:
                logger.critical("Error al inicializar las tablas de base de datos: %s", exc)
                raise

    # ==========================
    # GESTIÓN DE CIRCUITOS
    # ==========================

    def upsert_circuit(self, circuit: Circuit) -> None:
        """Inserta o actualiza un circuito."""
        with self._lock:
            conn = self.get_connection()
            query = """
                INSERT INTO circuits (
                    id, name, location, nominal_power_w, icon, is_active,
                    min_power_w, max_power_w, daily_kwh_target
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    location = excluded.location,
                    nominal_power_w = excluded.nominal_power_w,
                    icon = excluded.icon,
                    is_active = excluded.is_active,
                    min_power_w = excluded.min_power_w,
                    max_power_w = excluded.max_power_w,
                    daily_kwh_target = excluded.daily_kwh_target;
            """
            with conn:
                conn.execute(
                    query,
                    (
                        circuit.id,
                        circuit.name,
                        circuit.location,
                        circuit.nominal_power_w,
                        circuit.icon,
                        1 if circuit.is_active else 0,
                        getattr(circuit, "min_power_w", 0.0),
                        getattr(circuit, "max_power_w", 0.0),
                        getattr(circuit, "daily_kwh_target", 0.0),
                    ),
                )

    def upsert_circuits(self, circuits: List[Circuit]) -> None:
        """Inserta o actualiza una lista de circuitos en lote."""
        if not circuits:
            return
        with self._lock:
            conn = self.get_connection()
            query = """
                INSERT INTO circuits (
                    id, name, location, nominal_power_w, icon, is_active,
                    min_power_w, max_power_w, daily_kwh_target
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    location = excluded.location,
                    nominal_power_w = excluded.nominal_power_w,
                    icon = excluded.icon,
                    is_active = excluded.is_active,
                    min_power_w = excluded.min_power_w,
                    max_power_w = excluded.max_power_w,
                    daily_kwh_target = excluded.daily_kwh_target;
            """
            rows = [
                (
                    c.id,
                    c.name,
                    c.location,
                    c.nominal_power_w,
                    c.icon,
                    1 if c.is_active else 0,
                    getattr(c, "min_power_w", 0.0),
                    getattr(c, "max_power_w", 0.0),
                    getattr(c, "daily_kwh_target", 0.0),
                )
                for c in circuits
            ]
            with conn:
                conn.executemany(query, rows)

    def get_circuits(self, active_only: bool = False) -> List[Circuit]:
        """Obtiene la lista de circuitos registrados."""
        conn = self.get_connection()
        query = """
            SELECT id, name, location, nominal_power_w, icon, is_active,
                   COALESCE(min_power_w, 0.0) as min_power_w,
                   COALESCE(max_power_w, 0.0) as max_power_w,
                   COALESCE(daily_kwh_target, 0.0) as daily_kwh_target
            FROM circuits
        """
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY id ASC"

        cursor = conn.execute(query)
        result = []
        for row in cursor.fetchall():
            result.append(
                Circuit(
                    id=row["id"],
                    name=row["name"],
                    location=row["location"] or "",
                    nominal_power_w=float(row["nominal_power_w"]),
                    icon=row["icon"],
                    is_active=bool(row["is_active"]),
                    min_power_w=float(row["min_power_w"]),
                    max_power_w=float(row["max_power_w"]),
                    daily_kwh_target=float(row["daily_kwh_target"]),
                )
            )
        return result

    def delete_circuit(self, circuit_id: str) -> bool:
        """Elimina un circuito y sus lecturas asociadas por cascada.

        Args:
            circuit_id: Identificador del circuito.

        Returns:
            bool: True si se eliminó, False si no existía.
        """
        with self._lock:
            conn = self.get_connection()
            with conn:
                cur = conn.execute("DELETE FROM circuits WHERE id = ?", (circuit_id,))
                return cur.rowcount > 0

    # ==========================
    # GESTIÓN DE LECTURAS (READINGS)
    # ==========================

    def insert_readings_batch(self, readings: List[Reading]) -> int:
        """Inserta un lote de lecturas de forma atómica y eficiente con executemany.

        Args:
            readings: Lista de objetos Reading.

        Returns:
            int: Cantidad de lecturas insertadas con éxito.
        """
        if not readings:
            return 0

        with self._lock:
            conn = self.get_connection()
            query = """
                INSERT INTO readings (timestamp, circuit_id, voltage, current, power_w, energy_kwh)
                VALUES (?, ?, ?, ?, ?, ?);
            """
            tuples = [r.to_tuple() for r in readings]
            try:
                with conn:
                    cursor = conn.executemany(query, tuples)
                    inserted = cursor.rowcount if cursor.rowcount >= 0 else len(tuples)
                return inserted
            except (sqlite3.Error, OSError) as exc:
                logger.error("Error al insertar lote de lecturas (%d items): %s", len(readings), exc)
                return 0

    def get_readings(
        self,
        circuit_id: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> List[Reading]:
        """Consulta lecturas aplicando filtros por circuito, rango temporal y límite.

        Args:
            circuit_id: Opcional, filtrar por ID del circuito.
            start_time: Opcional, marca de tiempo Unix inicial (inclusive).
            end_time: Opcional, marca de tiempo Unix final (inclusive).
            limit: Opcional, número máximo de filas a retornar.

        Returns:
            List[Reading]: Lista de lecturas ordenadas cronológicamente.
        """
        conn = self.get_connection()
        query = "SELECT timestamp, circuit_id, voltage, current, power_w, energy_kwh FROM readings WHERE 1=1"
        params: List[Any] = []

        if circuit_id is not None:
            query += " AND circuit_id = ?"
            params.append(circuit_id)
        if start_time is not None:
            query += " AND timestamp >= ?"
            params.append(start_time)
        if end_time is not None:
            query += " AND timestamp <= ?"
            params.append(end_time)

        query += " ORDER BY timestamp ASC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor = conn.execute(query, params)
        results: List[Reading] = []
        for row in cursor.fetchall():
            results.append(
                Reading(
                    timestamp=float(row["timestamp"]),
                    circuit_id=row["circuit_id"],
                    voltage=float(row["voltage"]),
                    current=float(row["current"]),
                    power_w=float(row["power_w"]),
                    energy_kwh=float(row["energy_kwh"]),
                )
            )
        return results

    def get_total_readings_count(self, circuit_id: Optional[str] = None) -> int:
        """Retorna la cantidad total de lecturas registradas en la base de datos."""
        conn = self.get_connection()
        query = "SELECT COUNT(*) FROM readings"
        params: List[Any] = []
        if circuit_id:
            query += " WHERE circuit_id = ?"
            params.append(circuit_id)
        cursor = conn.execute(query, params)
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def get_readings_paginated(
        self,
        circuit_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        order_desc: bool = True,
    ) -> List[Dict[str, Any]]:
        """Consulta lecturas con paginación optimizada para vistas de tabla en la interfaz.

        Args:
            circuit_id: Opcional, filtrar por ID de circuito.
            limit: Número de registros por página (ej. 50, 100, 500).
            offset: Desplazamiento desde el primer registro.
            order_desc: True para orden cronológico descendente (más recientes primero).

        Returns:
            List[Dict[str, Any]]: Lista de diccionarios con id, timestamp, circuit_id,
                                  voltage, current, power_w, energy_kwh.
        """
        conn = self.get_connection()
        direction = "DESC" if order_desc else "ASC"
        query = "SELECT id, timestamp, circuit_id, voltage, current, power_w, energy_kwh FROM readings"
        params: List[Any] = []
        if circuit_id:
            query += " WHERE circuit_id = ?"
            params.append(circuit_id)

        query += f" ORDER BY timestamp {direction}, id {direction} LIMIT ? OFFSET ?"
        params.extend([max(1, limit), max(0, offset)])

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "timestamp": float(row["timestamp"]),
                "circuit_id": row["circuit_id"],
                "voltage": float(row["voltage"]),
                "current": float(row["current"]),
                "power_w": float(row["power_w"]),
                "energy_kwh": float(row["energy_kwh"]),
            }
            for row in rows
        ]

    def clear_readings(self, clear_aggregates: bool = True) -> int:
        """Elimina todas las lecturas de la base de datos y opcionalmente sus agregados."""
        with self._lock:
            conn = self.get_connection()
            with conn:
                cur = conn.execute("DELETE FROM readings;")
                deleted = cur.rowcount
                if clear_aggregates:
                    conn.execute("DELETE FROM hourly_aggregates;")
                    conn.execute("DELETE FROM daily_aggregates;")
                    conn.execute("DELETE FROM monthly_aggregates;")
            return deleted

    # ==========================
    # AGREGACIONES ESTADÍSTICAS
    # ==========================

    def calculate_hourly_aggregates(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> int:
        """Calcula y almacena agregados horarios a partir de las lecturas crudas.

        Args:
            start_time: Timestamp de inicio opcional.
            end_time: Timestamp de fin opcional.

        Returns:
            int: Número de periodos horarios procesados/actualizados.
        """
        with self._lock:
            conn = self.get_connection()
            query = """
                INSERT INTO hourly_aggregates (
                    period_start, circuit_id, avg_power_w, min_power_w, max_power_w, total_energy_kwh, reading_count
                )
                SELECT
                    CAST(timestamp / 3600 AS INTEGER) * 3600 AS p_start,
                    circuit_id,
                    ROUND(AVG(power_w), 2) AS avg_power_w,
                    ROUND(MIN(power_w), 2) AS min_power_w,
                    ROUND(MAX(power_w), 2) AS max_power_w,
                    ROUND(SUM(energy_kwh), 6) AS total_energy_kwh,
                    COUNT(*) AS reading_count
                FROM readings
                WHERE (? IS NULL OR timestamp >= ?)
                  AND (? IS NULL OR timestamp < ?)
                GROUP BY p_start, circuit_id
                ON CONFLICT(period_start, circuit_id) DO UPDATE SET
                    avg_power_w = excluded.avg_power_w,
                    min_power_w = excluded.min_power_w,
                    max_power_w = excluded.max_power_w,
                    total_energy_kwh = excluded.total_energy_kwh,
                    reading_count = excluded.reading_count;
            """
            with conn:
                cursor = conn.execute(query, (start_time, start_time, end_time, end_time))
                return cursor.rowcount

    def calculate_daily_aggregates(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> int:
        """Calcula y almacena agregados diarios a partir de lecturas crudas o agregados horarios.

        Args:
            start_time: Timestamp de inicio opcional.
            end_time: Timestamp de fin opcional.

        Returns:
            int: Número de periodos diarios procesados/actualizados.
        """
        with self._lock:
            conn = self.get_connection()
            # Se calcula a partir de lecturas crudas para máxima precisión
            query = """
                INSERT INTO daily_aggregates (
                    period_start, circuit_id, avg_power_w, min_power_w, max_power_w, total_energy_kwh, reading_count
                )
                SELECT
                    CAST(timestamp / 86400 AS INTEGER) * 86400 AS p_start,
                    circuit_id,
                    ROUND(AVG(power_w), 2) AS avg_power_w,
                    ROUND(MIN(power_w), 2) AS min_power_w,
                    ROUND(MAX(power_w), 2) AS max_power_w,
                    ROUND(SUM(energy_kwh), 6) AS total_energy_kwh,
                    COUNT(*) AS reading_count
                FROM readings
                WHERE (? IS NULL OR timestamp >= ?)
                  AND (? IS NULL OR timestamp < ?)
                GROUP BY p_start, circuit_id
                ON CONFLICT(period_start, circuit_id) DO UPDATE SET
                    avg_power_w = excluded.avg_power_w,
                    min_power_w = excluded.min_power_w,
                    max_power_w = excluded.max_power_w,
                    total_energy_kwh = excluded.total_energy_kwh,
                    reading_count = excluded.reading_count;
            """
            with conn:
                cursor = conn.execute(query, (start_time, start_time, end_time, end_time))
                return cursor.rowcount

    def calculate_monthly_aggregates(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> int:
        """Calcula y almacena agregados mensuales a partir de lecturas crudas.

        Args:
            start_time: Timestamp de inicio opcional.
            end_time: Timestamp de fin opcional.

        Returns:
            int: Número de periodos mensuales procesados/actualizados.
        """
        with self._lock:
            conn = self.get_connection()
            query = """
                INSERT INTO monthly_aggregates (
                    period_start, circuit_id, avg_power_w, min_power_w, max_power_w, total_energy_kwh, reading_count
                )
                SELECT
                    CAST(strftime('%s', datetime(timestamp, 'unixepoch', 'start of month')) AS REAL) AS p_start,
                    circuit_id,
                    ROUND(AVG(power_w), 2) AS avg_power_w,
                    ROUND(MIN(power_w), 2) AS min_power_w,
                    ROUND(MAX(power_w), 2) AS max_power_w,
                    ROUND(SUM(energy_kwh), 6) AS total_energy_kwh,
                    COUNT(*) AS reading_count
                FROM readings
                WHERE (? IS NULL OR timestamp >= ?)
                  AND (? IS NULL OR timestamp < ?)
                GROUP BY p_start, circuit_id
                ON CONFLICT(period_start, circuit_id) DO UPDATE SET
                    avg_power_w = excluded.avg_power_w,
                    min_power_w = excluded.min_power_w,
                    max_power_w = excluded.max_power_w,
                    total_energy_kwh = excluded.total_energy_kwh,
                    reading_count = excluded.reading_count;
            """
            with conn:
                cursor = conn.execute(query, (start_time, start_time, end_time, end_time))
                return cursor.rowcount

    def get_aggregates(
        self,
        period_type: str = "hourly",
        circuit_id: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> List[AggregateReading]:
        """Recupera agregados estadísticos por tipo de periodo (hourly, daily, monthly)."""
        valid_tables = {
            "hourly": "hourly_aggregates",
            "daily": "daily_aggregates",
            "monthly": "monthly_aggregates",
        }
        if period_type not in valid_tables:
            raise ValueError(f"Periodo inválido '{period_type}'. Válidos: {list(valid_tables.keys())}")

        table_name = valid_tables[period_type]
        conn = self.get_connection()
        query = f"""
            SELECT period_start, circuit_id, avg_power_w, min_power_w, max_power_w, total_energy_kwh, reading_count
            FROM {table_name}
            WHERE 1=1
        """
        params: List[Any] = []
        if circuit_id is not None:
            query += " AND circuit_id = ?"
            params.append(circuit_id)
        if start_time is not None:
            query += " AND period_start >= ?"
            params.append(start_time)
        if end_time is not None:
            query += " AND period_start <= ?"
            params.append(end_time)

        query += " ORDER BY period_start ASC"

        cursor = conn.execute(query, params)
        results: List[AggregateReading] = []
        for row in cursor.fetchall():
            results.append(
                AggregateReading(
                    period_start=float(row["period_start"]),
                    circuit_id=row["circuit_id"],
                    avg_power_w=float(row["avg_power_w"]),
                    min_power_w=float(row["min_power_w"]),
                    max_power_w=float(row["max_power_w"]),
                    total_energy_kwh=float(row["total_energy_kwh"]),
                    reading_count=int(row["reading_count"]),
                )
            )
        return results

    # ==========================
    # POLÍTICA DE RETENCIÓN DE DATOS
    # ==========================

    def apply_retention_policy(
        self,
        raw_days: int = 30,
        aggregates_days: int = 730,
        reference_time: Optional[float] = None,
    ) -> Dict[str, int]:
        """Aplica la política de retención eliminando datos que excedan el límite de conservación.

        Args:
            raw_days: Días de conservación de lecturas crudas (por defecto 30).
            aggregates_days: Días de conservación de tablas de agregados (por defecto 730 = 2 años).
            reference_time: Timestamp de referencia opcional (por defecto time.time()).

        Returns:
            Dict[str, int]: Diccionario con las filas eliminadas por tabla.
        """
        now = reference_time if reference_time is not None else time.time()
        raw_cutoff = now - (raw_days * 86400.0)
        agg_cutoff = now - (aggregates_days * 86400.0)

        results: Dict[str, int] = {
            "readings_deleted": 0,
            "hourly_deleted": 0,
            "daily_deleted": 0,
            "monthly_deleted": 0,
            "alerts_deleted": 0,
        }

        with self._lock:
            conn = self.get_connection()
            try:
                with conn:
                    # 1. Limpieza de lecturas crudas
                    cur = conn.execute("DELETE FROM readings WHERE timestamp < ?", (raw_cutoff,))
                    results["readings_deleted"] = cur.rowcount

                    # 2. Limpieza de agregados antiguos
                    cur = conn.execute(
                        "DELETE FROM hourly_aggregates WHERE period_start < ?", (agg_cutoff,)
                    )
                    results["hourly_deleted"] = cur.rowcount

                    cur = conn.execute(
                        "DELETE FROM daily_aggregates WHERE period_start < ?", (agg_cutoff,)
                    )
                    results["daily_deleted"] = cur.rowcount

                    cur = conn.execute(
                        "DELETE FROM monthly_aggregates WHERE period_start < ?", (agg_cutoff,)
                    )
                    results["monthly_deleted"] = cur.rowcount

                    # 3. Limpieza de alertas ya atendidas anteriores al periodo crudo
                    cur = conn.execute(
                        "DELETE FROM alerts WHERE timestamp < ? AND is_acknowledged = 1",
                        (raw_cutoff,),
                    )
                    results["alerts_deleted"] = cur.rowcount

                logger.info(
                    "Política de retención aplicada. Filas eliminadas: %s", results
                )
                return results
            except sqlite3.Error as exc:
                logger.error("Error al aplicar política de retención: %s", exc)
                raise

    # ==========================
    # GESTIÓN DE ALERTAS
    # ==========================

    def insert_alert(self, alert: Alert) -> int:
        """Inserta una alerta y retorna el identificador autogenerado."""
        with self._lock:
            conn = self.get_connection()
            query = """
                INSERT INTO alerts (
                    timestamp, circuit_id, alert_type, severity, message, value, threshold, is_acknowledged
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            with conn:
                cur = conn.execute(
                    query,
                    (
                        alert.timestamp,
                        alert.circuit_id,
                        alert.alert_type,
                        alert.severity,
                        alert.message,
                        alert.value,
                        alert.threshold,
                        1 if alert.is_acknowledged else 0,
                    ),
                )
                return cur.lastrowid or 0

    def get_alerts(
        self,
        limit: int = 100,
        unacknowledged_only: bool = False,
    ) -> List[Alert]:
        """Recupera la lista de alertas recientes."""
        conn = self.get_connection()
        query = "SELECT id, timestamp, circuit_id, alert_type, severity, message, value, threshold, is_acknowledged FROM alerts"
        params: List[Any] = []

        if unacknowledged_only:
            query += " WHERE is_acknowledged = 0"

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        results: List[Alert] = []
        for row in cursor.fetchall():
            results.append(
                Alert(
                    id=row["id"],
                    timestamp=float(row["timestamp"]),
                    circuit_id=row["circuit_id"],
                    alert_type=row["alert_type"],
                    severity=row["severity"],
                    message=row["message"],
                    value=float(row["value"]),
                    threshold=float(row["threshold"]),
                    is_acknowledged=bool(row["is_acknowledged"]),
                )
            )
        return results

    def acknowledge_alert(self, alert_id: int) -> bool:
        """Marca una alerta como atendida/reconocida."""
        with self._lock:
            conn = self.get_connection()
            with conn:
                cur = conn.execute(
                    "UPDATE alerts SET is_acknowledged = 1 WHERE id = ?", (alert_id,)
                )
                return cur.rowcount > 0

    # ==========================
    # MANTENIMIENTO Y CIERRE
    # ==========================

    def checkpoint_wal(self) -> None:
        """Ejecuta un checkpoint de WAL para transferir datos al archivo DB principal."""
        if self._is_memory:
            return
        with self._lock:
            conn = self.get_connection()
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except sqlite3.Error as exc:
                logger.warning("No se pudo ejecutar wal_checkpoint: %s", exc)

    def close(self) -> None:
        """Cierra de forma segura las conexiones activas."""
        with self._lock:
            if self._shared_memory_conn:
                try:
                    self._shared_memory_conn.close()
                except Exception:
                    pass
                self._shared_memory_conn = None

            conn = getattr(self._local, "conn", None)
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
                self._local.conn = None
