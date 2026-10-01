"""ESKI Excel (.xlsx) zaxira fayllari bilan ishlash (faqat o'qish/yuklab olish).

DIQQAT: endi tizim Excel zaxira YARATMAYDI -- buyurtmalar, yangiliklar va
xavfsizlik jurnali avtomatik o'chirilmaydi, shuning uchun ularni zaxiralash
ham shart emas (cleanup.py ga qarang). Bu modul faqat oldingi versiyalarda
diskda qolib ketgan eski .xlsx fayllarni admin panel orqali yuklab olib,
so'ng o'chirib yuborish imkonini saqlab qoladi. Buyurtma/yangilik
ma'lumotlarini zaxiralash uchun admin panelning "Baza holati" bo'limidagi
.db faylni yuklab olish ishlatiladi.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from . import config

SECTION_LABELS = {
    "havfsizlik_jurnali": "Xavfsizlik jurnali (eski)",
    "yangiliklar": "Yangiliklar (eski)",
    "buyurtmalar": "Buyurtmalar (eski)",
}


def list_backups() -> List[dict]:
    """Barcha bo'limlardagi mavjud (hali yuklab olinmagan) zaxira
    fayllarini, eng yangisidan boshlab qaytaradi."""
    out: List[dict] = []
    if not config.BACKUPS_DIR.exists():
        return out
    for section_dir in config.BACKUPS_DIR.iterdir():
        if not section_dir.is_dir():
            continue
        section = section_dir.name
        for f in section_dir.glob("*.xlsx"):
            stat = f.stat()
            out.append(
                {
                    "filename": f.name,
                    "section": section,
                    "section_label": SECTION_LABELS.get(section, section),
                    "created_at": datetime.utcfromtimestamp(stat.st_mtime),
                    "size_kb": round(stat.st_size / 1024, 1),
                }
            )
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return out


def resolve_backup_path(filename: str) -> Optional[Path]:
    """Berilgan fayl nomini, faqat BACKUPS_DIR ichidan xavfsiz qidiradi
    (yo'l-traversal urinishlaridan himoyalangan: faqat oddiy fayl nomi
    qabul qilinadi, papka belgilari yo'q)."""
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.endswith(".xlsx"):
        return None
    for section_dir in config.BACKUPS_DIR.iterdir():
        if not section_dir.is_dir():
            continue
        candidate = section_dir / safe_name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def delete_backup_file(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
