"""Ma'lumotlar bazasiga ulanish (SQLAlchemy + SQLite).

SQLite tanlangan: alohida server talab qilmaydi, loyiha ochilgan zahoti
ishlaydi. Kattaroq bazaga o'tmoqchi bo'lsangiz, config.py dagi DATABASE_URL
ni PostgreSQL manziliga almashtirish kifoya.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Har bir so'rov uchun alohida sessiya ochadi va so'rov tugagach yopadi."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
