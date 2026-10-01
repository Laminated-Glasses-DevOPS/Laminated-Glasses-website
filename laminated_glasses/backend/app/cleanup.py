"""Davriy fon tozalash vazifalari.

FAQAT bitta narsa avtomatik o'chiriladi:
    - Konstruktor bo'limida foydalanuvchilar yuklagan rasmlar
      (uploads/constructor_previews/) -- yoshi CONSTRUCTOR_LIMIT_HOURS
      (standart: 24 soat) dan oshgan fayllar.
    - Shu bilan birga muddati o'tgan konstruktor limit yozuvlari
      (models.ConstructorUsage) -- bular foydalanuvchi rasmi emas, faqat
      "24 soatda 1 marta" hisobini yuritish uchun.

HECH QACHON avtomatik o'chirilmaydigan narsalar (faqat admin panel orqali
QO'LDA o'chiriladi):
    - Buyurtmalar (Order + OrderItem)
    - Yangiliklar (NewsPost)
    - Xavfsizlik jurnali (SecurityEvent)
    - Mahsulotlar va ularning rasmlari, mijozlar, konstruktor o'lchamlari

Tozalash "yosh bo'yicha" ishlaydi: har bir fayl o'z yaratilgan vaqtidan
boshlab hisoblanadi. Shu sabab server qayta ishga tushsa yoki VPS'da kod
yangilansa ham 24 soatlik hisob "nolga tushib" ketmaydi (avvalgi
"N soat uxlab, keyin hammasini o'chir" usuli qayta ishga tushirishlarda
hech qachon ishga tushmay qolishi mumkin edi). Tozalash tekshiruvi har
CLEANUP_CHECK_MINUTES daqiqada (standart 30) va server ishga tushganda
darhol bajariladi.

Alohida kutubxona (APScheduler) talab qilinmaydi -- oddiy asyncio vazifa.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

from . import config, models, utils
from .database import SessionLocal

logger = logging.getLogger("cleanup")


def purge_constructor_previews() -> int:
    """Konstruktorga yuklangan rasmlardan yoshi limit oynasidan (standart
    24 soat) oshganlarini o'chiradi. Yangi, hali muddati o'tmagan fayllarga
    tegilmaydi. Mahsulot rasmlari boshqa papkada -- ularga tegilmaydi."""
    directory = utils.CONSTRUCTOR_PREVIEWS_DIR
    count = 0
    if directory.exists():
        cutoff_ts = time.time() - config.CONSTRUCTOR_LIMIT_HOURS * 3600
        for path in directory.iterdir():
            try:
                if path.is_file() and path.name != ".gitkeep" and path.stat().st_mtime <= cutoff_ts:
                    path.unlink()
                    count += 1
            except OSError:
                pass
    count += purge_constructor_usage()
    return count


def purge_constructor_usage() -> int:
    """Limit oynasi o'tib bo'lgan konstruktor foydalanish yozuvlarini
    o'chiradi. Faol (hali muddati o'tmagan) yozuvlarga tegilmaydi --
    foydalanuvchi limiti buzilmaydi."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=config.CONSTRUCTOR_LIMIT_HOURS)
        removed = (
            db.query(models.ConstructorUsage)
            .filter(models.ConstructorUsage.used_at <= cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        return removed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def _run_periodically(name: str, interval_seconds: int, func) -> None:
    """Funksiyani darhol (server ishga tushganda), so'ng har
    `interval_seconds` da ishga tushiradi. Xato yuz bersa ham tsikl
    to'xtamaydi -- xato faqat log qilinadi."""
    while True:
        try:
            removed = await asyncio.to_thread(func)
            if removed:
                logger.info("cleanup[%s]: %s ta yozuv/fayl tozalandi", name, removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("cleanup[%s]: tozalash vaqtida xato yuz berdi", name)
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            raise


def start_background_cleanup_tasks() -> list:
    """Davriy tozalash vazifasini fon rejimida ishga tushiradi va yaratilgan
    asyncio Task obyektlari ro'yxatini qaytaradi."""
    return [
        asyncio.create_task(
            _run_periodically(
                "konstruktor_rasmlari",
                config.CLEANUP_CHECK_MINUTES * 60,
                purge_constructor_previews,
            )
        ),
    ]
