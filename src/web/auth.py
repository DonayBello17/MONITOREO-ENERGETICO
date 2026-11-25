"""Módulo de autenticación liviano para la interfaz web del Monitor Energético.

Implementa:
- Autenticación de un solo usuario administrador mediante variables de entorno (ADMIN_USER, ADMIN_PASSWORD).
- Hashing de contraseñas con SHA-256 y comparación segura con hmac.compare_digest contra ataques de temporización.
- Sesiones sin estado (stateless) mediante cookies firmadas criptográficamente con HMAC-SHA256 (SESSION_SECRET).
- Funciones auxiliares para verificar y manipular cookies HttpOnly / SameSite.
- Utiliza estrictamente la biblioteca estándar de Python (hashlib, hmac, secrets, base64, json, time).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional
from fastapi import Request, Response

logger = logging.getLogger(__name__)

# Configuración por defecto mediante variables de entorno
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "monitor2026"
DEFAULT_SESSION_SECRET = "energy-monitor-super-secure-session-secret-key-2026"
SESSION_COOKIE_NAME = "energy_session"
DEFAULT_SESSION_DURATION = 86400 * 7  # 7 días


def get_admin_user() -> str:
    """Retorna el usuario administrador configurado en el entorno."""
    return os.environ.get("ADMIN_USER", DEFAULT_ADMIN_USER).strip()


def get_admin_password() -> str:
    """Retorna la contraseña del administrador configurada en el entorno."""
    return os.environ.get("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)


def get_session_secret() -> bytes:
    """Retorna la clave secreta para firmar sesiones en bytes."""
    secret_str = os.environ.get("SESSION_SECRET", DEFAULT_SESSION_SECRET)
    return secret_str.encode("utf-8")


def hash_password(password: str) -> str:
    """Calcula el hash SHA-256 de una contraseña en formato hexadecimal."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(provided_password: str) -> bool:
    """Compara la contraseña provista con la configurada usando hmac.compare_digest."""
    configured_pwd = get_admin_password()
    # Si la variable de entorno ya viniera como hash SHA-256 (64 caracteres hex)
    if len(configured_pwd) == 64 and all(c in "0123456789abcdefABCDEF" for c in configured_pwd):
        expected_hash = configured_pwd.lower()
    else:
        expected_hash = hash_password(configured_pwd)

    provided_hash = hash_password(provided_password)
    return hmac.compare_digest(provided_hash, expected_hash)


def authenticate(username: str, password: str) -> bool:
    """Verifica las credenciales del usuario contra el administrador del sistema."""
    if not username or not password:
        return False
    expected_user = get_admin_user()
    user_ok = hmac.compare_digest(username.strip(), expected_user)
    pwd_ok = verify_password(password)
    return user_ok and pwd_ok


def _b64encode(data: bytes) -> str:
    """Codifica bytes en base64 url-safe sin relleno."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(s: str) -> bytes:
    """Decodifica un string base64 url-safe añadiendo relleno si es necesario."""
    rem = len(s) % 4
    if rem > 0:
        s += "=" * (4 - rem)
    return base64.urlsafe_b64decode(s.encode("ascii"))


def create_session_token(username: str, max_age: int = DEFAULT_SESSION_DURATION) -> str:
    """Crea un token de sesión firmado criptográficamente con HMAC-SHA256."""
    now = int(time.time())
    payload = {
        "user": username,
        "iat": now,
        "exp": now + max_age,
    }
    payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64encode(payload_json)

    sig = hmac.new(get_session_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = _b64encode(sig)

    return f"{payload_b64}.{sig_b64}"


def verify_session_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Verifica la firma y expiración de un token de sesión.

    Returns:
        Dict con la carga útil si es válido, o None si es inválido o expiró.
    """
    if not token or "." not in token:
        return None

    parts = token.split(".")
    if len(parts) != 2:
        return None

    payload_b64, sig_b64 = parts

    # Verificar firma HMAC
    expected_sig = hmac.new(get_session_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    expected_sig_b64 = _b64encode(expected_sig)

    if not hmac.compare_digest(sig_b64, expected_sig_b64):
        logger.warning("Firma de token de sesión inválida.")
        return None

    try:
        payload_bytes = _b64decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        logger.warning("No se pudo decodificar payload de sesión: %s", exc)
        return None

    # Verificar expiración
    exp = payload.get("exp", 0)
    if time.time() > exp:
        logger.debug("Token de sesión expirado.")
        return None

    # Verificar que el usuario corresponda al administrador actual
    token_user = payload.get("user")
    if not token_user or not hmac.compare_digest(token_user, get_admin_user()):
        logger.debug("El usuario en la sesión no coincide con el administrador activo.")
        return None

    return payload


def get_current_user(request: Request) -> Optional[str]:
    """Extrae el usuario autenticado a partir de la cookie de sesión o encabezado Authorization."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        # Soporte alternativo de Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    payload = verify_session_token(token)
    if payload:
        return payload.get("user")
    return None


def set_session_cookie(
    response: Response,
    token: str,
    max_age: int = DEFAULT_SESSION_DURATION,
) -> None:
    """Configura la cookie de sesión segura en la respuesta HTTP."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        expires=max_age,
        httponly=True,
        samesite="lax",
        path="/",
        secure=False,  # Permite HTTP local (Windows/Linux); en producción HTTPS con proxy se mantiene
    )


def clear_session_cookie(response: Response) -> None:
    """Elimina la cookie de sesión."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
    )
