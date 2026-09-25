"""Laminated Glasses backend (FastAPI).

Ishga tushirish:
    python run.py
yoki:
    uvicorn app.main:app --host 0.0.0.0 --port 8000

Server ham API ni, ham frontendni bitta portdan beradi -- shu sababli
cloudflared tunnel bilan global chiqarish uchun bitta manzil kifoya.
"""

from datetime import datetime
from urllib.parse import unquote_plus

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, honeypot_state, models, security, shield, utils
from .database import Base, SessionLocal, engine
from .routers import admin, public

Base.metadata.create_all(bind=engine)
# Existing SQLite installations: add the gallery column without losing products.
try:
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE products ADD COLUMN images_json TEXT NOT NULL DEFAULT '[]'")
except Exception:
    pass
# Existing SQLite installations: add the pane-count column (necha oynaga
# bo'linishi) without losing sizes admin already created.
try:
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE constructor_sizes ADD COLUMN pane_count INTEGER NOT NULL DEFAULT 1")
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


def _log_security_event(kind: str, xss_type, request: Request, sample: str) -> None:
    """Honeypot tutgan urinishni jurnalga yozadi. Xato bo'lsa ham saytga
    ta'sir qilmasligi uchun sukut bilan o'tkazib yuboriladi."""
    db = SessionLocal()
    try:
        db.add(
            models.SecurityEvent(
                kind=kind,
                xss_type=xss_type,
                ip_address=security._get_client_ip(request),
                path=str(request.url.path)[:500],
                method=request.method,
                matched_sample=sample.strip()[:300],
                user_agent=(request.headers.get("user-agent") or "")[:300],
            )
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _wants_html_page(request: Request) -> bool:
    """Brauzer havolani to'g'ridan-to'g'ri (manzil qatoridan) ochganda
    Accept sarlavhasi "text/html" bilan boshlanadi. Saytning o'z JS kodi
    (fetch) esa buni yubormaydi -- shu farq orqali kimga chiroyli sahifa,
    kimga JSON kerakligini aniqlaymiz, aks holda qidiruv forma buzilardi."""
    return request.headers.get("accept", "").startswith("text/html")


def _honeypot_response(kind: str, message: str, request: Request):
    """HTML so'ralganda (brauzer manzil qatoridan ochilganda) admin ushbu
    IP uchun shaxsiy xabar yozgan bo'lsa, standart kinoyali matn o'rniga
    O'SHA xabar va "Javob" tugmasi (agar telegram username bo'lsa)
    ko'rsatiladi. JSON so'rovlar (saytning o'z fetch chaqiruvlari) bunga
    tegilmaydi -- ular har doim standart kinoyali javobni oladi.

    Sahifa render qilingan zahoti shu IP uchun heartbeat ham yoziladi --
    shunday qilib admin panelda "Onlayn" holati sahifa ochilgan ONI
    ko'rinadi, birinchi JS pulse kelishini kutish shart emas."""
    if _wants_html_page(request):
        ip_address = security._get_client_ip(request)
        db = SessionLocal()
        try:
            custom = honeypot_state.active_honeypot_message(db, ip_address)
            page_message = message
            reply_url = None
            if custom is not None:
                page_message = custom.message
                if custom.telegram_username:
                    reply_url = utils.telegram_url(custom.telegram_username)
                honeypot_state.mark_honeypot_message_shown(db, custom.id)
            honeypot_state.record_heartbeat(db, ip_address, is_open=True)
        finally:
            db.close()
        return HTMLResponse(
            content=shield.render_honeypot_page(
                page_message, reply_url=reply_url, default_message=message
            ),
            status_code=400,
        )
    return JSONResponse(status_code=400, content={"detail": message})


@app.middleware("http")
async def honeypot_shield(request: Request, call_next):
    """SQL Injection va XSS urinishlarini ushlaydigan honeypot qatlami.

    Haqiqiy zaiflik yopiq (ORM parametrlangan so'rovlar, chiqishlar escape
    qilingan) -- bu shunchaki qo'shimcha himoya: shubhali urinishni bazaga
    yetib bormasdan turib to'xtatadi va hujumchiga real xato o'rniga
    kinoyali javob qaytaradi."""
    # Fayl yuklash endpointlari (masalan konstruktordagi "Telegramga
    # yuborish" -- /api/constructor/share) va statik fayllar honeypot
    # skanerlashidan butunlay chetlab o'tiladi: bu yerda binary/rasm
    # content yuboriladi, oddiy matn emas -- shuning uchun tasodifan
    # honeypot naqshlariga mos kelib, haqiqiy so'rov SQL Injection/XSS
    # deb noto'g'ri bloklanishi mumkin edi.
    if shield.should_skip_scan(request.url.path):
        return await call_next(request)

    # MUHIM: request.url.query URL-encode qilingan holicha qaytadi (masalan
    # bo'sh joy -> %20, tirnoq -> %27), shuning uchun uni skanerlashdan oldin
    # albatta decode qilish kerak -- aks holda manzil qatoriga yozilgan yoki
    # brauzer avtomatik encode qilgan hujum matnlari (masalan ' OR '1'='1)
    # regex naqshlariga mos kelmay, honeypot tomonidan tutilmay qoladi.
    scan_parts = [request.url.path, unquote_plus(request.url.query or "")]

    content_type = request.headers.get("content-type", "")
    if request.method in ("POST", "PUT", "PATCH") and content_type.startswith("application/json"):
        body_bytes = await request.body()

        async def receive():
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        request._receive = receive
        scan_parts.append(body_bytes.decode("utf-8", errors="ignore"))

    combined = " ".join(scan_parts)

    xss_type = shield.detect_xss(combined)
    if xss_type:
        _log_security_event("xss", xss_type, request, combined)
        message = f"XSS ({xss_type}) qo'llash uchun bizni saytdan boshqa sayt topilmadimi?"
        return _honeypot_response("xss", message, request)

    if shield.detect_sql_injection(combined):
        _log_security_event("sql_injection", None, request, combined)
        message = "SQL Injection qo'llash uchun bizni saytdan boshqa sayt topilmadimi?"
        return _honeypot_response("sql_injection", message, request)

    return await call_next(request)


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
    "/aloqa": "contact.html", "/konstruktor": "constructor.html",
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
