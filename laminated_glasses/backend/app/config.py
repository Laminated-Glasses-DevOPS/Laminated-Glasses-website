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


def _restrict_permissions(path: Path) -> None:
    """Maxfiy fayllarni faqat egasi o'qiy oladigan qiladi (VPS'da muhim)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


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
    _restrict_permissions(secret_file)
    return new_secret


SECRET_KEY: str = _get_or_create_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))

# CORS. Frontend va API BITTA domendan beriladi (bir xil origin), shuning
# uchun CORS umuman kerak emas va standart holatda BUTUNLAY YOPIQ (bo'sh).
# Faqat frontend BOSHQA domenda joylashsa, shu yerga vergul bilan yozing:
#   ALLOWED_ORIGINS=https://domen.uz,https://www.domen.uz
# "*" faqat ataylab yozilsagina ochiladi va ogohlantirish chiqadi.
_origins_raw = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in _origins_raw.split(",") if o.strip()]

# Saytning ommaviy manzili (masalan https://domen.uz). Konstruktordagi
# Telegram havolalari (rasm URL'lari) shu manzil bilan quriladi. Bo'sh
# bo'lsa, manzil so'rovning o'zidan olinadi (proksi to'g'ri sozlangan
# bo'lsa ham ishlaydi), lekin domen ulangach buni yozib qo'yish eng ishonchli.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")

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
    _restrict_permissions(pw_file)
    return new_password


DEFAULT_ADMIN_PASSWORD = _get_or_create_default_admin_password()
DEFAULT_TELEGRAM_USERNAME = os.getenv("DEFAULT_TELEGRAM_USERNAME", "@laminated_glasses")
DEFAULT_SITE_TITLE = os.getenv("SITE_TITLE", "Laminated Glasses")

# Mijoz IP manzili (login brute-force bloki, honeypot, rate-limit uchun).
#
# Proksi (nginx, Cloudflare Tunnel, Render) orqasida backend barcha so'rovlarni
# proksining IP'sidan (127.0.0.1 va h.k.) kelayotgandek ko'radi. Shuning
# uchun haqiqiy mijoz IP'si proksi qo'ygan headerlardan olinadi -- lekin
# FAQAT so'rov ISHONCHLI proksidan kelgan bo'lsa (aks holda mijoz headerni
# o'zi soxtalashtirishi mumkin).
#
# TRUSTED_PROXIES  -- ishonchli proksilar (IP yoki CIDR, vergul bilan).
#                     Standart: 127.0.0.1, ::1 (o'sha serverdagi nginx yoki
#                     cloudflared). "private" -- barcha ichki tarmoqlar
#                     (Render, Docker va h.k.) uchun.
# TRUST_X_FORWARDED_FOR:
#     "auto"  (standart) -- so'rov ishonchli proksidan kelsagina headerlarga
#                           ishonadi. VPS + nginx uchun qo'shimcha sozlash KERAK EMAS.
#     "true"             -- har doim ishonadi (faqat backend to'g'ridan-to'g'ri
#                           internetga ochiq bo'lmasa!).
#     "false"            -- hech qachon ishonmaydi.
TRUSTED_PROXIES = os.getenv("TRUSTED_PROXIES", "127.0.0.1,::1").strip()
_tx = os.getenv("TRUST_X_FORWARDED_FOR", "auto").strip().lower()
TRUST_X_FORWARDED_FOR = _tx if _tx in ("auto", "true", "false") else "auto"

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

# Konstruktor limiti: har bir Google akkaunt (Gmail) uchun shuncha soatda 1 marta.
# Konstruktor vaqtinchalik ma'lumotlari (preview rasmlar) ham shuncha soatda
# tozalanadi (cleanup.py) -- shu sababli ikkalasi bitta qiymatdan olinadi.
CONSTRUCTOR_LIMIT_HOURS = max(1, int(os.getenv("CONSTRUCTOR_LIMIT_HOURS", "24")))
MAX_CART_ITEM_QUANTITY = 99

# Mahsulot izohlari: bitta Google akkaunt BITTA mahsulotga eng ko'pi bilan
# shuncha izoh yoza oladi va har bir izoh shuncha belgidan oshmaydi.
COMMENT_MAX_PER_USER_PER_PRODUCT = 5
COMMENT_MAX_LENGTH = 100
# Har bir izohni egasi eng ko'pi bilan shuncha marta tahrirlay oladi.
COMMENT_MAX_EDITS = 3
# Xavfli (XSS/SQL) matn yuborilganda izoh egasiga ko'rsatiladigan xabar.
COMMENT_BLOCKED_MESSAGE = "Ruxsat berilmagan xabar."
# Mahsulot oynasida ko'rsatiladigan eng yangi izohlar soni (sahifa og'irlashmasligi uchun).
COMMENT_LIST_LIMIT = 100

# Konstruktor rasmlari yoshini tekshirish oralig'i (daqiqa). Fayl faqat
# CONSTRUCTOR_LIMIT_HOURS dan eski bo'lsagina o'chadi; bu qiymat shunchaki
# tekshiruv qanchalik tez-tez bo'lishini bildiradi.
CLEANUP_CHECK_MINUTES = max(5, int(os.getenv("CLEANUP_CHECK_MINUTES", "30")))

# Ixtiyoriy: xatolarni kuzatish (Sentry). Bo'sh bo'lsa o'chiq.
SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()

# ---------------------------------------------------------------------------
# Google orqali kirish (OAuth 2.0 / Google Identity Services)
# ---------------------------------------------------------------------------
# MUHIM: Google "Client ID" MAXFIY KALIT EMAS -- u baribir brauzerda ko'rinadi
# (Google tugmasi shu bilan ishlaydi). Standart qiymat YO'Q -- o'zingizning
# Google Cloud loyihangiz Client ID'sini .env ga yozing. Uni backendda saqlashdan maqsad -- bitta
# joyda (.env / Render env) boshqarish va, eng muhimi, serverning O'ZI Google
# tokenidagi `aud` (qaysi ilova uchun berilgani)ni shu qiymatga solishtirib
# tekshirishi: boshqa ilova uchun berilgan token bu yerda qabul qilinmaydi.
# "Client Secret" bu oqimda umuman kerak emas -- uni hech qayerga yozmang.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()

# Mijoz (Google orqali kirgan foydalanuvchi) sessiya tokeni amal qilish muddati.
CUSTOMER_TOKEN_EXPIRE_DAYS = int(os.getenv("CUSTOMER_TOKEN_EXPIRE_DAYS", "30"))

# Google ID token faqat yaqinda (shu soniya ichida) berilgan bo'lsa qabul
# qilinadi -- eskirgan/o'g'irlangan tokenni qayta ishlatish (replay) oynasini
# qisqartiradi. Google tokeni o'zi 1 soat yashaydi.
GOOGLE_TOKEN_MAX_AGE_SECONDS = int(os.getenv("GOOGLE_TOKEN_MAX_AGE_SECONDS", "600"))
