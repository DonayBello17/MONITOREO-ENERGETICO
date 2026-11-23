"""Paquete del Dashboard de Escritorio para el Sistema de Monitoreo Energético."""

from src.dashboard.anomaly_detector import AnomalyDetector
from src.dashboard.cost_calculator import calculate_fixed_cost, calculate_time_of_use_cost
from src.dashboard.ipc_client import IPCClientThread
from src.dashboard.theme import apply_theme

__all__ = [
    "IPCClientThread",
    "apply_theme",
    "calculate_fixed_cost",
    "calculate_time_of_use_cost",
    "AnomalyDetector",
]
