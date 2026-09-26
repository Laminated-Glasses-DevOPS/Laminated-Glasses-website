"""Admin panelidagi "Baza holati" bo'limi uchun yordamchi funksiyalar:

    - joriy baza fayli, uploads/ va backups/ papkalarining hajmini va disk
      holatini hisoblash (StorageDagi holat);
    - har bir jadvaldagi qatorlar sonini hisoblash;
    - bazani (.db fayl) yuklab olish uchun ISHONCHLI, izchil nusxasini
      yaratish (SQLite'ning o'z backup API'si orqali -- oddiy fayl nusxasi
      emas, aks holda server yozayotgan paytga to'g'ri kelib qolsa, yarim
      yozilgan/nomos fayl olinishi mumkin edi);
    - yuklangan .db faylni ("konfiguratsiyani qayta yuklash") ehtiyotkorlik
      bilan tekshirib, joriy bazani almashtirish.

XAVFSIZLIK: bazani almashtirish (restore) juda halokatli amal -- shu sabab
bu yerdagi funksiyalar: (1) yuklangan faylni ANIQ SQLite fayl ekanini va
kutilgan asosiy jadvallarga ega ekanini ishga tushirishdan OLDIN tekshiradi,
(2) hajmini cheklaydi, (3) almashtirishdan OLDIN joriy bazaning zaxira
nusxasini avtomatik yaratadi (shu tufayli noto'g'ri fayl yuklab
yuborilsa ham, admin darhol oldingi holatga qaytarishi mumkin).
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import config, models
from .database import Base, engine

SQLITE_MAGIC = b"SQLite format 3\x00"

# Bazada, kamida shu jadvallar mavjud bo'lishi shart -- aks holda bu
# "Laminated Glasses" loyihasining bazasi emas (yoki buzilgan/bo'sh fayl).
REQUIRED_TABLES = {
    "products",
    "categories",
    "site_settings",
    "orders",
    "order_items",
}

_TABLE_LABELS = [
    (models.Product, "Mahsulotlar"),
    (models.Category, "Kategoriyalar"),
    (models.Customer, "Mijozlar"),
    (models.Order, "Buyurtmalar"),
    (models.OrderItem, "Buyurtma qatorlari"),
    (models.NewsPost, "Yangiliklar"),
    (models.ConstructorSize, "Konstruktor o'lchamlari"),
    (models.SecurityEvent, "Xavfsizlik jurnali yozuvlari"),
]


def _db_path() -> Path:
    # config.DATABASE_URL = "sqlite:///<yo'l>"
    return Path(config.DATABASE_URL.replace("sqlite:///", "", 1))


def _dir_size_bytes(directory: Path) -> int:
    if not directory.exists():
        return 0
    total = 0
    for f in directory.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def get_database_status(db: Session) -> dict:
    db_path = _db_path()
    db_size = db_path.stat().st_size if db_path.exists() else 0

    uploads_size = _dir_size_bytes(config.UPLOADS_DIR)
    backups_size = _dir_size_bytes(config.BACKUPS_DIR)

    disk_total, disk_used, disk_free = shutil.disk_usage(config.DATA_DIR)

    tables = []
    for model, label in _TABLE_LABELS:
        try:
            count = db.query(model).count()
        except Exception:
            count = 0
        tables.append({"table": model.__tablename__, "label": label, "rows": count})

    last_snapshot_at = None
    if config.DB_SNAPSHOTS_DIR.exists():
        snapshots = sorted(
            config.DB_SNAPSHOTS_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime
        )
        if snapshots:
            last_snapshot_at = datetime.utcfromtimestamp(snapshots[-1].stat().st_mtime)

    return {
        "db_size_kb": round(db_size / 1024, 1),
        "uploads_size_kb": round(uploads_size / 1024, 1),
        "backups_size_kb": round(backups_size / 1024, 1),
        "disk_total_kb": round(disk_total / 1024, 1),
        "disk_used_kb": round(disk_used / 1024, 1),
        "disk_free_kb": round(disk_free / 1024, 1),
        "disk_used_percent": round((disk_used / disk_total) * 100, 1) if disk_total else 0.0,
        "tables": tables,
        "last_snapshot_at": last_snapshot_at,
    }


def make_consistent_db_copy(target_path: Path) -> None:
    """SQLite'ning o'z backup API'si orqali joriy bazaning IZCHIL nusxasini
    yaratadi -- shu tufayli ayni shu daqiqada boshqa so'rov yozayotgan
    bo'lsa ham, chalasiga/nomos fayl olinmaydi (oddiy `shutil.copy` bunga
    kafolat bermaydi)."""
    source = sqlite3.connect(str(_db_path()))
    try:
        dest = sqlite3.connect(str(target_path))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()


def _validate_sqlite_file(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Fayl bo'sh yoki mavjud emas."
        )

    with open(path, "rb") as f:
        header = f.read(16)
    if header != SQLITE_MAGIC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Bu fayl haqiqiy SQLite baza fayli emas. Faqat shu admin "
                "paneldan avval yuklab olingan .db faylni qayta yuklang."
            ),
        )

    try:
        conn = sqlite3.connect(str(path))
        try:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            table_names = {row[0] for row in cur.fetchall()}
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Fayl SQLite bazasi sifatida ochilmadi: {exc}",
        )

    missing = REQUIRED_TABLES - table_names
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Fayl 'Laminated Glasses' bazasiga o'xshamaydi -- kutilgan "
                f"jadvallar topilmadi: {', '.join(sorted(missing))}."
            ),
        )


def _enforce_snapshot_limit() -> None:
    snapshots = sorted(
        config.DB_SNAPSHOTS_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime
    )
    while len(snapshots) >= config.MAX_DB_SNAPSHOTS:
        oldest = snapshots.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass


def restore_database(uploaded_tmp_path: Path) -> dict:
    """Yuklangan faylni tekshirgach, joriy bazani almashtiradi.

    Qadamlar (har biri xato bo'lsa, joriy baza TEGILMAGAN holda qoladi):
      1) Yuklangan fayl haqiqatan SQLite ekani va kerakli jadvallarga ega
         ekani tekshiriladi.
      2) Joriy baza avval DB_SNAPSHOTS_DIR ga xavfsizlik nusxasi sifatida
         saqlanadi (eskilari MAX_DB_SNAPSHOTS dan oshsa, avtomatik
         o'chiriladi).
      3) SQLAlchemy dvigateli (`engine`) o'zining barcha ochiq
         ulanishlarini yopadi (`dispose()`), shundan keyingina fayl xavfsiz
         almashtiriladi -- aks holda eski ulanish yangi faylni ko'rmasligi
         yoki fayl banд bo'lib qolishi mumkin edi.
      4) Fayl almashtirilgach, jadval sxemasi joriy kod bilan mos bo'lishi
         uchun forward-compatible ALTER TABLE migratsiyalari qayta
         ishga tushiriladi (main.py dagi bilan bir xil mantiq).
    """
    _validate_sqlite_file(uploaded_tmp_path)

    max_bytes = config.MAX_DB_UPLOAD_SIZE_MB * 1024 * 1024
    if uploaded_tmp_path.stat().st_size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Fayl hajmi {config.MAX_DB_UPLOAD_SIZE_MB}MB dan katta bo'lmasligi kerak.",
        )

    db_path = _db_path()
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    _enforce_snapshot_limit()
    snapshot_path = config.DB_SNAPSHOTS_DIR / f"pre_restore_{timestamp}.db"
    if db_path.exists():
        make_consistent_db_copy(snapshot_path)

    engine.dispose()
    try:
        shutil.copyfile(uploaded_tmp_path, db_path)
        # Forward-compatible migratsiyalar (main.py bilan bir xil, yangi
        # yuklangan baza eski versiyada yaratilgan bo'lishi mumkin).
        with engine.begin() as conn:
            try:
                conn.exec_driver_sql(
                    "ALTER TABLE products ADD COLUMN images_json TEXT NOT NULL DEFAULT '[]'"
                )
            except Exception:
                pass
            try:
                conn.exec_driver_sql(
                    "ALTER TABLE constructor_sizes ADD COLUMN pane_count INTEGER NOT NULL DEFAULT 1"
                )
            except Exception:
                pass
        Base.metadata.create_all(bind=engine)
    except Exception as exc:
        # Nimadir noto'g'ri ketsa, xavfsizlik nusxasidan darhol tiklaymiz --
        # sayt hech qachon "bazasiz" holatda qolmasligi kerak.
        if snapshot_path.exists():
            engine.dispose()
            shutil.copyfile(snapshot_path, db_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bazani tiklashda xatolik yuz berdi, o'zgarishlar bekor qilindi: {exc}",
        )

    return {
        "restored_at": datetime.utcnow(),
        "snapshot_filename": snapshot_path.name if snapshot_path.exists() else None,
    }


def resolve_snapshot_path(filename: str) -> "Path | None":
    """backup.resolve_backup_path bilan bir xil mantiq: yo'l-traversal
    urinishlaridan himoyalangan, faqat DB_SNAPSHOTS_DIR ichidan qidiradi."""
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.endswith(".db"):
        return None
    candidate = config.DB_SNAPSHOTS_DIR / safe_name
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def list_snapshots() -> List[dict]:
    if not config.DB_SNAPSHOTS_DIR.exists():
        return []
    out = []
    for f in config.DB_SNAPSHOTS_DIR.glob("*.db"):
        stat = f.stat()
        out.append(
            {
                "filename": f.name,
                "created_at": datetime.utcfromtimestamp(stat.st_mtime),
                "size_kb": round(stat.st_size / 1024, 1),
            }
        )
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return out
