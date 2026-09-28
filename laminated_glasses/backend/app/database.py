"""Ma'lumotlar bazasiga ulanish (SQLAlchemy + SQLite).

SQLite tanlangan: alohida server talab qilmaydi, loyiha ochilgan zahoti
ishlaydi. Kattaroq bazaga o'tmoqchi bo'lsangiz, config.py dagi DATABASE_URL
ni PostgreSQL manziliga almashtirish kifoya.

Har bir yangi ulanishda xavfsiz/tezkor PRAGMA'lar o'rnatiladi:
  - busy_timeout: bir vaqtda yozish to'qnashganda "database is locked"
    xatosi o'rniga 10 soniyagacha kutadi.
  - synchronous=FULL: elektr o'chsa ham yozuvlar yo'qolmaydi (standart
    "delete" jurnal rejimida eng xavfsiz). WAL ATAYIN yoqilmagan --
    "Bazani tiklash" fayl nusxalash orqali ishlaydi va -wal/-shm fayllari
    uni buzib qo'yishi mumkin.
  - temp_store=MEMORY, cache_size: kattaroq so'rovlarni tezlashtiradi.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 15},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA cache_size=-16000")  # ~16 MB
    finally:
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Har bir so'rov uchun alohida sessiya ochadi va so'rov tugagach yopadi."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
