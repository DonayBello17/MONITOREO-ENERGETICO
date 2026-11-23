"""Paquete del recolector en segundo plano (Collector).

Contiene el simulador de telemetría, validador de lecturas, servidor IPC,
trabajador de agregación estadística y el servicio principal productor-consumidor.
"""

from src.collector.aggregator import AggregatorWorker
from src.collector.ipc_server import IPCServer
from src.collector.simulator import DataSourceError, EnergySimulator
from src.collector.validator import ReadingValidator

__all__ = [
    "EnergySimulator",
    "DataSourceError",
    "ReadingValidator",
    "IPCServer",
    "AggregatorWorker",
]
