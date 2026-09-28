"""Google ID tokenni (Sign in with Google / Google Identity Services)
SERVER TOMONIDA tekshirish.

Brauzer Google'dan `credential` (imzolangan JWT) oladi va uni bizning backendga
yuboradi. Frontendga ishonib bo'lmaydi -- shu sabab token bu yerda to'liq
tekshiriladi:

  1) imzo -- Google'ning ommaviy kalitlari (JWKS) bilan RS256;
  2) `aud` -- aynan bizning GOOGLE_CLIENT_ID (boshqa ilova uchun berilgan
     token qabul qilinmaydi);
  3) `iss` -- accounts.google.com;
  4) `exp` -- muddati tugamagan; `iat` -- yaqinda berilgan (replay oynasi);
  5) `email_verified` -- Google email'ni tasdiqlagan.

Faqat `alg=RS256` qabul qilinadi (alg=none / HS256 chalkashtirish hujumlari
yopiq). Qo'shimcha kutubxona kerak emas: python-jose allaqachon
requirements.txt da, kalitlar esa standart `urllib` bilan olinadi va keshlanadi.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status
from jose import JWTError, jwt

from . import config

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_VALID_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# Soat farqi (server va Google orasida) uchun kichik ruxsat.
_CLOCK_SKEW_SECONDS = 120
_JWKS_DEFAULT_TTL = 3600
# Noma'lum `kid` bilan kelgan so'rovlar Google'ni bombardimon qilmasligi uchun.
_JWKS_MIN_REFETCH_INTERVAL = 60

_lock = threading.Lock()
_jwks_keys: dict = {}          # kid -> JWK
_jwks_expires_at: float = 0.0
_jwks_last_fetch: float = 0.0


@dataclass
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    name: str
    given_name: Optional[str]
    family_name: Optional[str]
    picture: Optional[str]
    locale: Optional[str]


def _fetch_jwks() -> tuple[dict, int]:
    req = urllib.request.Request(GOOGLE_JWKS_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        cache_control = resp.headers.get("Cache-Control", "") or ""
    ttl = _JWKS_DEFAULT_TTL
    for part in cache_control.split(","):
        part = part.strip().lower()
        if part.startswith("max-age="):
            try:
                ttl = max(60, int(part.split("=", 1)[1]))
            except ValueError:
                pass
    keys = {k["kid"]: k for k in body.get("keys", []) if k.get("kid")}
    if not keys:
        raise ValueError("Google kalitlar ro'yxati bo'sh")
    return keys, ttl


def _get_key(kid: str) -> Optional[dict]:
    """`kid` ga mos Google ommaviy kalitini qaytaradi (keshdan yoki yangidan)."""
    global _jwks_keys, _jwks_expires_at, _jwks_last_fetch
    now = time.monotonic()
    with _lock:
        cache_fresh = bool(_jwks_keys) and now < _jwks_expires_at
        if cache_fresh and kid in _jwks_keys:
            return _jwks_keys[kid]

        # Kesh eskirgan yoki `kid` topilmadi (Google kalitni almashtirgan
        # bo'lishi mumkin) -- yangilaymiz, lekin tez-tez emas.
        if _jwks_keys and (now - _jwks_last_fetch) < _JWKS_MIN_REFETCH_INTERVAL:
            return _jwks_keys.get(kid)

        try:
            keys, ttl = _fetch_jwks()
        except Exception:
            # Google'ga ulanib bo'lmadi. Eski kesh bo'lsa, undan foydalanamiz.
            _jwks_last_fetch = now
            if _jwks_keys:
                return _jwks_keys.get(kid)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google bilan bog'lanib bo'lmadi. Birozdan so'ng qayta urinib ko'ring.",
            )
        _jwks_keys = keys
        _jwks_expires_at = now + ttl
        _jwks_last_fetch = now
        return _jwks_keys.get(kid)


def _safe_picture(url: Optional[str]) -> Optional[str]:
    """Rasm havolasi frontendda <img src> ga qo'yiladi -- faqat https qabul."""
    return url if url and url.lower().startswith("https://") else None


def _invalid(detail: str = "Google tokeni yaroqsiz. Qaytadan urinib ko'ring.") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def verify_google_id_token(credential: str) -> GoogleIdentity:
    """Google ID tokenni tekshiradi. Yaroqsiz bo'lsa 401 (Google'ga ulanib
    bo'lmasa 503) HTTPException ko'taradi."""
    if not config.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google orqali kirish serverda sozlanmagan (GOOGLE_CLIENT_ID).",
        )

    try:
        header = jwt.get_unverified_header(credential)
    except JWTError:
        raise _invalid()

    if header.get("alg") != "RS256" or not header.get("kid"):
        raise _invalid()

    key = _get_key(header["kid"])
    if key is None:
        raise _invalid()

    try:
        claims = jwt.decode(
            credential,
            key,
            algorithms=["RS256"],
            audience=config.GOOGLE_CLIENT_ID,
            options={"verify_at_hash": False},
        )
    except JWTError:
        # imzo noto'g'ri, `aud` boshqa, muddati tugagan va h.k.
        raise _invalid()

    if claims.get("iss") not in _VALID_ISSUERS:
        raise _invalid()

    now = time.time()
    iat = claims.get("iat")
    if not isinstance(iat, (int, float)):
        raise _invalid()
    if iat > now + _CLOCK_SKEW_SECONDS or now - iat > config.GOOGLE_TOKEN_MAX_AGE_SECONDS:
        raise _invalid("Google tokeni eskirgan. Qaytadan kiring.")

    sub = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    if not sub or len(sub) > 40 or not email:
        raise _invalid()

    if claims.get("email_verified") not in (True, "true"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google akkauntingiz emaili tasdiqlanmagan.",
        )

    def _s(value, limit) -> Optional[str]:
        value = str(value).strip() if value else ""
        return value[:limit] if value else None

    name = _s(claims.get("name"), 120) or email.split("@")[0][:120]
    return GoogleIdentity(
        sub=sub,
        email=email[:255],
        email_verified=True,
        name=" ".join(name.split()),
        given_name=_s(claims.get("given_name"), 120),
        family_name=_s(claims.get("family_name"), 120),
        picture=_safe_picture(_s(claims.get("picture"), 500)),
        locale=_s(claims.get("locale"), 20),
    )
