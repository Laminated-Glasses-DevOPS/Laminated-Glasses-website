"""Yordamchi funksiyalar: rasmlar, savat tozalash, buyurtma kodi, matn
formatlash."""

import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from . import config, models


def _validate_image(file: UploadFile) -> str:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.ALLOWED_IMAGE_EXTENSIONS:
        allowed = ", ".join(sorted(config.ALLOWED_IMAGE_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Faqat quyidagi rasm formatlariga ruxsat bor: {allowed}",
        )
    return suffix


def save_product_image(file: UploadFile) -> str:
    """Rasmni diskka saqlaydi va faqat fayl nomini qaytaradi."""
    suffix = _validate_image(file)

    contents = file.file.read()
    max_bytes = config.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rasm hajmi {config.MAX_UPLOAD_SIZE_MB}MB dan katta bo'lmasligi kerak.",
        )

    filename = f"{uuid.uuid4().hex}{suffix}"
    with open(config.UPLOADS_DIR / filename, "wb") as f:
        f.write(contents)
    return filename


def delete_product_image(filename: Optional[str]) -> None:
    if not filename:
        return
    path = config.UPLOADS_DIR / filename
    if path.exists() and path.is_file():
        try:
            path.unlink()
        except OSError:
            pass


def build_image_url(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    return f"/uploads/{filename}"


def purge_expired_cart_items(db: Session, customer_id: Optional[int] = None) -> int:
    """Muddati o'tgan savat qatorlarini o'chiradi va nechtasi o'chirilganini
    qaytaradi. Savat har safar ochilganda chaqiriladi."""
    query = db.query(models.CartItem).filter(
        models.CartItem.expires_at <= datetime.utcnow()
    )
    if customer_id is not None:
        query = query.filter(models.CartItem.customer_id == customer_id)

    expired = query.all()
    for item in expired:
        db.delete(item)
    if expired:
        db.commit()
    return len(expired)


def days_left(expires_at: datetime) -> int:
    """Savatda necha kun qolganini yaxlitlab qaytaradi (kamida 0)."""
    delta = expires_at - datetime.utcnow()
    if delta.total_seconds() <= 0:
        return 0
    return max(1, -(-int(delta.total_seconds()) // 86400))


def generate_order_code(db: Session) -> str:
    """LG-000001 ko'rinishidagi ketma-ket buyurtma raqami."""
    last = db.query(models.Order).order_by(models.Order.id.desc()).first()
    next_id = (last.id + 1) if last else 1
    return f"LG-{next_id:06d}"


def format_price(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def build_order_message(
    order_code: str,
    customer_name: str,
    items: List[models.OrderItem],
    total_amount: float,
) -> str:
    """Telegramga yuboriladigan tayyor matn. Mijoz saytga yozgan ismi shu
    yerda albatta ko'rsatiladi -- sotuvchi buyurtmani shu ism bo'yicha
    admin panelda topadi."""
    lines = [
        "Assalomu alaykum! Saytdan buyurtma bermoqchiman.",
        "",
        f"Buyurtma raqami: {order_code}",
        f"Mijoz ismi: {customer_name}",
        "",
        "Tarkibi:",
    ]
    for index, item in enumerate(items, start=1):
        lines.append(
            f"{index}. {item.product_name} — {item.quantity} dona × "
            f"{format_price(item.unit_price)} = {format_price(item.line_total)} so'm"
        )
    lines += ["", f"Jami: {format_price(total_amount)} so'm"]
    return "\n".join(lines)


def telegram_url(username: str, text: str = "") -> str:
    handle = username.lstrip("@")
    base = f"https://t.me/{handle}"
    if not text:
        return base
    return f"{base}?text={quote(text)}"
