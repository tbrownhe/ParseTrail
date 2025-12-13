import atexit
import importlib.util
import socket
import subprocess
import time
from typing import Optional, Tuple

from settings import settings
from ssh import fetch_remote_env
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_tunnel_proc: Optional[subprocess.Popen] = None
_engine = None
_SessionLocal: Optional[sessionmaker] = None
_atexit_registered = False
_REMOTE_DB_ENV: Optional[dict] = None


def _load_remote_db_env() -> dict:
    """Fetch DB connection settings from the remote .env (cached)."""
    global _REMOTE_DB_ENV
    if _REMOTE_DB_ENV is not None:
        return _REMOTE_DB_ENV

    keys = [
        "POSTGRES_SERVER",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
    ]
    values = {k: fetch_remote_env(k) for k in keys}
    # Cast numeric fields
    values["POSTGRES_PORT"] = int(values["POSTGRES_PORT"])
    _REMOTE_DB_ENV = values
    return values


def _driver_prefix() -> str:
    """Prefer psycopg (psycopg3); fall back to psycopg2; otherwise default."""
    if importlib.util.find_spec("psycopg"):
        return "postgresql+psycopg://"
    if importlib.util.find_spec("psycopg2"):
        return "postgresql+psycopg2://"
    return "postgresql://"


def _build_database_url(host: str, port: int) -> str:
    prefix = _driver_prefix()
    db_env = _load_remote_db_env()
    return (
        f"{prefix}{db_env['POSTGRES_USER']}:{db_env['POSTGRES_PASSWORD']}"
        f"@{host}:{port}/{db_env['POSTGRES_DB']}"
    )


def _get_container_ip() -> str:
    cmd = ["ssh"]
    if settings.SSH_KEY_PATH:
        cmd += ["-i", settings.SSH_KEY_PATH]
    cmd += [
        f"{settings.REMOTE_USER}@{settings.REMOTE_HOST}",
        "docker",
        "inspect",
        "-f",
        "'{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'",
        settings.DB_CONTAINER_NAME,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    ip = result.stdout.strip()
    if not ip:
        raise RuntimeError("Failed to resolve container IP from docker inspect")
    return ip


def _wait_for_port(host: str, port: int, timeout: float = 8.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"Tunnel to {host}:{port} did not become ready")


def _start_tunnel() -> Tuple[str, int]:
    global _tunnel_proc
    if not settings.REMOTE_HOST or not settings.REMOTE_USER:
        raise ValueError("REMOTE_HOST and REMOTE_USER are required for SSH tunneling")
    container_ip = _get_container_ip()
    local_port = settings.SSH_TUNNEL_LOCAL_PORT
    cmd = ["ssh"]
    if settings.SSH_KEY_PATH:
        cmd += ["-i", settings.SSH_KEY_PATH]
    cmd += [
        "-N",
        "-L",
        f"{local_port}:{container_ip}:{settings.DB_CONTAINER_PORT}",
        f"{settings.REMOTE_USER}@{settings.REMOTE_HOST}",
    ]
    _tunnel_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _wait_for_port("127.0.0.1", local_port)
    return "127.0.0.1", local_port


def _stop_tunnel():
    global _tunnel_proc
    if _tunnel_proc and _tunnel_proc.poll() is None:
        _tunnel_proc.terminate()
        try:
            _tunnel_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _tunnel_proc.kill()
    _tunnel_proc = None


def _ensure_tunnel() -> Tuple[str, int]:
    global _atexit_registered
    if _tunnel_proc and _tunnel_proc.poll() is None:
        return "127.0.0.1", settings.SSH_TUNNEL_LOCAL_PORT
    host, port = _start_tunnel()
    if not _atexit_registered:
        atexit.register(_stop_tunnel)
        _atexit_registered = True
    return host, port


def get_engine():
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine

    db_env = _load_remote_db_env()
    host = db_env["POSTGRES_SERVER"]
    port = db_env["POSTGRES_PORT"]

    if settings.SSH_TUNNEL_ENABLE:
        host, port = _ensure_tunnel()

    url = _build_database_url(host, port)
    _engine = create_engine(url, pool_size=5, max_overflow=10)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _engine


def get_sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        get_engine()
    return _SessionLocal  # type: ignore


# Eagerly initialize so existing imports still work
get_engine()
SessionLocal = get_sessionmaker()
