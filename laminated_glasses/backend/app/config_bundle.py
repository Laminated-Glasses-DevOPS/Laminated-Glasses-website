"""Konfiguratsiya to'plamini (mahsulotlar+rasmlar, constructor sozlamalari,
admin paroli, statistika/attack loglari) yagona .zip fayl sifatida eksport
qilish va xuddi shu tuzilishdagi zip'ni qayta import qilish uchun modul.

Zip tarkibi (har biri IXTIYORIY -- import paytida qaysi biri bo'lmasa,
o'sha bo'lim xatosiz o'tkazib yuboriladi):

    tovar_rasmlari/                -- mahsulot rasmlari (uploads/ nusxasi)
    mahsulotlar.db                 -- categories + products jadvallari
                                       (nomi, tavsifi va h.k.)
    admin_constructor_settings.db  -- constructor_sizes jadvali
    admin_password.db              -- site_settings jadvali (parol hash'i,
                                       telegram, sayt nomi)
    statistics.db                  -- security_events (attack IP'lari,
                                       XSS/SQLi urinishlari) + visit_logs
                                       (tashriflar statistikasi)

MUHIM: bular ALOHIDA, mustaqil SQLite fayllar -- asosiy
`laminated_glasses.db` ning bo'lagi emas, balki undan ANIQ shu jadvallar
ajratib olingan mustaqil nusxalar. Eksport paytida asosiy bazadan IZCHIL
(consistent) nusxa olinadi (`db_admin.make_consistent_db_copy` bilan bir
xil mantiq), so'ng shu nusxadan har bir bo'lim uchun kerakli jadval(lar)
ajratib olinadi -- shu tufayli eksport paytida serverga boshqa so'rovlar
kelayotgan bo'lsa ham, natija hech qachon "yarim yozilgan" holatda
bo'lmaydi.

Import har bir MAVJUD bo'lim uchun:
  1) fayl haqiqatan SQLite ekanini va kutilgan jadval(lar)ga ega ekanini
     tekshiradi (hech narsa o'zgartirmasdan oldin -- shu tufayli bitta
     bo'lim buzuq bo'lsa, boshqa bo'limlar ham qo'llanilmaydi: yo hammasi,
     yo hech narsa);
  2) shu bo'limga tegishli jadval(lar)ni asosiy bazada TO'LIQ ALMASHTIRADI
     (eski qatorlar o'chirilib, fayldagilar bilan to'ldiriladi -- oddiy
     qo'shish/merge emas, aks holda ID to'qnashuvi va eski/yangi
     ma'lumotlar aralashib ketishi mumkin edi);
  3) almashtirishdan OLDIN, "Bazani tiklash" funksiyasidagi kabi, joriy
     bazaning to'liq xavfsizlik nusxasi avtomatik olinadi -- xato ketsa
     yoki natija kutilganidek bo'lmasa, admin darhol oldingi holatga
     qaytarishi mumkin.

Rasmlar (`tovar_rasmlari/`) mavjud bo'lsa, ular uploads/ papkasiga
NUSXALANADI (bir xil nomli fayllar ustidan yoziladi, boshqa mavjud
rasmlar o'chirilmaydi) -- shu tufayli qisman import (masalan faqat
statistika) mavjud rasmlarga tegmaydi.
"""

from __future__ import annotations

import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import HTTPException, status

from . import config, db_admin
from .database import Base, engine

SQLITE_MAGIC = b"SQLite format 3\x00"

IMAGES_FOLDER_NAME = "tovar_rasmlari"

# Har bir bo'lim fayli -- ichidagi jadvallar. Bular importda "shu jadval
# bo'lishi shart" ro'yxati sifatida ham ishlatiladi (bu kichik,
# bitta-maqsadli fayllar bo'lgani uchun barcha jadval majburiy).
BUNDLE_TABLES: Dict[str, List[str]] = {
    "mahsulotlar.db": ["categories", "products"],
    "admin_constructor_settings.db": ["constructor_sizes"],
    "admin_password.db": ["site_settings"],
    "statistics.db": ["security_events", "visit_logs"],
}


def _main_db_path() -> Path:
    return Path(config.DATABASE_URL.replace("sqlite:///", "", 1))


# ---------- Eksport ----------


def _extract_section(source_db_path: Path, tables: List[str], target_path: Path) -> None:
    """`source_db_path` (izchil to'liq nusxa)dan faqat `tables`
    ro'yxatidagi jadvallarni yangi, mustaqil SQLite faylga ko'chiradi."""
    if target_path.exists():
        target_path.unlink()
    conn = sqlite3.connect(str(target_path))
    try:
        conn.execute("ATTACH DATABASE ? AS src", (str(source_db_path),))
        for table in tables:
            conn.execute(f"CREATE TABLE {table} AS SELECT * FROM src.{table}")
        conn.commit()
        conn.execute("DETACH DATABASE src")
    finally:
        conn.close()


def build_export_bundle(target_zip_path: Path) -> None:
    """To'liq konfiguratsiya to'plamini `target_zip_path` yo'liga .zip
    fayl sifatida yozadi."""
    tmp_full_copy = config.DATA_DIR / f".bundle_src_{datetime.utcnow():%Y%m%d%H%M%S%f}.db"
    db_admin.make_consistent_db_copy(tmp_full_copy)

    tmp_dir = config.DATA_DIR / f".bundle_build_{datetime.utcnow():%Y%m%d%H%M%S%f}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        section_paths: Dict[str, Path] = {}
        for filename, tables in BUNDLE_TABLES.items():
            section_path = tmp_dir / filename
            _extract_section(tmp_full_copy, tables, section_path)
            section_paths[filename] = section_path

        with zipfile.ZipFile(target_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, path in section_paths.items():
                zf.write(path, arcname=filename)
            if config.UPLOADS_DIR.exists():
                for img in config.UPLOADS_DIR.rglob("*"):
                    if img.is_file():
                        zf.write(img, arcname=f"{IMAGES_FOLDER_NAME}/{img.name}")
    finally:
        tmp_full_copy.unlink(missing_ok=True)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------- Import ----------


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """`zf`ni `dest` ichiga, "zip-slip" (yo'l-traversal, masalan
    ../../etc/passwd) hujumlaridan himoyalangan holda ochadi, va umumiy
    siqilmagan hajmni cheklaydi (zip-bomb himoyasi)."""
    dest_resolved = dest.resolve()
    total_uncompressed = 0
    max_bytes = config.MAX_CONFIG_BUNDLE_UPLOAD_SIZE_MB * 1024 * 1024

    for member in zf.infolist():
        member_path = (dest / member.filename).resolve()
        if member_path != dest_resolved and dest_resolved not in member_path.parents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Zip fayl ichida ruxsatsiz yo'l (path traversal) aniqlandi.",
            )
        total_uncompressed += member.file_size
        if total_uncompressed > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zip fayl siqilmagan holda {config.MAX_CONFIG_BUNDLE_UPLOAD_SIZE_MB}MB dan katta.",
            )

    zf.extractall(dest)


def _validate_section_file(path: Path, tables: List[str]) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"{path.name} fayli bo'sh yoki mavjud emas."
        )
    with open(path, "rb") as f:
        header = f.read(16)
    if header != SQLITE_MAGIC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{path.name} haqiqiy SQLite baza fayli emas.",
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
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"{path.name} SQLite sifatida ochilmadi: {exc}"
        )
    missing = set(tables) - table_names
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{path.name} kutilgan jadvallarga ega emas: {', '.join(sorted(missing))}.",
        )


def _merge_section(section_db_path: Path, tables: List[str]) -> None:
    """`section_db_path` ichidagi jadvallarni asosiy bazaga TO'LIQ
    ALMASHTIRIB qo'shadi: har bir jadvalning eski qatorlari o'chiriladi,
    so'ng fayldagi qatorlar bilan to'ldiriladi."""
    main_path = _main_db_path()
    conn = sqlite3.connect(str(main_path))
    try:
        conn.execute("ATTACH DATABASE ? AS part", (str(section_db_path),))
        conn.execute("BEGIN")
        for table in tables:
            conn.execute(f"DELETE FROM {table}")
            conn.execute(f"INSERT INTO {table} SELECT * FROM part.{table}")
        conn.commit()
        conn.execute("DETACH DATABASE part")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _enforce_bundle_snapshot_limit() -> None:
    snapshots = sorted(config.DB_SNAPSHOTS_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime)
    while len(snapshots) >= config.MAX_DB_SNAPSHOTS:
        oldest = snapshots.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass


def import_config_bundle(uploaded_zip_path: Path) -> dict:
    """Yuklangan .zip'ni tekshirib, ichidagi MAVJUD bo'limlarnigina
    asosiy bazaga/uploads papkasiga qo'llaydi. Zipda bo'lmagan bo'limlar
    xatosiz o'tkazib yuboriladi -- natijada `skipped` ro'yxatida
    ko'rsatiladi.
    """
    if not zipfile.is_zipfile(uploaded_zip_path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fayl haqiqiy .zip arxiv emas.")

    extract_dir = config.DATA_DIR / f".bundle_import_{datetime.utcnow():%Y%m%d%H%M%S%f}"
    extract_dir.mkdir(parents=True, exist_ok=True)

    applied: List[str] = []
    skipped: List[str] = []
    snapshot_name: Optional[str] = None

    try:
        with zipfile.ZipFile(uploaded_zip_path) as zf:
            _safe_extract(zf, extract_dir)

        # Avval FAQAT tekshiramiz, hech narsani o'zgartirmasdan -- shu
        # tufayli birorta bo'lim buzuq bo'lsa, boshqalari ham qo'llanilmay,
        # baza yarim-import holatida qolib ketmaydi (yo hammasi, yo hech
        # narsa).
        present_sections: Dict[str, Path] = {}
        for filename, tables in BUNDLE_TABLES.items():
            candidate = extract_dir / filename
            if candidate.exists():
                _validate_section_file(candidate, tables)
                present_sections[filename] = candidate
            else:
                skipped.append(filename)

        images_dir = extract_dir / IMAGES_FOLDER_NAME
        has_images = images_dir.exists() and images_dir.is_dir()
        if not has_images:
            skipped.append(IMAGES_FOLDER_NAME)

        if not present_sections and not has_images:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Zip ichida tanish bo'limlardan birortasi ham topilmadi.",
            )

        if present_sections:
            _enforce_bundle_snapshot_limit()
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            snapshot_path = config.DB_SNAPSHOTS_DIR / f"pre_config_import_{timestamp}.db"
            if _main_db_path().exists():
                db_admin.make_consistent_db_copy(snapshot_path)
                snapshot_name = snapshot_path.name

            engine.dispose()
            try:
                for filename, tables in BUNDLE_TABLES.items():
                    if filename in present_sections:
                        _merge_section(present_sections[filename], tables)
                        applied.append(filename)

                # Forward-compatible migratsiyalar (db_admin.restore_database
                # bilan bir xil mantiq) -- yuklangan bo'lim eski versiyada
                # yaratilgan bo'lishi mumkin.
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
                if snapshot_name:
                    engine.dispose()
                    shutil.copyfile(config.DB_SNAPSHOTS_DIR / snapshot_name, _main_db_path())
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Import qilishda xatolik yuz berdi, o'zgarishlar bekor qilindi: {exc}",
                )

        if has_images:
            config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            for img in images_dir.rglob("*"):
                if img.is_file():
                    shutil.copyfile(img, config.UPLOADS_DIR / img.name)
            applied.append(IMAGES_FOLDER_NAME)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

    return {
        "applied": applied,
        "skipped": skipped,
        "snapshot_filename": snapshot_name,
        "restored_at": datetime.utcnow(),
    }
