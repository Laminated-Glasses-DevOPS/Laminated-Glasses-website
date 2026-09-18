"""Parol xeshlash, JWT tokenlar va admin loginini brute-force dan himoya."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import config, models

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def create_access_token(subject: str = "admin") -> str:
    expire = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, "iat": datetime.utcnow()}
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
    except JWTError:
        return None


def get_current_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
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
    return payload


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


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
