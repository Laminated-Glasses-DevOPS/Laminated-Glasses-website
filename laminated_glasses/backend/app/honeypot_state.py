"""Honeypot uchun umumiy, real-vaqtdagi holat: faol shaxsiy xabar va
brauzer heartbeat (yurak urishi).

`main.py` (400-sahifani birinchi marta chizganda) va `routers/public.py`
(honeypot sahifasi ochiq turgan paytda muntazam so'raydigan "pulse"
endpointi) shu yerdagi funksiyalarni baham ko'radi -- shunday qilib IP
holati va faol xabar mantiqi bitta joyda saqlanadi va ikkalasi bir-biridan
farq qilib qolmaydi.
"""

from datetime import datetime
from typing import Optional

from . import models

# Honeypot sahifasi qancha tez-tez pulse yuborishini frontend bilan
# kelishilgan qiymat (frontend/shield.py da ham shu son ishlatiladi).
HEARTBEAT_INTERVAL_SECONDS = 4

# IP "Onlayn" deb hisoblanadigan oyna: heartbeat intervalidan taxminan 3x
# katta -- bitta tarmoq kechikishi yoki o'tkazib yuborilgan pulsni hisobga
# oladi, lekin sezilarli kechikishga yo'l qo'ymaydi (haqiqiy "real-time"
# tuyulishi uchun bir necha soniyadan oshmasligi kerak).
ONLINE_WINDOW_SECONDS = HEARTBEAT_INTERVAL_SECONDS * 3


def active_honeypot_message(db, ip_address: str) -> Optional["models.HoneypotMessage"]:
    """Admin ushbu IP uchun yozgan, hali bekor qilinmagan shaxsiy xabarni
    qaytaradi (eng oxirgisi). Faol xabar bo'lmasa None."""
    return (
        db.query(models.HoneypotMessage)
        .filter(
            models.HoneypotMessage.ip_address == ip_address,
            models.HoneypotMessage.is_active == 1,
        )
        .order_by(models.HoneypotMessage.created_at.desc())
        .first()
    )


def mark_honeypot_message_shown(db, msg_id: int) -> None:
    row = db.get(models.HoneypotMessage, msg_id)
    if row:
        row.shown_count = (row.shown_count or 0) + 1
        row.last_shown_at = datetime.utcnow()
        db.commit()


def record_heartbeat(db, ip_address: str, is_open: bool = True) -> None:
    """Honeypot sahifasi shu IP dan hali ham ochiq turganini (yoki endi
    yopilganini, `is_open=False`) qayd etadi. Xato bo'lsa ham saytga ta'sir
    qilmasligi uchun sukut bilan o'tkazib yuboriladi."""
    try:
        row = db.get(models.HoneypotHeartbeat, ip_address)
        if row is None:
            row = models.HoneypotHeartbeat(ip_address=ip_address)
            db.add(row)
        row.last_seen_at = datetime.utcnow()
        row.is_open = 1 if is_open else 0
        db.commit()
    except Exception:
        db.rollback()


def is_ip_online(heartbeat: Optional["models.HoneypotHeartbeat"]) -> bool:
    """Berilgan heartbeat yozuvi asosida IP hozir HAQIQATAN onlaynmi
    (sahifa ochiq turibdimi) hisoblaydi -- shunchaki oxirgi hujum vaqtiga
    emas, oxirgi "men ochiqman" signaliga qaraydi."""
    if heartbeat is None or not heartbeat.is_open:
        return False
    diff = (datetime.utcnow() - heartbeat.last_seen_at).total_seconds()
    return diff <= ONLINE_WINDOW_SECONDS
