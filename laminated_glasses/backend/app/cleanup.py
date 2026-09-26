"""Davriy fon tozalash vazifalari.

Talab qilingan tartib:
    - Xavfsizlik jurnali (SecurityEvent)      -> har 24 soatda TO'LIQ tozalanadi
    - Konstruktor preview rasmlari (vaqtinchalik) -> har 24 soatda TO'LIQ tozalanadi
    - Yangiliklar (NewsPost)                  -> har 48 soatda TO'LIQ tozalanadi
    - Buyurtmalar (Order + OrderItem)         -> har 48 soatda TO'LIQ tozalanadi

Bu yerga HECH QACHON tegilmaydigan narsalar (ataylab chetlab o'tiladi):
    - Mahsulotlar va ularning joriy rasmlari (models.Product, uploads/ papkasi)
    - Mijozlar (models.Customer) -- ismlari va ma'lumotlari saqlanib qoladi
    - Konstruktor o'lchamlari (models.ConstructorSize) -- faqat vaqtinchalik
      preview rasmlari tozalanadi, o'lchamlarning o'zi emas

Alohida kutubxona (masalan APScheduler) talab qilinmasligi uchun oddiy
asyncio fon vazifalari sifatida ishlaydi: server ishga tushganda
`start_background_cleanup_tasks()` chaqiriladi va har bir vazifa o'z
intervalida cheksiz tsiklda uxlab-ishlab turadi.
"""

import asyncio
import logging

from . import backup, models, utils
from .database import SessionLocal

logger = logging.getLogger("cleanup")

SECURITY_LOG_INTERVAL_SECONDS = 24 * 3600
CONSTRUCTOR_PREVIEW_INTERVAL_SECONDS = 24 * 3600
NEWS_INTERVAL_SECONDS = 48 * 3600
ORDERS_INTERVAL_SECONDS = 48 * 3600


def purge_security_logs() -> int:
    """Havfsizlik (SQLi/XSS honeypot) jurnalini, avval Excel'ga zaxiralab,
    to'liq tozalaydi."""
    db = SessionLocal()
    try:
        events = db.query(models.SecurityEvent).order_by(models.SecurityEvent.created_at.asc()).all()
        if not events:
            return 0
        backup.backup_security_logs(events)
        count = db.query(models.SecurityEvent).delete()
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def purge_constructor_previews() -> int:
    """Konstruktor \"Share\" orqali yuklangan vaqtinchalik preview
    rasmlarini (uploads/constructor_previews/) to'liq o'chiradi.
    Mahsulot rasmlari BOSHQA papkada saqlangani uchun bunga tegilmaydi."""
    directory = utils.CONSTRUCTOR_PREVIEWS_DIR
    count = 0
    if directory.exists():
        for path in directory.iterdir():
            if path.is_file():
                try:
                    path.unlink()
                    count += 1
                except OSError:
                    pass
    return count


def purge_news() -> int:
    """Yangiliklar bo'limidagi barcha yozuvlarni, avval Excel'ga
    zaxiralab, to'liq tozalaydi."""
    db = SessionLocal()
    try:
        posts = db.query(models.NewsPost).order_by(models.NewsPost.created_at.asc()).all()
        if not posts:
            return 0
        backup.backup_news(posts)
        count = db.query(models.NewsPost).delete()
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def purge_orders() -> int:
    """Buyurtmalarni (va ularning tarkibiy qatorlarini) to'liq tozalaydi.

    Har bir Order ORM sathida (`db.delete`) o'chiriladi -- shunday qilib
    Order.items uchun belgilangan `cascade=\"all, delete-orphan\"` ishlaydi
    va OrderItem qatorlari ham birga o'chadi. Customer jadvaliga
    (mijoz ismi/ma'lumotlari) hech qanday cascade yo'q -- ular saqlanib
    qoladi. O'chirishdan OLDIN barcha buyurtmalar (va ularning tarkibi)
    Excel faylga to'liq zaxiralanadi."""
    db = SessionLocal()
    try:
        orders = db.query(models.Order).order_by(models.Order.created_at.asc()).all()
        if not orders:
            return 0
        backup.backup_orders(orders)
        count = len(orders)
        for order in orders:
            db.delete(order)
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def _run_periodically(name: str, interval_seconds: int, func) -> None:
    """Berilgan funksiyani cheksiz tsiklda, har safar `interval_seconds`
    kutib, ishga tushiradi. Xato yuz bersa ham tsikl to'xtamaydi -- xato
    faqat log qilinadi, shunda bitta muvaffaqiyatsiz tozalash keyingi
    tsikllarni to'xtatib qo'ymaydi."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            removed = await asyncio.to_thread(func)
            logger.info("cleanup[%s]: %s ta yozuv/fayl tozalandi", name, removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("cleanup[%s]: tozalash vaqtida xato yuz berdi", name)


def start_background_cleanup_tasks() -> list:
    """Barcha davriy tozalash vazifalarini fon rejimida ishga tushiradi va
    yaratilgan asyncio Task obyektlari ro'yxatini qaytaradi (server
    to'xtaganda bekor qilish uchun)."""
    return [
        asyncio.create_task(
            _run_periodically("havfsizlik_jurnali", SECURITY_LOG_INTERVAL_SECONDS, purge_security_logs)
        ),
        asyncio.create_task(
            _run_periodically(
                "konstruktor_previewlari", CONSTRUCTOR_PREVIEW_INTERVAL_SECONDS, purge_constructor_previews
            )
        ),
        asyncio.create_task(
            _run_periodically("yangiliklar", NEWS_INTERVAL_SECONDS, purge_news)
        ),
        asyncio.create_task(
            _run_periodically("buyurtmalar", ORDERS_INTERVAL_SECONDS, purge_orders)
        ),
    ]
