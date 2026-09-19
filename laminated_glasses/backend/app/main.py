"""Laminated Glasses backend (FastAPI).

Ishga tushirish:
    python run.py
yoki:
    uvicorn app.main:app --host 0.0.0.0 --port 8000

Server ham API ni, ham frontendni bitta portdan beradi -- shu sababli
cloudflared tunnel bilan global chiqarish uchun bitta manzil kifoya.
"""

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, models, security, utils
from .database import Base, SessionLocal, engine
from .routers import admin, public

Base.metadata.create_all(bind=engine)
# Existing SQLite installations: add the gallery column without losing products.
try:
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE products ADD COLUMN images_json TEXT NOT NULL DEFAULT '[]'")
except Exception:
    pass

app = FastAPI(
    docs_url=None, redoc_url=None, openapi_url=None,
    title="Laminated Glasses API",
    description="Oynaga rasm bosish xizmati uchun backend",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


app.include_router(public.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "laminated-glasses-api"}


@app.on_event("startup")
def seed_default_data() -> None:
    """Birinchi ishga tushishda admin parol va sozlamalarni yaratadi,
    shuningdek muddati o'tgan savatlarni tozalaydi."""
    db = SessionLocal()
    try:
        settings = db.query(models.SiteSettings).first()
        if settings is None:
            db.add(
                models.SiteSettings(
                    id=1,
                    password_hash=security.hash_password(config.DEFAULT_ADMIN_PASSWORD),
                    telegram_username=config.DEFAULT_TELEGRAM_USERNAME,
                    site_title=config.DEFAULT_SITE_TITLE,
                )
            )
            db.commit()
        utils.purge_expired_cart_items(db)
    finally:
        db.close()


app.mount("/uploads", StaticFiles(directory=str(config.UPLOADS_DIR)), name="uploads")


# Clean, extension-free public routes. Keep these before the catch-all static mount.

_PAGE_FILES = {
    "/": "index.html", "/bosh-sahifa": "index.html",
    "/mahsulotlar": "products.html", "/yangiliklar": "news.html",
    "/aloqa": "contact.html",
    "/admin": "admin.html",
}
for _route, _filename in _PAGE_FILES.items():
    app.add_api_route(
        _route,
        lambda filename=_filename: FileResponse(config.FRONTEND_DIR / filename),
        methods=["GET"], include_in_schema=False,
    )

# Frontend eng oxirida ulanadi, aks holda "/" barcha API yo'llarini to'sib qo'yadi.
if config.FRONTEND_DIR.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(config.FRONTEND_DIR), html=True),
        name="frontend",
    )
