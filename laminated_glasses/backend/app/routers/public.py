"""Ommaviy API -- saytga kirgan har qanday mehmon foydalanadigan qism.

Bu yerda hech qachon tannarx yoki foyda qaytarilmaydi. Telegram username ham
faqat bitta joyda -- buyurtmani rasmiylashtirish (checkout) javobida beriladi.
"""

from datetime import datetime, timedelta
import json
import threading
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config, google_auth, honeypot_state, models, schemas, security, utils
from ..database import get_db

router = APIRouter(tags=["Public"])


def _product_images(p):
    try: items = json.loads(p.images_json or "[]")
    except Exception: items = []
    if not items and p.image_filename: items = [p.image_filename]
    return items

def _settings(db: Session) -> models.SiteSettings:
    settings = db.query(models.SiteSettings).first()
    if settings is None:
        raise HTTPException(status_code=500, detail="Sayt sozlamalari topilmadi.")
    return settings


@router.get("/site", response_model=schemas.SiteInfo)
def site_info(db: Session = Depends(get_db)):
    return schemas.SiteInfo(
        site_title=_settings(db).site_title,
        cart_ttl_days=config.CART_TTL_DAYS,
        google_client_id=config.GOOGLE_CLIENT_ID,
    )


_BOT_MARKERS = (
    "bot", "crawler", "spider", "slurp", "headless", "lighthouse", "curl/", "wget/",
    "python-requests", "httpx", "go-http-client", "monitor", "uptime", "facebookexternalhit",
    "preview", "scrapy",
)


def _looks_like_bot(request: Request) -> bool:
    """Ochiq botlar (qidiruv robotlari, monitoring, skriptlar) statistikani
    shishirmasligi uchun. Yashiringan botni ushlamaydi -- lekin real
    foydalanuvchilar soni (Google akkauntlar) bunga bog'liq emas."""
    ua = (request.headers.get("user-agent") or "").lower()
    return (not ua) or any(marker in ua for marker in _BOT_MARKERS)


@router.post("/visit", status_code=204)
def log_visit(
    payload: schemas.VisitIn,
    request: Request,
    db: Session = Depends(get_db),
    customer: Optional[models.Customer] = Depends(security.get_optional_customer),
):
    """Sayt tashrifini qayd qiladi.

    Bitta qurilma bir kunda bir necha marta kirsa ham, (device_id, kun) jufti
    unique bo'lgani uchun faqat bitta qator saqlanadi. Foydalanuvchi Google
    orqali kirgan bo'lsa, qator uning `customer_id`siga bog'lanadi -- shu
    tufayli statistikada bir odam ikki qurilmadan kirsa ham 1 ta sanaladi.
    """
    if _looks_like_bot(request):
        return None

    device_id = payload.device_id.strip()
    today = datetime.utcnow().date()
    row = (
        db.query(models.VisitLog)
        .filter(models.VisitLog.device_id == device_id, models.VisitLog.visit_date == today)
        .first()
    )
    if row is not None:
        # Mehmon sifatida kirib, keyin shu kuni Google bilan kirgan bo'lsa.
        if customer is not None and row.customer_id != customer.id:
            row.customer_id = customer.id
            db.commit()
        return None

    db.add(
        models.VisitLog(
            device_id=device_id,
            visit_date=today,
            customer_id=customer.id if customer is not None else None,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Parallel so'rov bir vaqtda xuddi shu qatorni yozgan bo'lishi mumkin --
        # natija bir xil: 1 ta odam = 1 ta ko'rish.
        db.rollback()
    return None


@router.get("/products", response_model=List[schemas.ProductPublic])
def list_products(
    category: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Product).filter(models.Product.is_active == 1)
    if category:
        query = query.filter(models.Product.category == category)
    if search:
        query = query.filter(models.Product.name.ilike(f"%{search.strip()}%"))

    products = query.order_by(models.Product.created_at.desc()).all()
    return [
        schemas.ProductPublic(
            id=p.id,
            name=p.name,
            description=p.description or "",
            category=p.category,
            sale_price=p.sale_price,
            image_url=utils.build_image_url(p.image_filename),
            image_urls=[utils.build_image_url(x) for x in _product_images(p)],
        )
        for p in products
    ]


@router.get("/products/{product_id}", response_model=schemas.ProductPublic)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = (
        db.query(models.Product)
        .filter(models.Product.id == product_id, models.Product.is_active == 1)
        .first()
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi.")
    return schemas.ProductPublic(
        id=product.id,
        name=product.name,
        description=product.description or "",
        category=product.category,
        sale_price=product.sale_price,
        image_url=utils.build_image_url(product.image_filename),
        image_urls=[utils.build_image_url(x) for x in _product_images(product)],
    )


@router.get("/categories", response_model=List[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.query(models.Category).order_by(models.Category.name).all()


# ---------- Google orqali kirish ----------
#
# Avval savatga birinchi marta qo'shishda ism so'ralar edi (device_id bo'yicha,
# hech qanday tasdiqsiz). Endi foydalanuvchi Google akkaunti bilan kiradi:
# brauzer Google'dan ID token oladi, biz uni SERVERDA tekshiramiz
# (google_auth.py), keyin o'zimizning mijoz sessiya tokenimizni beramiz.
# Savat va checkout shu token bilan himoyalangan.


def _apply_identity(customer: models.Customer, ident: google_auth.GoogleIdentity) -> None:
    """Google'dan kelgan (yangilanishi mumkin) ma'lumotlarni yozadi.

    ISM: foydalanuvchi ismini o'zi kiritgan/tasdiqlagan bo'lsa
    (`name_confirmed`), Google'dagi ism uni QAYTA YOZMAYDI. Aks holda Google
    ismi vaqtinchalik (oldindan to'ldirilgan) qiymat sifatida turadi va
    foydalanuvchidan ism so'raladi. EMAIL esa doim Google'dan olinadi."""
    now = datetime.utcnow()
    customer.google_sub = ident.sub
    if not customer.name_confirmed:
        customer.name = ident.name
    customer.email = ident.email
    customer.email_verified = 1 if ident.email_verified else 0
    customer.picture_url = ident.picture
    customer.given_name = ident.given_name
    customer.family_name = ident.family_name
    customer.locale = ident.locale
    if customer.google_registered_at is None:
        customer.google_registered_at = now
    customer.login_count = (customer.login_count or 0) + 1
    customer.last_login_at = now
    customer.last_seen_at = now


@router.post("/auth/google", response_model=schemas.AuthOut)
def google_login(payload: schemas.GoogleLoginIn, request: Request, db: Session = Depends(get_db)):
    """Google ID tokenni tekshirib, mijozni topadi yoki yaratadi.

    BIR AKKAUNT = BIR MIJOZ: `google_sub` bo'yicha qidiriladi. Shu akkauntdan
    2-marta (yoki boshqa qurilmadan) kirilsa, yangi yozuv YARATILMAYDI --
    mavjud mijoz qaytariladi, faqat `login_count`/`last_login_at` yangilanadi.
    """
    security.enforce_rate_limit(request, "google_login", max_calls=30, window_seconds=600)
    ident = google_auth.verify_google_id_token(payload.credential)

    customer = (
        db.query(models.Customer)
        .filter(models.Customer.google_sub == ident.sub)
        .first()
    )
    is_new = False

    if customer is None:
        # Eski tizimdagi (faqat ism bilan ro'yxatdan o'tgan) mijozning savati va
        # buyurtmalari yo'qolmasligi uchun: shu qurilma identifikatori bo'yicha
        # hali hech qaysi Google akkauntga bog'lanmagan yozuv bo'lsa, uni shu
        # akkauntga biriktiramiz.
        device_id = (payload.device_id or "").strip()
        if device_id and not device_id.startswith("google:"):
            customer = (
                db.query(models.Customer)
                .filter(
                    models.Customer.device_id == device_id,
                    models.Customer.google_sub.is_(None),
                )
                .first()
            )
            if customer is not None and customer.name:
                # Eski tizimda ismini o'zi yozgan -- qayta so'ralmaydi.
                customer.name_confirmed = 1
        if customer is None:
            customer = models.Customer(device_id=f"google:{ident.sub}", name=ident.name)
            db.add(customer)
            is_new = True

    _apply_identity(customer, ident)
    try:
        db.commit()
    except IntegrityError:
        # Bir vaqtda kelgan ikki so'rov bir akkauntni ikki marta yaratmoqchi
        # bo'ldi -- unique indeks buni to'xtatdi; mavjud yozuvni olamiz.
        db.rollback()
        customer = (
            db.query(models.Customer)
            .filter(models.Customer.google_sub == ident.sub)
            .first()
        )
        if customer is None:
            raise HTTPException(status_code=500, detail="Kirishda xatolik. Qayta urinib ko'ring.")
        is_new = False
        _apply_identity(customer, ident)
        db.commit()
    db.refresh(customer)

    # Statistika: shu qurilmaning avvalgi (mehmon sifatidagi) tashriflari endi
    # shu odamga tegishli -- aks holda u bir marta mehmon, bir marta
    # foydalanuvchi bo'lib ikki marta sanalib qolardi.
    device_id = (payload.device_id or "").strip()
    if device_id:
        db.query(models.VisitLog).filter(
            models.VisitLog.device_id == device_id,
            models.VisitLog.customer_id.is_(None),
        ).update({"customer_id": customer.id}, synchronize_session=False)
        db.commit()

    return schemas.AuthOut(
        access_token=security.create_customer_token(customer),
        expires_in_days=config.CUSTOMER_TOKEN_EXPIRE_DAYS,
        is_new=is_new,
        customer=schemas.CustomerOut.model_validate(customer),
    )


@router.get("/auth/me", response_model=schemas.CustomerOut)
def auth_me(
    db: Session = Depends(get_db),
    customer: models.Customer = Depends(security.get_current_customer),
):
    """Saqlangan sessiya hali amal qiladimi? Qilsa, mijoz ma'lumotini qaytaradi."""
    customer.last_seen_at = datetime.utcnow()
    db.commit()
    return customer


@router.put("/auth/profile", response_model=schemas.CustomerOut)
def update_profile(
    payload: schemas.ProfileUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
    customer: models.Customer = Depends(security.get_current_customer),
):
    """Profildagi ismni saqlaydi (Google akkauntni tanlagandan keyingi birinchi
    so'rov ham shu). FAQAT ism o'zgaradi -- email Google'dan keladi va bu
    yerdan o'zgartirib bo'lmaydi."""
    security.enforce_rate_limit(request, "update_profile", max_calls=20, window_seconds=600)
    try:
        customer.name = utils.clean_person_name(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    customer.name_confirmed = 1
    customer.last_seen_at = datetime.utcnow()
    db.commit()
    db.refresh(customer)
    return customer


def _cart_response(db: Session, customer: models.Customer, removed: int = 0):
    items = (
        db.query(models.CartItem)
        .filter(models.CartItem.customer_id == customer.id)
        .order_by(models.CartItem.created_at.asc())
        .all()
    )

    out: List[schemas.CartItemOut] = []
    total_amount = 0.0
    total_quantity = 0

    for item in items:
        product = item.product
        if product is None or not product.is_active:
            db.delete(item)
            removed += 1
            continue

        line_total = round(product.sale_price * item.quantity, 2)
        total_amount += line_total
        total_quantity += item.quantity

        out.append(
            schemas.CartItemOut(
                id=item.id,
                product_id=product.id,
                name=product.name,
                category=product.category,
                unit_price=product.sale_price,
                quantity=item.quantity,
                line_total=line_total,
                image_url=utils.build_image_url(product.image_filename),
                expires_at=item.expires_at,
                days_left=utils.days_left(item.expires_at),
            )
        )

    db.commit()

    return schemas.CartOut(
        items=out,
        total_quantity=total_quantity,
        total_amount=round(total_amount, 2),
        cart_ttl_days=config.CART_TTL_DAYS,
        removed_expired=removed,
    )


@router.get("/cart", response_model=schemas.CartOut)
def get_cart(
    db: Session = Depends(get_db),
    customer: models.Customer = Depends(security.get_current_customer),
):
    removed = utils.purge_expired_cart_items(db, customer.id)
    return _cart_response(db, customer, removed)


@router.post("/cart", response_model=schemas.CartOut, status_code=201)
def add_to_cart(
    payload: schemas.CartItemIn,
    request: Request,
    db: Session = Depends(get_db),
    customer: models.Customer = Depends(security.get_current_customer),
):
    security.enforce_rate_limit(request, "add_to_cart", max_calls=60, window_seconds=300)
    utils.purge_expired_cart_items(db, customer.id)

    product = (
        db.query(models.Product)
        .filter(models.Product.id == payload.product_id, models.Product.is_active == 1)
        .first()
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi.")

    expires_at = datetime.utcnow() + timedelta(days=config.CART_TTL_DAYS)

    existing = (
        db.query(models.CartItem)
        .filter(
            models.CartItem.customer_id == customer.id,
            models.CartItem.product_id == product.id,
        )
        .first()
    )
    if existing:
        existing.quantity = min(
            config.MAX_CART_ITEM_QUANTITY, existing.quantity + payload.quantity
        )
        # Har qo'shilganda muddat yangidan 7 kunga uzayadi
        existing.expires_at = expires_at
    else:
        db.add(
            models.CartItem(
                customer_id=customer.id,
                product_id=product.id,
                quantity=payload.quantity,
                expires_at=expires_at,
            )
        )

    db.commit()
    return _cart_response(db, customer)


@router.put("/cart/item/{item_id}", response_model=schemas.CartOut)
def update_cart_item(
    item_id: int,
    payload: schemas.CartQuantityIn,
    db: Session = Depends(get_db),
    customer: models.Customer = Depends(security.get_current_customer),
):
    item = (
        db.query(models.CartItem)
        .filter(models.CartItem.id == item_id, models.CartItem.customer_id == customer.id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Savatda bunday qator yo'q.")

    item.quantity = payload.quantity
    db.commit()
    return _cart_response(db, customer)


@router.delete("/cart/item/{item_id}", response_model=schemas.CartOut)
def delete_cart_item(
    item_id: int,
    db: Session = Depends(get_db),
    customer: models.Customer = Depends(security.get_current_customer),
):
    item = (
        db.query(models.CartItem)
        .filter(models.CartItem.id == item_id, models.CartItem.customer_id == customer.id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Savatda bunday qator yo'q.")

    db.delete(item)
    db.commit()
    return _cart_response(db, customer)


@router.delete("/cart", response_model=schemas.CartOut)
def clear_cart(
    db: Session = Depends(get_db),
    customer: models.Customer = Depends(security.get_current_customer),
):
    db.query(models.CartItem).filter(models.CartItem.customer_id == customer.id).delete()
    db.commit()
    return _cart_response(db, customer)


@router.post("/checkout", response_model=schemas.CheckoutOut, status_code=201)
def checkout(
    request: Request,
    db: Session = Depends(get_db),
    customer: models.Customer = Depends(security.get_current_customer),
):
    """Savatni buyurtmaga aylantiradi va Telegram havolasini qaytaradi.

    Telegram username butun loyihada faqat shu javobda uchraydi.
    """
    # Skript orqali cheksiz buyurtma yaratib, admin panelini spam bilan
    # to'ldirishning oldini olish uchun cheklov.
    security.enforce_rate_limit(request, "checkout", max_calls=8, window_seconds=600)
    utils.purge_expired_cart_items(db, customer.id)

    cart_items = (
        db.query(models.CartItem)
        .filter(models.CartItem.customer_id == customer.id)
        .order_by(models.CartItem.created_at.asc())
        .all()
    )
    if not cart_items:
        raise HTTPException(status_code=400, detail="Savat bo'sh.")

    order = models.Order(
        code=utils.generate_order_code(db),
        customer_id=customer.id,
        customer_name=customer.name,
        status="new",
        admin_note="",
    )
    db.add(order)
    db.flush()

    total_amount = 0.0
    total_cost = 0.0
    for item in cart_items:
        product = item.product
        if product is None:
            continue
        order_item = models.OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=item.quantity,
            unit_price=product.sale_price,
            unit_cost=product.cost_price,
        )
        db.add(order_item)
        total_amount += product.sale_price * item.quantity
        total_cost += product.cost_price * item.quantity

    order.total_amount = round(total_amount, 2)
    order.total_cost = round(total_cost, 2)

    for item in cart_items:
        db.delete(item)

    db.commit()
    db.refresh(order)

    settings = _settings(db)
    message_text = utils.build_order_message(
        order.code, order.customer_name, order.items, order.total_amount
    )

    return schemas.CheckoutOut(
        order_code=order.code,
        customer_name=order.customer_name,
        total_amount=order.total_amount,
        telegram_username=settings.telegram_username,
        telegram_url=utils.telegram_url(settings.telegram_username, message_text),
        message_text=message_text,
    )

@router.get("/news")
def public_news(db: Session = Depends(get_db)):
    return db.query(models.NewsPost).filter_by(is_published=1).order_by(models.NewsPost.created_at.desc()).all()

@router.get("/site-links")
def public_site_links(db: Session = Depends(get_db)):
    return {x.key:x.value for x in db.query(models.SiteLink).all() if x.value}


@router.get("/constructor/sizes", response_model=List[schemas.ConstructorSizeOut])
def public_constructor_sizes(db: Session = Depends(get_db)):
    """Konstruktor sahifasida mijozga ko'rsatiladigan, admin yoqqan
    o'lchamlar ro'yxati (o'chirilganlari bu yerda chiqmaydi)."""
    return (
        db.query(models.ConstructorSize)
        .filter(models.ConstructorSize.is_active == 1)
        .order_by(models.ConstructorSize.sort_order.asc(), models.ConstructorSize.created_at.asc())
        .all()
    )


# ---------- Konstruktor limiti (Google akkaunt bo'yicha, 24 soatda 1 marta) ----------
#
# "Foydalanish" = konstruktorda rasm yuklab dizayn boshlash (frontend buni
# /constructor/start orqali serverga bildiradi). Boshlangan paytdan
# CONSTRUCTOR_LIMIT_HOURS soat ichida shu akkaunt yangi foydalanishni
# boshlay olmaydi. Limit har bir Gmail uchun ALOHIDA. Server tomonda qattiq
# tekshiriladigan qism -- "Telegramga yuborish" (/constructor/share): u faqat
# faol foydalanish oynasi bor akkauntga ishlaydi.

_constructor_lock = threading.Lock()


def _limit_window() -> timedelta:
    return timedelta(hours=config.CONSTRUCTOR_LIMIT_HOURS)


def _active_constructor_usage(db: Session, customer_id: int) -> Optional[models.ConstructorUsage]:
    cutoff = datetime.utcnow() - _limit_window()
    return (
        db.query(models.ConstructorUsage)
        .filter(
            models.ConstructorUsage.customer_id == customer_id,
            models.ConstructorUsage.used_at > cutoff,
        )
        .order_by(models.ConstructorUsage.used_at.desc())
        .first()
    )


def _limit_out(usage: Optional[models.ConstructorUsage]) -> schemas.ConstructorLimitOut:
    if usage is None:
        return schemas.ConstructorLimitOut(allowed=True, limit_hours=config.CONSTRUCTOR_LIMIT_HOURS)
    remaining = (usage.used_at + _limit_window() - datetime.utcnow()).total_seconds()
    return schemas.ConstructorLimitOut(
        allowed=False,
        limit_hours=config.CONSTRUCTOR_LIMIT_HOURS,
        retry_after_seconds=max(1, int(remaining)),
    )


@router.get("/constructor/limit", response_model=schemas.ConstructorLimitOut)
def constructor_limit(
    db: Session = Depends(get_db),
    customer: models.Customer = Depends(security.get_current_customer),
):
    """Akkaunt konstruktordan hozir foydalana oladimi (yoki qancha kutish kerak)."""
    return _limit_out(_active_constructor_usage(db, customer.id))


@router.post("/constructor/start", response_model=schemas.ConstructorLimitOut)
def constructor_start(
    request: Request,
    db: Session = Depends(get_db),
    customer: models.Customer = Depends(security.get_current_customer),
):
    """Konstruktordan foydalanishni boshlaydi va limitni sarflaydi.

    `allowed=True` -- foydalanish yozildi (keyingisi limit_hours dan so'ng).
    `allowed=False` -- limit sarflangan, `retry_after_seconds` ichida kutish kerak."""
    security.enforce_rate_limit(request, "constructor_start", max_calls=30, window_seconds=600)
    with _constructor_lock:
        active = _active_constructor_usage(db, customer.id)
        if active is not None:
            return _limit_out(active)
        db.add(models.ConstructorUsage(customer_id=customer.id, used_at=datetime.utcnow()))
        db.commit()
    return schemas.ConstructorLimitOut(allowed=True, limit_hours=config.CONSTRUCTOR_LIMIT_HOURS)


@router.post("/constructor/share", response_model=schemas.ConstructorShareOut)
async def share_constructor_preview(
    request: Request,
    original: UploadFile = File(...),
    final: UploadFile = File(...),
    size_label: Optional[str] = Form(None),
    pane_count: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    customer: models.Customer = Depends(security.get_current_customer),
):
    """Konstruktordagi \"Share\" tugmasi: mijoz yuklagan asl rasm va
    oynalarga bo'lingan holda ko'rinadigan tayyor dizayn diskka saqlanadi,
    so'ng admin sozlamalarda oldindan belgilangan Telegram akkauntiga
    (`SiteSettings.telegram_username`) shu ikki rasm havolasi bilan tayyor
    xabar tuziladi. Haqiqiy jo'natishni (checkout oqimidagi kabi) mijozning
    o'zi Telegram ilovasida \"Yuborish\"ni bosib amalga oshiradi -- bu
    yerda bot orqali avtomatik xabar yuborilmaydi."""
    security.enforce_rate_limit(request, "constructor_share", max_calls=15, window_seconds=600)
    # Faqat konstruktordan foydalanishni (limitni) boshlagan akkaunt yubora oladi.
    if _active_constructor_usage(db, customer.id) is None:
        raise HTTPException(
            status_code=403,
            detail="Avval konstruktorda rasm yuklab, dizaynni boshlang.",
        )
    # Bu rasmlar mahsulot rasmlaridan ALOHIDA papkaga saqlanadi (constructor
    # preview) -- shu tufayli har 24 soatlik avtomatik tozalash faqat shu
    # vaqtinchalik fayllarni o'chiradi, mahsulotlarning joriy rasmlariga
    # hech qachon tegmaydi.
    original_filename = utils.save_constructor_preview_image(original)
    final_filename = utils.save_constructor_preview_image(final)

    settings = _settings(db)
    base = config.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    original_url = f"{base}{utils.build_constructor_preview_url(original_filename)}"
    final_url = f"{base}{utils.build_constructor_preview_url(final_filename)}"

    lines = ["Assalomu alaykum! Konstruktorda tayyorlagan dizaynimni yubormoqchiman."]
    if size_label:
        size_line = f"O'lcham: {size_label}"
        if pane_count:
            size_line += f" ({pane_count} oyna)"
        lines.append(size_line)
    lines += [
        "",
        f"Asl rasm: {original_url}",
        f"Tayyor dizayn (oynalarga bo'lingan): {final_url}",
    ]
    message_text = "\n".join(lines)

    return schemas.ConstructorShareOut(
        telegram_username=settings.telegram_username,
        telegram_url=utils.telegram_url(settings.telegram_username, message_text),
        original_image_url=original_url,
        final_image_url=final_url,
        message_text=message_text,
    )


# ---------- Honeypot: real-vaqt heartbeat + avtomatik yangilanish ----------
#
# Bu ikki endpoint faqat ochiq turgan honeypot 400-sahifasining o'z JS kodi
# tomonidan chaqiriladi (haqiqiy mijozlar hech qachon bunga tegmaydi).
# Ular orqali: (1) admin panelda IP haqiqiy real-vaqt Onlayn/Oflayn holati
# ko'rsatiladi, (2) admin yozgan/bekor qilgan shaxsiy xabar honeypot
# sahifasida sahifani qayta yuklamasdan avtomatik ko'rinadi.

@router.post("/security/pulse")
def honeypot_pulse(request: Request, db: Session = Depends(get_db)):
    """Honeypot sahifasi ochiq turgan vaqtda muntazam yuboriladigan
    "men hali ham ochiqman" signali. Javobida joriy faol shaxsiy xabar
    (bo'lsa) qaytariladi -- sahifa buni o'zi bilan solishtirib, farq
    bo'lsa avtomatik yangilanadi."""
    ip_address = security._get_client_ip(request)
    honeypot_state.record_heartbeat(db, ip_address, is_open=True)
    custom = honeypot_state.active_honeypot_message(db, ip_address)
    if custom is None:
        return {"message": None, "reply_url": None}
    reply_url = utils.telegram_url(custom.telegram_username) if custom.telegram_username else None
    return {"message": custom.message, "reply_url": reply_url}


@router.post("/security/offline")
def honeypot_offline(request: Request, db: Session = Depends(get_db)):
    """Honeypot sahifasi yopilayotganda (tab yopish, orqaga qaytish va h.k.)
    `navigator.sendBeacon` orqali yuboriladigan signal -- IP darhol
    "Oflayn" deb belgilanadi, heartbeat oynasi tugashini kutish shart
    emas."""
    ip_address = security._get_client_ip(request)
    honeypot_state.record_heartbeat(db, ip_address, is_open=False)
    return {"ok": True}
