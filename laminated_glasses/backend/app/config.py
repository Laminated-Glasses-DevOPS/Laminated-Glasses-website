"""Ilova sozlamalari. Barcha muhitga bog'liq qiymatlar shu yerda."""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"

load_dotenv(BACKEND_DIR / ".env")

# XAVFSIZLIK / DOIMIYLIK ESLATMASI: Render.com (va shunga o'xshash
# platformalar)da har bir deploy'da kod papkasi (bu yerda -- BASE_DIR,
# ya'ni backend/app) YANGIDAN yaratiladi -- undagi hech narsa (baza fayli,
# uploads/, .secret_key, .admin_password) keyingi deployгача SAQLANMAYDI.
# Shu sabab bularning barchasi endi ALOHIDA papkaga (DATA_DIR) yoziladi.
# Lokal ishlab chiqishda DATA_DIR ko'rsatilmasa, sukut bo'yicha BASE_DIR
# ishlatilinaveradi (avvalgi xatti-harakat o'zgarmaydi). Render'da esa
# DATA_DIR ni platformaning "Persistent Disk"i ulangan yo'lga (masalan
# /var/data) ko'rsatish kifoya -- shunda baza, rasm va zaxira fayllari
# har bir qayta deploy/qayta ishga tushirishdan keyin ham saqlanib qoladi.
_data_dir_env = os.getenv("DATA_DIR", "").strip()
DATA_DIR = Path(_data_dir_env).resolve() if _data_dir_env else BASE_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)

UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

BACKUPS_DIR = DATA_DIR / "backups"
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

# Bazani "tiklash" (restore) dan OLDIN joriy bazaning xavfsizlik nusxasi
# shu yerga avtomatik yoziladi -- noto'g'ri/buzuq fayl yuklansa ham,
# admin har doim oldingi holatga qaytarilishi mumkin.
DB_SNAPSHOTS_DIR = DATA_DIR / "db_snapshots"
DB_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def _get_or_create_secret_key() -> str:
    """JWT kaliti. Muhit o'zgaruvchisi bo'lmasa, bir marta yaratilib faylga
    saqlanadi, shunda server qayta ishga tushganda tokenlar bekor bo'lmaydi."""
    env_value = os.getenv("SECRET_KEY", "").strip()
    if env_value:
        return env_value

    secret_file = DATA_DIR / ".secret_key"
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

def _get_or_create_default_admin_password() -> str:
    """Admin panelning BOSHLANG'ICH paroli.

    Avval juda zaif, hammaga ma'lum standart qiymat ("7719") ishlatilar edi
    -- bu, ayniqsa brute-force himoyasi zaiflashtirilgan holatda, admin
    panelni osongina buzish xavfini keltirib chiqarardi. Endi:
      1) Agar .env faylida DEFAULT_ADMIN_PASSWORD aniq ko'rsatilgan bo'lsa,
         o'sha qiymat ishlatiladi (admin o'zi ongli tanlagan parol).
      2) Aks holda, bir martalik TASODIFIY va YETARLICHA UZUN parol
         yaratiladi va `.admin_password` fayliga yoziladi (xuddi JWT
         maxfiy kaliti kabi) -- shu tufayli server qayta ishga tushganda
         ham parol o'zgarib qolmaydi. Bu parol server birinchi marta
         ishga tushganda konsolga chiqariladi (main.py da).
    """
    env_value = os.getenv("DEFAULT_ADMIN_PASSWORD", "").strip()
    if env_value:
        return env_value

    pw_file = DATA_DIR / ".admin_password"
    if pw_file.exists():
        stored = pw_file.read_text().strip()
        if stored:
            return stored

    new_password = secrets.token_urlsafe(9)  # ~12 ta belgili, taxmin qilib bo'lmaydigan parol
    pw_file.write_text(new_password)
    return new_password


DEFAULT_ADMIN_PASSWORD = _get_or_create_default_admin_password()
DEFAULT_TELEGRAM_USERNAME = os.getenv("DEFAULT_TELEGRAM_USERNAME", "@laminated_glasses")
DEFAULT_SITE_TITLE = os.getenv("SITE_TITLE", "Laminated Glasses")

# Xavfsizlik: "X-Forwarded-For" headeriga sukut bo'yicha ISHONILMAYDI, chunki
# uni har qanday mijoz o'zi soxtalashtirishi mumkin (aks holda login
# bruteforce blokini va honeypot IP kuzatuvini osongina chetlab o'tish
# mumkin bo'lardi). Faqat admin o'zi ishonadigan proksi (masalan o'z nginx'i)
# orqasida ishlatayotganini aniq bildirsagina yoqiladi. Cloudflare Tunnel
# ishlatilganda bunga ehtiyoj yo'q -- "CF-Connecting-IP" headeri avtomatik
# va ishonchli tarzda ishlatiladi (security.py ga qarang).
TRUST_X_FORWARDED_FOR = os.getenv("TRUST_X_FORWARDED_FOR", "false").strip().lower() == "true"

DATABASE_URL = f"sqlite:///{DATA_DIR / 'laminated_glasses.db'}"

MAX_UPLOAD_SIZE_MB = 8
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# "Bazani tiklash" (admin panel -> Baza holati) uchun cheklovlar.
MAX_DB_UPLOAD_SIZE_MB = 200
MAX_DB_SNAPSHOTS = 5

# "Konfiguratsiya to'plami" (mahsulotlar+rasmlar, constructor sozlamalari,
# admin paroli, statistika) eksport/import qilinganda .zip fayl siqilmagan
# holda shu hajmdan katta bo'lmasligi kerak (zip-bomb himoyasi).
MAX_CONFIG_BUNDLE_UPLOAD_SIZE_MB = 300

MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15

CART_TTL_DAYS = int(os.getenv("CART_TTL_DAYS", "7"))
MAX_CART_ITEM_QUANTITY = 99
