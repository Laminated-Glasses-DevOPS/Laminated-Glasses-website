"""Parol xeshlash, JWT tokenlar va admin loginini brute-force dan himoya."""

import hashlib
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import config, models
from .database import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def password_fingerprint(password_hash: str) -> str:
    """Parol xeshidan olingan qisqa "barmoq izi". Admin tokeniga yoziladi:
    parol o'zgartirilganda barcha eski tokenlar (o'g'irlanganlari ham)
    avtomatik yaroqsiz bo'lib qoladi."""
    return hashlib.sha256((config.SECRET_KEY + password_hash).encode()).hexdigest()[:16]


def create_access_token(subject: str = "admin", pw_hash: str = "") -> str:
    expire = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, "iat": datetime.utcnow()}
    if pw_hash:
        payload["pwf"] = password_fingerprint(pw_hash)
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
    except JWTError:
        return None


def get_current_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """Barcha admin endpointlari uchun himoya qatlami."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Avtorizatsiyadan o'tilmagan. Admin panelga qayta kiring.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if payload is None or payload.get("sub") != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token yaroqsiz yoki muddati tugagan. Qaytadan kiring.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Parol o'zgargan bo'lsa, eski token endi o'tmaydi.
    settings = db.query(models.SiteSettings).first()
    if (
        settings is None
        or payload.get("pwf") != password_fingerprint(settings.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessiya eskirgan (parol o'zgargan). Qaytadan kiring.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


# ---------------------------------------------------------------------------
# Mijoz (Google orqali kirgan foydalanuvchi) sessiyasi
# ---------------------------------------------------------------------------
# Admin tokenidan ALOHIDA: `sub` = "customer" (admin uchun "admin"), shu sabab
# mijoz tokeni admin endpointlarida hech qachon o'tmaydi va aksincha. Token
# ichida mijoz `id`si bilan birga Google `sub`i ham bor -- baza tiklanib ID'lar
# boshqa odamga tegib qolsa ham, eski token begona akkauntni ochib bermaydi.


def create_customer_token(customer: models.Customer) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": "customer",
        "cid": customer.id,
        "gsub": customer.google_sub,
        "iat": now,
        "exp": now + timedelta(days=config.CUSTOMER_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM)


def get_current_customer(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.Customer:
    """Savat va buyurtma endpointlari uchun himoya: faqat Google orqali
    kirgan mijoz o'tadi."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Avval Google orqali kiring.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    payload = decode_access_token(credentials.credentials)
    if payload is None or payload.get("sub") != "customer":
        raise unauthorized

    customer = (
        db.query(models.Customer)
        .filter(models.Customer.id == payload.get("cid"))
        .first()
    )
    if (
        customer is None
        or not customer.google_sub
        or customer.google_sub != payload.get("gsub")
    ):
        raise unauthorized
    return customer


def get_optional_customer(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[models.Customer]:
    """Token bo'lsa va yaroqli bo'lsa mijozni qaytaradi, aks holda None
    (XATO KO'TARMAYDI) -- tashrif statistikasi kabi mehmon ham kira oladigan
    endpointlar uchun."""
    if credentials is None:
        return None
    payload = decode_access_token(credentials.credentials)
    if payload is None or payload.get("sub") != "customer":
        return None
    customer = db.query(models.Customer).filter(models.Customer.id == payload.get("cid")).first()
    if customer is None or not customer.google_sub or customer.google_sub != payload.get("gsub"):
        return None
    return customer


def _get_client_ip(request: Request) -> str:
    """Mijozning HAQIQIY IP manzilini aniqlaydi.

    XAVFSIZLIK ESLATMASI: oddiy "X-Forwarded-For" headeriga sukut bo'yicha
    ISHONIB BO'LMAYDI -- uni har qanday mijoz (brauzer yoki skript) o'zi
    xohlagancha o'zgartirib yuborishi mumkin. Agar shunga ishonilsa, login
    brute-force blokini va honeypot IP kuzatuvini har safar headerni
    almashtirib, osongina chetlab o'tish mumkin bo'lardi.

    Ustuvorlik:
      1) "CF-Connecting-IP" -- FAQAT Cloudflare Tunnel/Proxy orqali kelganda
         mavjud bo'ladi va Cloudflare tomonidan edge'da qo'yiladi, mijoz uni
         o'zgartira olmaydi (Cloudflare har doim o'zining haqiqiy qiymatini
         yozib qo'yadi) -- shuning uchun ishonchli.
      2) To'g'ridan-to'g'ri TCP ulanish manzili (`request.client.host`) --
         buni ham mijoz soxtalashtira olmaydi.
      3) "X-Forwarded-For" FAQAT admin buni config.TRUST_X_FORWARDED_FOR=true
         qilib, o'zi ishonadigan proksi (masalan o'z nginx serveri) orqasida
         ishlatayotganini aniq bildirgandagina ishlatiladi.
    """
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip and cf_ip.strip():
        return cf_ip.strip()

    if config.TRUST_X_FORWARDED_FOR:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

    if request.client:
        return request.client.host
    return "unknown"


# ---------------------------------------------------------------------------
# Oddiy, xotirada saqlanadigan "sliding window" so'rov cheklovchi.
#
# Maqsad -- tashqi kutubxonasiz, checkout/savat/rasm yuklash kabi og'ir
# amallarni skript orqali spam qilishning oldini olish. Haqiqiy mijozlar
# oddiy foydalanishda bunga hech qachon duch kelmaydi -- chegaralar odatiy
# foydalanish uchun ancha keng qilib tanlangan.
# ---------------------------------------------------------------------------

_rate_buckets: dict = defaultdict(deque)


def enforce_rate_limit(request: Request, bucket: str, max_calls: int, window_seconds: int) -> None:
    """Berilgan `bucket` nomi va so'rov IP manzili bo'yicha, oxirgi
    `window_seconds` ichida `max_calls` dan ko'p so'rov bo'lsa, 429 xatosi
    bilan to'xtatadi."""
    ip = _get_client_ip(request)
    key = f"{bucket}:{ip}"
    now = time.monotonic()
    timestamps = _rate_buckets[key]

    while timestamps and now - timestamps[0] > window_seconds:
        timestamps.popleft()

    if len(timestamps) >= max_calls:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Juda ko'p so'rov yuborildi. Birozdan so'ng qayta urinib ko'ring.",
        )

    timestamps.append(now)


def check_login_allowed(request: Request, db: Session) -> None:
    ip = _get_client_ip(request)
    record = db.query(models.LoginAttempt).filter_by(ip_address=ip).first()
    if record and record.locked_until and record.locked_until > datetime.utcnow():
        remaining = int((record.locked_until - datetime.utcnow()).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Juda ko'p noto'g'ri urinish. {remaining} daqiqadan so'ng qayta urining.",
        )


def register_failed_login(request: Request, db: Session) -> None:
    ip = _get_client_ip(request)
    record = db.query(models.LoginAttempt).filter_by(ip_address=ip).first()
    if record is None:
        record = models.LoginAttempt(ip_address=ip, attempts=0)
        db.add(record)

    record.attempts = (record.attempts or 0) + 1
    if record.attempts >= config.MAX_LOGIN_ATTEMPTS:
        record.locked_until = datetime.utcnow() + timedelta(
            minutes=config.LOGIN_LOCKOUT_MINUTES
        )
        record.attempts = 0
    db.commit()


def register_successful_login(request: Request, db: Session) -> None:
    ip = _get_client_ip(request)
    record = db.query(models.LoginAttempt).filter_by(ip_address=ip).first()
    if record:
        record.attempts = 0
        record.locked_until = None
        db.commit()
