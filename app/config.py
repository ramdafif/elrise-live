import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_config():
    selected_env = os.getenv("ELRISE_ENV_FILE")
    env_path = ROOT / selected_env if selected_env else ROOT / ".env"
    if selected_env and not env_path.is_file():
        raise RuntimeError("ELRISE_ENV_FILE tidak ditemukan; konfigurasi demo tidak dipakai sebagai fallback.")
    load_dotenv(env_path)
    production = os.getenv("APP_ENV", "production") == "production"
    return {
        "APP_ENV": os.getenv("APP_ENV", "production"),
        "SECRET_KEY": os.getenv("SECRET_KEY", ""),
        "MYSQL_HOST": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "MYSQL_PORT": int(os.getenv("MYSQL_PORT", "3306")),
        "MYSQL_USER": os.getenv("MYSQL_USER", "elrise"),
        "MYSQL_PASSWORD": os.getenv("MYSQL_PASSWORD", ""),
        "MYSQL_DATABASE": os.getenv("MYSQL_DATABASE", "elrise_db"),
        "MYSQL_SSL_CA": os.getenv("MYSQL_SSL_CA", ""),
        "SESSION_COOKIE_NAME": os.getenv("SESSION_COOKIE_NAME", "elrise_session"),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": production or os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=8),
        "SESSION_REFRESH_EACH_REQUEST": False,
        "MAX_CONTENT_LENGTH": 6 * 1024 * 1024,
        "MAX_FORM_MEMORY_SIZE": 2 * 1024 * 1024,
        "MAX_FORM_PARTS": 30,
        "MAX_PHOTO_BYTES": int(os.getenv("MAX_PHOTO_BYTES", "1048576")),
        "PHOTO_RETENTION_DAYS": int(os.getenv("PHOTO_RETENTION_DAYS", "30")),
        "ATTENDANCE_RETENTION_DAYS": int(os.getenv("ATTENDANCE_RETENTION_DAYS", "365")),
        "LEAVE_RETENTION_DAYS": int(os.getenv("LEAVE_RETENTION_DAYS", "365")),
        "PRIVATE_UPLOAD_DIR": os.getenv("PRIVATE_UPLOAD_DIR", str(ROOT / "instance" / "attendance")),
        "PRIVACY_VERSION": os.getenv("PRIVACY_VERSION", "2026-10-13"),
        "PRIVACY_CONTACT": os.getenv("PRIVACY_CONTACT", ""),
        "TRUSTED_HOSTS": [host.strip() for host in os.getenv("TRUSTED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()],
        "TRUST_PROXY_HOPS": int(os.getenv("TRUST_PROXY_HOPS", "0")),
        "DEMO_PASSWORD": os.getenv("DEMO_PASSWORD", ""),
    }
