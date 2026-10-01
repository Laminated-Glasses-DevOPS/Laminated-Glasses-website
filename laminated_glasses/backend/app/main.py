"""Laminated Glasses backend (FastAPI).

Ishga tushirish:
    python run.py
yoki:
    uvicorn app.main:app --host 0.0.0.0 --port 8000

Server ham API ni, ham frontendni bitta portdan beradi -- shu sababli
nginx (VPS), cloudflared tunnel yoki Render orqali chiqarish uchun bitta
manzil kifoya. VPS o'rnatish: deploy/README_VPS.md
"""

import logging
import os
from datetime import datetime
from urllib.parse import unquote_plus

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import cleanup, config, honeypot_state, migrations, models, security, shield, utils
from .database import Base, SessionLocal, engine
from .routers import admin, public

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Ixtiyoriy xato kuzatuvi (Sentry). SENTRY_DSN bo'sh bo'lsa umuman ishlamaydi;
# kutubxona o'rnatilmagan bo'lsa ham server yiqilmaydi.
if config.SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=config.SENTRY_DSN, traces_sample_rate=0.0, send_default_pii=False)
        logging.getLogger("app").info("Sentry yoqildi.")
    except ImportError:
        logging.getLogger("app").warning(
            "SENTRY_DSN berilgan, lekin sentry-sdk o'rnatilmagan: pip install sentry-sdk"
        )

Base.metadata.create_all(bind=engine)
# Mavjud SQLite bazalar uchun yangi ustun/indekslarni qo'shadi (mahsulot
# galereyasi, oyna soni, Google orqali kirish maydonlari) -- ma'lumot
# yo'qolmaydi. Batafsil: migrations.py
migrations.run_migrations(engine)

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


# Matn/JSON/JS/CSS javoblarini siqadi (mobil internetda sezilarli tezroq).
app.add_middleware(GZipMiddleware, minimum_size=800)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    h = response.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Clickjacking: sayt boshqa saytning iframe'iga joylanmasin.
    h["X-Frame-Options"] = "SAMEORIGIN"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"  # Google kirish oynasi uchun
    # HTTPS orqali kirilganda brauzer keyingi safar ham faqat HTTPS ishlatsin.
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if proto == "https":
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Admin panel va API javoblari keshlanmasin.
    path = request.url.path
    if path.startswith("/api/admin") or path == "/admin":
        h["Cache-Control"] = "no-store"
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


def _is_verified_admin_request(request: Request) -> bool:
    """So'rovda haqiqiy, amal qiluvchi admin JWT tokeni bormi?

    Honeypot filtri asli anonim/mehmon trafigidagi hujum urinishlarini
    ushlash uchun mo'ljallangan. Lekin u oldin BARCHA so'rovlarni, shu
    jumladan JWT bilan allaqachon tasdiqlangan admin so'rovlarini ham
    skanerlar edi -- natijada admin yangilik/izoh matnida tasodifan
    "--" bilan tugagan gap yoki "... yoki narx=narx" kabi so'z birikmasi
    bo'lsa, honeypot buni hujum deb hisoblab, ADMINNING O'ZINI bloklab
    qo'yishi mumkin edi. Login endpointi bunga kirmaydi -- u hali
    tokensiz so'ralayotgani uchun baribir skanerlanadi."""
    if request.url.path.startswith("/api/admin/login"):
        return False
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return False
    payload = security.decode_access_token(auth[7:].strip())
    return bool(payload and payload.get("sub") == "admin")


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

    # Tasdiqlangan admin so'rovlari ham chetlab o'tiladi (yuqoridagi
    # izohga qarang) -- honeypotning maqsadi anonim hujumchilarni ushlash,
    # o'z paneliga kirgan adminni emas.
    if _is_verified_admin_request(request):
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


@app.api_route("/api/health", methods=["GET", "HEAD"], include_in_schema=False)
def health_check(request: Request):
    """Bazaga haqiqatan ulanib ko'radi.

    GET ham, HEAD ham qabul qilinadi: UptimeRobot (bepul reja) sukut bo'yicha
    HEAD yuboradi, Render'ning healthCheck'i esa GET. Ikkalasi ham baza
    ishlayotgan bo'lsa 200 oladi, baza ishdan chiqsa 503. Javob keshlanmaydi,
    shunda har bir ping haqiqatan serverga yetib boradi (Render uxlab
    qolmasligi uchun)."""
    headers = {"Cache-Control": "no-store"}
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        if request.method == "HEAD":
            return Response(status_code=503, headers=headers)
        return JSONResponse(status_code=503, content={"status": "db_error"}, headers=headers)
    finally:
        db.close()
    if request.method == "HEAD":
        return Response(status_code=200, headers=headers)
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "service": "laminated-glasses-api"},
        headers=headers,
    )


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
            # Parol .env orqali aniq berilmagan bo'lsa, u tasodifiy
            # yaratiladi (config.py) -- shu bois admin uni yo'qotib
            # qo'ymasligi uchun bu yerda, faqat BIRINCHI marta, konsolga
            # aniq chiqarib qo'yamiz.
            if not os.getenv("DEFAULT_ADMIN_PASSWORD", "").strip():
                print("=" * 64)
                print("  ADMIN PANEL UCHUN BOSHLANG'ICH PAROL YARATILDI:")
                print(f"  {config.DEFAULT_ADMIN_PASSWORD}")
                print("  Iltimos, birinchi kirishdan so'ng buni albatta")
                print("  Sozlamalar bo'limidan o'zgartiring va xavfsiz joyga yozib qo'ying.")
                print("=" * 64)
        utils.purge_expired_cart_items(db)
    finally:
        db.close()


@app.on_event("startup")
def warn_if_cors_open() -> None:
    if "*" in config.ALLOWED_ORIGINS:
        print("-" * 64)
        print("  ESLATMA: ALLOWED_ORIGINS=* (hamma saytga ochiq). Frontend shu")
        print("  serverdan beriladi, shuning uchun buni bo'sh qoldiring yoki")
        print("  o'z domeningizni yozing: ALLOWED_ORIGINS=https://domen.uz")
        print("-" * 64)


@app.on_event("startup")
def warn_if_multiple_workers() -> None:
    """Rate-limit va login-lockout xotirada saqlanadi -- bir nechta worker
    ishga tushsa, har biri alohida hisob yuritadi va cheklovlar chetlab
    o'tilishi mumkin. Shu sabab faqat BITTA worker ishlatiladi."""
    try:
        workers = int(os.getenv("WEB_CONCURRENCY", "1") or "1")
    except ValueError:
        workers = 1
    if workers > 1:
        print("!" * 64)
        print(f"  OGOHLANTIRISH: WEB_CONCURRENCY={workers}. Bu loyiha BITTA worker uchun")
        print("  mo'ljallangan (rate-limit/lockout xotirada). --workers 1 ishlating.")
        print("!" * 64)


@app.on_event("startup")
def warn_if_google_not_configured() -> None:
    if not config.GOOGLE_CLIENT_ID:
        print("!" * 64)
        print("  OGOHLANTIRISH: GOOGLE_CLIENT_ID sozlanmagan -- mijozlar Google")
        print("  orqali kira olmaydi (savatga qo'shish ishlamaydi). .env yoki")
        print("  muhit o'zgaruvchilariga GOOGLE_CLIENT_ID ni yozing.")
        print("!" * 64)


@app.on_event("startup")
async def start_periodic_cleanup() -> None:
    """Fon tozalash: FAQAT konstruktorda foydalanuvchilar yuklagan rasmlar
    (va muddati o'tgan limit yozuvlari) 24 soatdan keyin o'chiriladi.
    Buyurtmalar, yangiliklar, xavfsizlik jurnali, mahsulotlar va mijozlar
    avtomatik O'CHIRILMAYDI -- faqat admin panel orqali qo'lda
    o'chiriladi (batafsili: app/cleanup.py)."""
    app.state.cleanup_tasks = cleanup.start_background_cleanup_tasks()


@app.on_event("shutdown")
async def stop_periodic_cleanup() -> None:
    for task in getattr(app.state, "cleanup_tasks", []):
        task.cancel()


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
