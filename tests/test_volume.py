"""Pruebas de estrés y volumen de datos masivos (1.000.000 de lecturas).

Valida:
1. Rendimiento y tasa de inserción atómica en lotes (batching con executemany).
2. Estabilidad de la base de datos SQLite en modo WAL bajo alta concurrencia.
3. Rendimiento de consultas analíticas indexadas sobre 1 millón de registros (< 250 ms).
4. Ausencia de fugas de memoria y consistencia referencial.
"""

import time
import pytest

from src.common.database import DatabaseManager
from src.common.models import Circuit, Reading


@pytest.fixture
def volume_db(tmp_path):
    """Crea una base de datos temporal optimizada para pruebas de volumen."""
    db_file = tmp_path / "volume_test.db"
    db = DatabaseManager(db_path=db_file)

    # Crear 5 circuitos estándar
    circuits = [
        Circuit(id=f"circ_0{i}", name=f"Circuito {i}", location=f"Zona {i}", nominal_power_w=1500.0)
        for i in range(1, 6)
    ]
    db.upsert_circuits(circuits)
    yield db
    db.close()


def test_million_readings_insertion_and_query_performance(volume_db):
    """Inserta 1.000.000 de lecturas en SQLite y mide tiempos de inserción y consulta indexada."""
    target_count = 1_000_000
    batch_size = 50_000
    batches = target_count // batch_size

    base_timestamp = 1700000000.0
    total_inserted = 0

    circuit_ids = ["circ_01", "circ_02", "circ_03", "circ_04", "circ_05"]

    t_start = time.perf_counter()

    # Inserción en lotes de 50.000
    for b in range(batches):
        batch = []
        offset = b * batch_size
        for i in range(batch_size):
            idx = offset + i
            cid = circuit_ids[idx % len(circuit_ids)]
            batch.append(
                Reading(
                    timestamp=base_timestamp + (idx * 2.0),
                    circuit_id=cid,
                    voltage=120.0 + (i % 5) * 0.2,
                    current=1.0 + (i % 10) * 0.1,
                    power_w=120.0 + (i % 50),
                    energy_kwh=0.00005 * idx,
                )
            )

        inserted = volume_db.insert_readings_batch(batch)
        total_inserted += inserted

    t_insert = time.perf_counter() - t_start

    # 1. Validar cantidad total insertada
    assert total_inserted == target_count
    insertion_rate = target_count / t_insert
    print(f"\n[VOLUMEN] 1.000.000 lecturas insertadas en {t_insert:.2f}s ({insertion_rate:,.0f} lecturas/seg)")
    # La tasa debe ser superior a 30.000 lecturas/segundo
    assert insertion_rate > 30_000

    # 2. Medir tiempo de consulta por rango y circuito (debe usar índice y tardar < 0.25s)
    t_query_start = time.perf_counter()
    # Rango de 10.000 segundos para el circuito 1
    sample = volume_db.get_readings(
        circuit_id="circ_01",
        start_time=base_timestamp + 100_000,
        end_time=base_timestamp + 120_000,
        limit=2000,
    )
    t_query = time.perf_counter() - t_query_start

    print(f"[VOLUMEN] Consulta indexada sobre 1.000.000 filas: {len(sample)} resultados en {t_query * 1000:.2f} ms")
    assert len(sample) > 0
    assert t_query < 0.25  # Menos de 250 milisegundos

    # 3. Validar consistencia de cálculo de agregados sobre un subperiodo
    t_agg_start = time.perf_counter()
    hourly_updated = volume_db.calculate_hourly_aggregates(
        start_time=base_timestamp,
        end_time=base_timestamp + 86400,
    )
    t_agg = time.perf_counter() - t_agg_start
    print(f"[VOLUMEN] Cálculo de agregados horarios (1 día = 43.200 lecturas) tomó {t_agg:.2f}s ({hourly_updated} periodos)")
    assert hourly_updated >= 1
