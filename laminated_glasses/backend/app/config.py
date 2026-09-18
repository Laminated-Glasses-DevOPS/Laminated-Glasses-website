"""Ilova sozlamalari. Barcha muhitga bog'liq qiymatlar shu yerda."""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"

UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

load_dotenv(BACKEND_DIR / ".env")


def _get_or_create_secret_key() -> str:
    """JWT kaliti. Muhit o'zgaruvchisi bo'lmasa, bir marta yaratilib faylga
    saqlanadi, shunda server qayta ishga tushganda tokenlar bekor bo'lmaydi."""
    env_value = os.getenv("SECRET_KEY", "").strip()
    if env_value:
        return env_value

    secret_file = BASE_DIR / ".secret_key"
    if secret_file.exists():
        return secret_file.read_text().strip()

    new_secret = secrets.token_hex(32)
    secret_file.write_text(new_secret)
    return new_secret


SECRET_KEY: str = _get_or_create_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))

_origins_raw = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = [o.strip() for o in _origins_raw.split(",") if o.strip()]

DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "7719")
DEFAULT_TELEGRAM_USERNAME = os.getenv("DEFAULT_TELEGRAM_USERNAME", "@laminated_glasses")
DEFAULT_SITE_TITLE = os.getenv("SITE_TITLE", "Laminated Glasses")

DATABASE_URL = f"sqlite:///{BASE_DIR / 'laminated_glasses.db'}"

MAX_UPLOAD_SIZE_MB = 8
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15

CART_TTL_DAYS = int(os.getenv("CART_TTL_DAYS", "7"))
MAX_CART_ITEM_QUANTITY = 99
