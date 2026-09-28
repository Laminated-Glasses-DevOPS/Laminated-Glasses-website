"""Mavjud SQLite bazalarini joriy kod bilan moslashtiruvchi yengil migratsiyalar.

Avval bu ALTER TABLE'lar main.py, db_admin.py va config_bundle.py'da alohida
nusxada takrorlangan edi. Endi bitta joyda -- uchala joy ham shu funksiyani
chaqiradi, shu tufayli yangi ustun qo'shilganda birortasini unutib qoldirib
bo'lmaydi (masalan eski .db yoki zip tiklanganda).

Barcha amallar IDEMPOTENT: ustun/indeks allaqachon bor bo'lsa, jim o'tkazib
yuboriladi.
"""

from sqlalchemy.engine import Engine

_COLUMN_MIGRATIONS = [
    ("products", "images_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("constructor_sizes", "pane_count", "INTEGER NOT NULL DEFAULT 1"),
    # Google orqali kirish (customers)
    ("customers", "google_sub", "VARCHAR(64)"),
    ("customers", "email", "VARCHAR(255)"),
    ("customers", "email_verified", "INTEGER NOT NULL DEFAULT 0"),
    ("customers", "picture_url", "VARCHAR(500)"),
    ("customers", "given_name", "VARCHAR(120)"),
    ("customers", "family_name", "VARCHAR(120)"),
    ("customers", "locale", "VARCHAR(20)"),
    ("customers", "name_confirmed", "INTEGER NOT NULL DEFAULT 0"),
    ("customers", "login_count", "INTEGER NOT NULL DEFAULT 0"),
    ("customers", "last_login_at", "DATETIME"),
    ("customers", "google_registered_at", "DATETIME"),
    # Statistika: tashrifni Google akkauntga bog'lash
    ("visit_logs", "customer_id", "INTEGER"),
]

_INDEX_MIGRATIONS = [
    # UNIQUE: bitta Google akkaunt = bitta mijoz (NULL'lar bir-biriga to'qnashmaydi).
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_customers_google_sub ON customers (google_sub)",
    "CREATE INDEX IF NOT EXISTS ix_customers_email ON customers (email)",
    "CREATE INDEX IF NOT EXISTS ix_visit_logs_customer_id ON visit_logs (customer_id)",
    # Tez-tez ishlatiladigan so'rovlar uchun kompozit indekslar (admin ro'yxatlar,
    # statistika, savat, tozalash vazifalari).
    "CREATE INDEX IF NOT EXISTS ix_orders_status_created ON orders (status, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_orders_customer_created ON orders (customer_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_cart_customer_expires ON cart_items (customer_id, expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_visit_date_device ON visit_logs (visit_date, device_id)",
    "CREATE INDEX IF NOT EXISTS ix_security_kind_created ON security_events (kind, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_ctor_usage_customer_used ON constructor_usage (customer_id, used_at)",
]

_BACKFILLS = [
    # Google'ga allaqachon bog'langan mijozlar uchun "ro'yxatdan o'tgan payt".
    "UPDATE customers SET google_registered_at = COALESCE(last_login_at, created_at) "
    "WHERE google_sub IS NOT NULL AND google_registered_at IS NULL",
]


def run_migrations(engine: Engine) -> None:
    with engine.begin() as conn:
        for table, column, ddl in _COLUMN_MIGRATIONS:
            try:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            except Exception:
                # Ustun allaqachon bor (yoki jadval hali yo'q) -- normal holat.
                pass
        for statement in _INDEX_MIGRATIONS + _BACKFILLS:
            try:
                conn.exec_driver_sql(statement)
            except Exception:
                pass
