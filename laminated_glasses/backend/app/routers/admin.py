"""Admin API -- faqat to'g'ri JWT tokeni bo'lganlar kira oladigan qism."""

from datetime import datetime, timedelta
import json
import uuid
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import backup, config, config_bundle, db_admin, honeypot_state, models, schemas, security, utils
from ..database import SessionLocal, get_db

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/login", response_model=schemas.TokenResponse)
def login(
    payload: schemas.LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    security.check_login_allowed(request, db)

    settings = db.query(models.SiteSettings).first()
    if settings is None or not security.verify_password(
        payload.password, settings.password_hash
    ):
        security.register_failed_login(request, db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Parol noto'g'ri."
        )

    security.register_successful_login(request, db)
    return schemas.TokenResponse(
        access_token=security.create_access_token(),
        expires_in_minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES,
    )


@router.get("/verify")
def verify_token(_admin=Depends(security.get_current_admin)):
    return {"valid": True}


def _find_category_case_insensitive(db: Session, name: str):
    """Kategoriya nomini KATTA/KICHIK harf farqisiz qidiradi.

    Muammo: avval nomlar faqat aniq (case-sensitive) taqqoslanardi, shu
    sabab \"Oyna\" va \"oyna\" ikkita ALOHIDA kategoriya bo'lib qolishi
    mumkin edi -- bu admin uchun chalkashlik va mahsulotlarning noto'g'ri
    "bo'linib ketishiga" olib kelardi."""
    return (
        db.query(models.Category)
        .filter(func.lower(models.Category.name) == name.strip().lower())
        .first()
    )


def _normalize_category(db: Session, name: str) -> str:
    """Kategoriya nomini bazaga mos ravishda normallashtiradi: agar
    (katta/kichik harfdan qat'i nazar) shunday kategoriya allaqachon
    mavjud bo'lsa, ANIQ o'sha yozuvdagi nom qaytariladi (mahsulotlar bir
    xil kategoriya ostida qolishi uchun); aks holda yangi kategoriya
    yaratiladi."""
    name = name.strip()
    existing = _find_category_case_insensitive(db, name)
    if existing:
        return existing.name
    db.add(models.Category(name=name))
    return name


def _product_images(p):
    try: items = json.loads(p.images_json or "[]")
    except Exception: items = []
    if not items and p.image_filename: items = [p.image_filename]
    return items

def _to_admin_schema(p: models.Product) -> schemas.ProductAdmin:
    return schemas.ProductAdmin(
        id=p.id,
        name=p.name,
        description=p.description or "",
        category=p.category,
        cost_price=p.cost_price,
        sale_price=p.sale_price,
        profit=p.profit,
        profit_margin_percent=p.profit_margin_percent,
        image_url=utils.build_image_url(p.image_filename),
        image_urls=[utils.build_image_url(x) for x in _product_images(p)],
        is_active=bool(p.is_active),
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get("/products", response_model=List[schemas.ProductAdmin])
def list_products_admin(
    db: Session = Depends(get_db), _admin=Depends(security.get_current_admin)
):
    products = db.query(models.Product).order_by(models.Product.created_at.desc()).all()
    return [_to_admin_schema(p) for p in products]


@router.post("/products", response_model=schemas.ProductAdmin, status_code=201)
def create_product(
    name: str = Form(...),
    description: str = Form(""),
    category: str = Form(...),
    cost_price: float = Form(..., ge=0),
    sale_price: float = Form(..., ge=0),
    is_active: bool = Form(True),
    image: Optional[UploadFile] = File(None),
    images: List[UploadFile] = File([]),
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    files = [f for f in images if f and f.filename]
    if image and image.filename: files.insert(0, image)
    saved = [utils.save_product_image(f) for f in files]
    image_filename = saved[0] if saved else None

    normalized_category = _normalize_category(db, category)

    product = models.Product(
        name=name.strip(),
        description=description.strip(),
        category=normalized_category,
        cost_price=cost_price,
        sale_price=sale_price,
        is_active=1 if is_active else 0,
        image_filename=image_filename,
        images_json=json.dumps(saved),
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return _to_admin_schema(product)


@router.put("/products/{product_id}", response_model=schemas.ProductAdmin)
def update_product(
    product_id: int,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    cost_price: Optional[float] = Form(None, ge=0),
    sale_price: Optional[float] = Form(None, ge=0),
    is_active: Optional[bool] = Form(None),
    image: Optional[UploadFile] = File(None),
    images: List[UploadFile] = File([]),
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi.")

    if name is not None:
        product.name = name.strip()
    if description is not None:
        product.description = description.strip()
    if category is not None:
        product.category = _normalize_category(db, category)
    if cost_price is not None:
        product.cost_price = cost_price
    if sale_price is not None:
        product.sale_price = sale_price
    if is_active is not None:
        product.is_active = 1 if is_active else 0

    files = [f for f in images if f and f.filename]
    if image and image.filename: files.insert(0, image)
    if files:
        # Yangi rasmlar yuklanmoqda -- avval eski rasmlarning ro'yxatini
        # olib qo'yamiz, so'ng bazani yangilaymiz, va oxirida ESKI rasmlarni
        # diskdan to'liq o'chiramiz. Shu tufayli eskirgan fayllar diskda
        # abadiy "yetim" bo'lib qolmaydi -- ular yangilari bilan to'liq
        # almashtiriladi.
        old_files = _product_images(product)
        new_files = [utils.save_product_image(f) for f in files]
        product.images_json = json.dumps(new_files)
        product.image_filename = new_files[0]
        db.commit()
        db.refresh(product)
        utils.delete_product_images(old_files)
        return _to_admin_schema(product)

    db.commit()
    db.refresh(product)
    return _to_admin_schema(product)


@router.delete("/products/{product_id}", status_code=204)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi.")

    db.query(models.CartItem).filter(models.CartItem.product_id == product.id).delete()
    # Faqat bitta image_filename emas, mahsulotning BUTUN galereyasi
    # (images_json dagi barcha fayllar) diskdan to'liq o'chiriladi.
    all_images = _product_images(product)
    db.delete(product)
    db.commit()
    utils.delete_product_images(all_images)
    return None


@router.get("/categories", response_model=List[schemas.CategoryOut])
def list_categories_admin(
    db: Session = Depends(get_db), _admin=Depends(security.get_current_admin)
):
    return db.query(models.Category).order_by(models.Category.name).all()


@router.post("/categories", response_model=schemas.CategoryOut, status_code=201)
def create_category(
    payload: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    if _find_category_case_insensitive(db, payload.name):
        raise HTTPException(status_code=409, detail="Bu kategoriya allaqachon mavjud.")
    category = models.Category(name=payload.name.strip())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    category = db.query(models.Category).filter(models.Category.id == category_id).first()
    if category is None:
        raise HTTPException(status_code=404, detail="Kategoriya topilmadi.")

    in_use = db.query(models.Product).filter_by(category=category.name).count()
    if in_use:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Bu kategoriyada {in_use} ta mahsulot bor. Avval ularni boshqa "
                "kategoriyaga o'tkazing yoki o'chiring."
            ),
        )
    db.delete(category)
    db.commit()
    return None


def _order_to_schema(order: models.Order) -> schemas.OrderAdminOut:
    return schemas.OrderAdminOut(
        id=order.id,
        code=order.code,
        customer_name=order.customer_name,
        total_amount=order.total_amount,
        total_profit=order.total_profit,
        status=order.status,
        admin_note=order.admin_note or "",
        created_at=order.created_at,
        confirmed_at=order.confirmed_at,
        items=[
            schemas.OrderItemOut(
                product_name=i.product_name,
                quantity=i.quantity,
                unit_price=i.unit_price,
                line_total=i.line_total,
            )
            for i in order.items
        ],
    )


@router.get("/orders", response_model=List[schemas.OrderAdminOut])
def list_orders(
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    query = db.query(models.Order)
    if status_filter in {"new", "sold", "cancelled"}:
        query = query.filter(models.Order.status == status_filter)
    orders = query.order_by(models.Order.created_at.desc()).all()
    return [_order_to_schema(o) for o in orders]


@router.put("/orders/{order_id}", response_model=schemas.OrderAdminOut)
def update_order_status(
    order_id: int,
    payload: schemas.OrderStatusUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    """Sotuvchi tovarni sotgach, buyurtmani shu yerda "Sotildi" deb belgilaydi
    va bitta gap bilan izoh qoldiradi."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")

    order.status = payload.status
    order.admin_note = payload.admin_note.strip()
    order.confirmed_at = datetime.utcnow() if payload.status == "sold" else None

    db.commit()
    db.refresh(order)
    return _order_to_schema(order)


@router.delete("/orders/{order_id}", status_code=204)
def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")
    db.delete(order)
    db.commit()
    return None


@router.put("/settings/password")
def change_password(
    payload: schemas.ChangePasswordRequest,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    settings = db.query(models.SiteSettings).first()
    if not security.verify_password(payload.current_password, settings.password_hash):
        raise HTTPException(status_code=400, detail="Joriy parol noto'g'ri.")

    settings.password_hash = security.hash_password(payload.new_password)
    db.commit()
    return {"message": "Parol muvaffaqiyatli o'zgartirildi."}


@router.get("/settings/telegram", response_model=schemas.TelegramOut)
def get_telegram(
    db: Session = Depends(get_db), _admin=Depends(security.get_current_admin)
):
    settings = db.query(models.SiteSettings).first()
    return schemas.TelegramOut(
        telegram_username=settings.telegram_username,
        telegram_url=utils.telegram_url(settings.telegram_username),
        site_title=settings.site_title,
    )


@router.put("/settings/telegram", response_model=schemas.TelegramOut)
def update_telegram(
    payload: schemas.UpdateTelegramRequest,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    settings = db.query(models.SiteSettings).first()
    settings.telegram_username = payload.telegram_username
    db.commit()
    return schemas.TelegramOut(
        telegram_username=settings.telegram_username,
        telegram_url=utils.telegram_url(settings.telegram_username),
        site_title=settings.site_title,
    )


@router.get("/stats", response_model=schemas.StatsResponse)
def get_stats(
    db: Session = Depends(get_db), _admin=Depends(security.get_current_admin)
):
    products = db.query(models.Product).all()
    active = [p for p in products if p.is_active]

    # MUHIM: "potensial daromad/foyda" faqat SAYTDA KO'RINADIGAN (faol)
    # mahsulotlar bo'yicha hisoblanadi. Avval yashirilgan (is_active=0)
    # mahsulotlar ham shu summaga qo'shilardi -- bu haqiqatda sotib
    # bo'lmaydigan tovarni "potensial daromad"ga kiritib, ko'rsatkichni
    # noto'g'ri (haddan tashqari katta) qilib ko'rsatardi.
    total_revenue = sum(p.sale_price for p in active)
    total_cost = sum(p.cost_price for p in active)

    margins = [p.profit_margin_percent for p in active if p.sale_price]
    avg_margin = round(sum(margins) / len(margins), 2) if margins else 0.0

    orders = db.query(models.Order).all()
    sold = [o for o in orders if o.status == "sold"]
    new_orders = [o for o in orders if o.status == "new"]

    return schemas.StatsResponse(
        total_products=len(products),
        active_products=len(active),
        total_categories=db.query(models.Category).count(),
        total_potential_revenue=round(total_revenue, 2),
        total_potential_cost=round(total_cost, 2),
        total_potential_profit=round(total_revenue - total_cost, 2),
        average_profit_margin_percent=avg_margin,
        total_orders=len(orders),
        new_orders=len(new_orders),
        sold_orders=len(sold),
        sold_revenue=round(sum(o.total_amount for o in sold), 2),
        sold_profit=round(sum(o.total_profit for o in sold), 2),
    )


_WEEKDAY_UZ = ["Du", "Se", "Chor", "Pay", "Ju", "Shan", "Yak"]


@router.get("/analytics", response_model=schemas.AnalyticsResponse)
def get_analytics(
    days: int = 14,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    """Kunlik noyob tashriflar statistikasi.

    Har bir qurilma bir kunda faqat bitta marta hisoblanadi (1 device = 1
    view), chunki VisitLog jadvalida (device_id, visit_date) jufti unique.
    """
    days = max(1, min(days, 90))
    today = datetime.utcnow().date()
    start_date = today - timedelta(days=days - 1)

    rows = (
        db.query(models.VisitLog.visit_date, func.count(models.VisitLog.id))
        .filter(models.VisitLog.visit_date >= start_date)
        .group_by(models.VisitLog.visit_date)
        .all()
    )
    counts_by_date = {row[0]: row[1] for row in rows}

    daily: List[schemas.DailyVisitPoint] = []
    for offset in range(days):
        d = start_date + timedelta(days=offset)
        weekday = _WEEKDAY_UZ[d.weekday()]
        daily.append(
            schemas.DailyVisitPoint(
                date=d.isoformat(),
                label=f"{weekday} {d.day:02d}.{d.month:02d}",
                unique_visitors=counts_by_date.get(d, 0),
            )
        )

    total_unique_devices = db.query(
        func.count(func.distinct(models.VisitLog.device_id))
    ).scalar() or 0
    total_views = db.query(func.count(models.VisitLog.id)).scalar() or 0
    yesterday = today - timedelta(days=1)

    return schemas.AnalyticsResponse(
        today_visitors=counts_by_date.get(today, 0),
        yesterday_visitors=counts_by_date.get(yesterday, 0),
        total_unique_devices=total_unique_devices,
        total_views=total_views,
        daily=daily,
    )

# Yangiliklar va aloqa havolalarini boshqarish (JWT bilan himoyalangan).
from pydantic import BaseModel, Field

class NewsPayload(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    excerpt: str = Field(default="", max_length=1000)
    body: str = Field(default="", max_length=12000)
    image_url: Optional[str] = Field(default=None, max_length=500)
    is_published: bool = True

class LinkPayload(BaseModel):
    value: str = Field(default="", max_length=500)

@router.get("/news")
def admin_news(db: Session = Depends(get_db), _admin=Depends(security.get_current_admin)):
    return db.query(models.NewsPost).order_by(models.NewsPost.created_at.desc()).all()

@router.post("/news", status_code=201)
def create_news(payload: NewsPayload, db: Session = Depends(get_db), _admin=Depends(security.get_current_admin)):
    item = models.NewsPost(**payload.model_dump())
    db.add(item); db.commit(); db.refresh(item); return item

@router.put("/news/{news_id}")
def update_news(news_id: int, payload: NewsPayload, db: Session = Depends(get_db), _admin=Depends(security.get_current_admin)):
    item = db.query(models.NewsPost).filter_by(id=news_id).first()
    if not item: raise HTTPException(status_code=404, detail="Yangilik topilmadi")
    for k,v in payload.model_dump().items(): setattr(item,k,v)
    item.updated_at = datetime.utcnow(); db.commit(); db.refresh(item); return item

@router.delete("/news/{news_id}", status_code=204)
def delete_news(news_id: int, db: Session = Depends(get_db), _admin=Depends(security.get_current_admin)):
    item = db.query(models.NewsPost).filter_by(id=news_id).first()
    if not item: raise HTTPException(status_code=404, detail="Yangilik topilmadi")
    db.delete(item); db.commit()

@router.get("/site-links")
def admin_site_links(db: Session = Depends(get_db), _admin=Depends(security.get_current_admin)):
    return {x.key:x.value for x in db.query(models.SiteLink).all()}

@router.put("/site-links/{key}")
def update_site_link(key: str, payload: LinkPayload, db: Session = Depends(get_db), _admin=Depends(security.get_current_admin)):
    if key not in {"instagram","telegram","youtube","phone","address","email"}:
        raise HTTPException(status_code=400, detail="Noto'g'ri maydon")
    item=db.query(models.SiteLink).filter_by(key=key).first()
    if not item: item=models.SiteLink(key=key,value=payload.value); db.add(item)
    else: item.value=payload.value
    db.commit(); return {"key":key,"value":payload.value}


@router.get("/constructor/sizes", response_model=List[schemas.ConstructorSizeAdminOut])
def list_constructor_sizes(
    db: Session = Depends(get_db), _admin=Depends(security.get_current_admin)
):
    """Konstruktor uchun barcha o'lchamlar (faol va o'chirilganlari ham)."""
    return (
        db.query(models.ConstructorSize)
        .order_by(models.ConstructorSize.sort_order.asc(), models.ConstructorSize.created_at.asc())
        .all()
    )


def _panes_to_columns(panes: list) -> dict:
    """Har bir panelning alohida eni/bo'yi ro'yxatini (`PaneSize` obyektlari
    yoki dict) `ConstructorSize` ustunlariga aylantiradi: pane_count,
    orqaga moslik uchun umumiy width_cm (yig'indi) / height_cm (maksimum),
    va panellarning o'zini saqlaydigan panes_json."""
    normalized = [
        {"width_cm": p.width_cm, "height_cm": p.height_cm}
        if hasattr(p, "width_cm")
        else {"width_cm": p["width_cm"], "height_cm": p["height_cm"]}
        for p in panes
    ]
    return {
        "pane_count": len(normalized),
        "width_cm": sum(p["width_cm"] for p in normalized),
        "height_cm": max(p["height_cm"] for p in normalized),
        "panes_json": json.dumps(normalized),
    }


@router.post("/constructor/sizes", response_model=schemas.ConstructorSizeAdminOut, status_code=201)
def create_constructor_size(
    payload: schemas.ConstructorSizeCreate,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    data = payload.model_dump(exclude={"panes"})
    data.update(_panes_to_columns(payload.panes))
    size = models.ConstructorSize(**data)
    size.is_active = 1 if payload.is_active else 0
    db.add(size)
    db.commit()
    db.refresh(size)
    return size


@router.put("/constructor/sizes/{size_id}", response_model=schemas.ConstructorSizeAdminOut)
def update_constructor_size(
    size_id: int,
    payload: schemas.ConstructorSizeUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    size = db.query(models.ConstructorSize).filter(models.ConstructorSize.id == size_id).first()
    if size is None:
        raise HTTPException(status_code=404, detail="O'lcham topilmadi.")

    data = payload.model_dump(exclude_unset=True, exclude={"panes"})
    if "is_active" in data:
        size.is_active = 1 if data.pop("is_active") else 0
    for key, value in data.items():
        setattr(size, key, value)
    if payload.panes is not None:
        for key, value in _panes_to_columns(payload.panes).items():
            setattr(size, key, value)

    db.commit()
    db.refresh(size)
    return size


@router.delete("/constructor/sizes/{size_id}", status_code=204)
def delete_constructor_size(
    size_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    size = db.query(models.ConstructorSize).filter(models.ConstructorSize.id == size_id).first()
    if size is None:
        raise HTTPException(status_code=404, detail="O'lcham topilmadi.")
    db.delete(size)
    db.commit()
    return None


@router.get("/security-events")
def list_security_events(
    limit: int = 100,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    """Honeypot tutgan SQL Injection / XSS urinishlari -- eng oxirgisi birinchi."""
    limit = max(1, min(limit, 300))
    events = (
        db.query(models.SecurityEvent)
        .order_by(models.SecurityEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    total = db.query(func.count(models.SecurityEvent.id)).scalar() or 0
    sql_count = (
        db.query(func.count(models.SecurityEvent.id))
        .filter(models.SecurityEvent.kind == "sql_injection")
        .scalar()
        or 0
    )
    xss_count = total - sql_count

    # Har bir IP uchun HAQIQIY real-vaqt Onlayn/Oflayn holati -- oxirgi
    # hujum vaqtiga emas, honeypot sahifasidan kelayotgan heartbeatga
    # asoslangan (qarang: app/honeypot_state.py).
    ip_addresses = {e.ip_address for e in events}
    heartbeats: dict = {}
    if ip_addresses:
        rows = (
            db.query(models.HoneypotHeartbeat)
            .filter(models.HoneypotHeartbeat.ip_address.in_(ip_addresses))
            .all()
        )
        for hb in rows:
            heartbeats[hb.ip_address] = {
                "online": honeypot_state.is_ip_online(hb),
                "last_seen_at": hb.last_seen_at.isoformat() + "Z",
            }

    return {
        "total": total,
        "sql_injection_count": sql_count,
        "xss_count": xss_count,
        "heartbeats": heartbeats,
        "events": [
            {
                "id": e.id,
                "kind": e.kind,
                "xss_type": e.xss_type,
                "ip_address": e.ip_address,
                "path": e.path,
                "method": e.method,
                "matched_sample": e.matched_sample,
                "user_agent": e.user_agent,
                "created_at": e.created_at.isoformat() + "Z",
            }
            for e in events
        ],
    }


@router.delete("/security-events")
def clear_security_events(
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    """Xavfsizlik jurnalini (SQLi/XSS urinishlari tarixini) butunlay
    tozalaydi. Faol honeypot xabarlariga (HoneypotMessage) tegilmaydi --
    ular alohida boshqariladi."""
    deleted = db.query(models.SecurityEvent).delete()
    db.commit()
    return {"deleted": deleted}


@router.get("/security/messages", response_model=List[schemas.HoneypotMessageOut])
def list_honeypot_messages(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    """Admin turli IP larga yozgan honeypot xabarlari ro'yxati."""
    query = db.query(models.HoneypotMessage)
    if not include_inactive:
        query = query.filter(models.HoneypotMessage.is_active == 1)
    return query.order_by(models.HoneypotMessage.created_at.desc()).limit(200).all()


@router.post("/security/messages", response_model=schemas.HoneypotMessageOut)
def send_honeypot_message(
    payload: schemas.HoneypotMessageCreate,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    """Tanlangan IP manziliga shaxsiy honeypot xabari yozadi.

    Shu IP uchun avval yuborilgan faol xabarlar avtomatik bekor qilinadi
    (is_active=0) -- bir vaqtning o'zida bitta IP uchun faqat bitta faol
    xabar bo'ladi, shunday qilib hujumchi honeypot sahifasiga qaytadan
    tushganda eng oxirgi yozilgan xabarni ko'radi."""
    db.query(models.HoneypotMessage).filter(
        models.HoneypotMessage.ip_address == payload.ip_address,
        models.HoneypotMessage.is_active == 1,
    ).update({"is_active": 0})

    telegram_username = payload.telegram_username
    if not telegram_username:
        settings = db.query(models.SiteSettings).first()
        if settings and settings.telegram_username:
            telegram_username = settings.telegram_username.lstrip("@")

    msg = models.HoneypotMessage(
        ip_address=payload.ip_address,
        message=payload.message,
        telegram_username=telegram_username,
        is_active=1,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


@router.delete("/security/messages/{message_id}")
def cancel_honeypot_message(
    message_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    """Yozilgan xabarni bekor qiladi -- shu daqiqadan boshlab hujumchi
    yana honeypotga tushsa, standart kinoyali matnni ko'radi."""
    msg = db.get(models.HoneypotMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Xabar topilmadi.")
    msg.is_active = 0
    db.commit()
    return {"ok": True}


# ---------- Zaxira nusxalar (backup) ----------
#
# Buyurtmalar (48 soat), yangiliklar (48 soat) va xavfsizlik jurnali
# (24 soat) davriy ravishda TO'LIQ tozalanadi (cleanup.py). Shu tozalashdan
# OLDIN har bir bo'lim uchun alohida Excel (.xlsx) fayl yaratiladi -- admin
# shu yerdan yuklab olishi mumkin. Fayl BIR MARTA yuklab olingach, serverdan
# avtomatik o'chiriladi.

@router.get("/backups", response_model=List[schemas.BackupFileOut])
def list_backups(_admin=Depends(security.get_current_admin)):
    return backup.list_backups()


@router.get("/backups/{filename}/download")
def download_backup(filename: str, _admin=Depends(security.get_current_admin)):
    path = backup.resolve_backup_path(filename)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="Bu zaxira fayli topilmadi -- eskirgan, allaqachon yuklab olingan yoki hali yaratilmagan bo'lishi mumkin.",
        )
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        # Fayl to'liq mijozga yuborib bo'lingach, serverdan avtomatik
        # o'chiriladi -- shu tufayli har bir backup faqat BIR MAROTABA
        # yuklab olinadi va diskda cheksiz to'planib qolmaydi.
        background=BackgroundTask(backup.delete_backup_file, path),
    )


# ---------- Baza holati (Database status / konfiguratsiyani yuklab
# olish va tiklash) ----------
#
# Render.com kabi platformalarda kod papkasi har bir deploy'da yangidan
# yaratiladi -- shu sabab config.DATA_DIR "Persistent Disk"ga ko'rsatilgan
# bo'lishi kerak (qarang: render.yaml va .env.example). Bu bo'lim admin
# panelda joriy baza/disk holatini ko'rsatadi va bazani (.db fayl)
# yuklab olish/qayta yuklash (tiklash) imkonini beradi.

@router.get("/database/status", response_model=schemas.DatabaseStatusOut)
def database_status(
    db: Session = Depends(get_db), _admin=Depends(security.get_current_admin)
):
    return db_admin.get_database_status(db)


@router.get("/database/download")
def download_database(_admin=Depends(security.get_current_admin)):
    """Joriy bazaning IZCHIL (consistent) nusxasini .db fayl sifatida
    qaytaradi -- SQLite'ning o'z backup API'si orqali, oddiy fayl nusxasi
    emas (qarang: db_admin.make_consistent_db_copy)."""
    tmp_path = config.DATA_DIR / f".download_tmp_{uuid.uuid4().hex}.db"
    db_admin.make_consistent_db_copy(tmp_path)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return FileResponse(
        tmp_path,
        filename=f"laminated_glasses_{timestamp}.db",
        media_type="application/octet-stream",
        # Vaqtinchalik nusxa jo'natilgach o'chiriladi -- diskda qolib
        # ketmaydi. Joriy ISHCHI bazaga hech qanday ta'sir qilmaydi.
        background=BackgroundTask(lambda p=tmp_path: p.unlink(missing_ok=True)),
    )


@router.get("/database/snapshots", response_model=List[schemas.DatabaseSnapshotOut])
def list_database_snapshots(_admin=Depends(security.get_current_admin)):
    """Bazani tiklashdan OLDIN avtomatik yaratilgan xavfsizlik nusxalari
    ro'yxati -- noto'g'ri fayl yuklab yuborilgan taqdirda ham, admin shu
    yerdan oldingi holatni qayta yuklab olishi mumkin."""
    return db_admin.list_snapshots()


@router.get("/database/snapshots/{filename}/download")
def download_database_snapshot(
    filename: str, _admin=Depends(security.get_current_admin)
):
    path = db_admin.resolve_snapshot_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Bu zaxira nusxa topilmadi.")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.post("/database/restore", response_model=schemas.DatabaseStatusOut)
def restore_database(
    request: Request,
    current_password: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    """XAVFLI AMAL: joriy bazani yuklangan .db fayl bilan TO'LIQ almashtiradi.

    Qo'shimcha himoya qatlamlari (faqat amal qiluvchi Bearer token bilan
    cheklanmaydi):
      1) Admin joriy PAROLINI qayta kiritishi shart -- shu tufayli
         o'g'irlangan yoki eskirib qolgan (masalan ochiq qolgan brauzer
         sessiyasidagi) token bilan bu halokatli amalni bajarib bo'lmaydi
         (parolni o'zgartirish endpointi bilan bir xil mantiq).
      2) Bu endpoint alohida, qattiq tezlik chegarasiga ega.
      3) Yuklangan fayl haqiqiy SQLite ekani va kerakli jadvallarga ega
         ekani tekshiriladi (db_admin.restore_database ichida).
      4) Almashtirishdan OLDIN joriy baza avtomatik zaxiralanadi.
    """
    security.enforce_rate_limit(
        request, "database_restore", max_calls=5, window_seconds=3600
    )

    settings = db.query(models.SiteSettings).first()
    if settings is None or not security.verify_password(
        current_password, settings.password_hash
    ):
        raise HTTPException(status_code=400, detail="Joriy parol noto'g'ri.")

    if not (file.filename or "").lower().endswith(".db"):
        raise HTTPException(
            status_code=400, detail="Faqat .db kengaytmali fayl qabul qilinadi."
        )

    max_bytes = config.MAX_DB_UPLOAD_SIZE_MB * 1024 * 1024
    # Xotira himoyasi: butun faylni emas, eng ko'pi bilan (max_bytes + 1)
    # baytni o'qiymiz (utils.save_product_image dagi bilan bir xil mantiq).
    contents = file.file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Fayl hajmi {config.MAX_DB_UPLOAD_SIZE_MB}MB dan katta bo'lmasligi kerak.",
        )

    tmp_path = config.DATA_DIR / f".restore_tmp_{uuid.uuid4().hex}.db"
    tmp_path.write_bytes(contents)
    try:
        db_admin.restore_database(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    # Bazani almashtirgach, ushbu so'rov ochgan ESKI sessiya eski
    # ulanishga bog'liq bo'lishi mumkin -- holatni YANGI sessiya bilan
    # o'qiymiz.
    fresh_db = SessionLocal()
    try:
        return db_admin.get_database_status(fresh_db)
    finally:
        fresh_db.close()


# ---------- Konfiguratsiya to'plami (mahsulotlar+rasmlar, constructor
# sozlamalari, admin paroli, statistika/attack loglari) -- bittalab .zip
# fayl sifatida yuklab olish va qayta yuklash ----------
#
# Yagona /database/download dan farqli o'laroq, bu yerda TO'RTTA mustaqil
# bo'lim (+ rasmlar papkasi) ALOHIDA .db fayllar sifatida bitta zip'ga
# yig'iladi (qarang: config_bundle.py). Import paytida qaysi bo'lim zipda
# bo'lmasa, o'sha shunchaki o'tkazib yuboriladi -- qolganlari normal
# qo'llanadi.

@router.get("/config-bundle/export")
def export_config_bundle(_admin=Depends(security.get_current_admin)):
    """Mahsulotlar+rasmlar, constructor sozlamalari, admin paroli va
    statistika/attack loglarini bitta .zip fayl sifatida qaytaradi."""
    tmp_path = config.DATA_DIR / f".config_bundle_tmp_{uuid.uuid4().hex}.zip"
    config_bundle.build_export_bundle(tmp_path)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return FileResponse(
        tmp_path,
        filename=f"laminated_glasses_config_{timestamp}.zip",
        media_type="application/zip",
        # Vaqtinchalik zip jo'natilgach o'chiriladi -- diskda qolib
        # ketmaydi.
        background=BackgroundTask(lambda p=tmp_path: p.unlink(missing_ok=True)),
    )


@router.post("/config-bundle/import", response_model=schemas.ConfigBundleImportOut)
def import_config_bundle(
    request: Request,
    current_password: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin=Depends(security.get_current_admin),
):
    """XAVFLI AMAL: zip ichidagi HAR BIR MAVJUD bo'limni asosiy bazada/
    uploads papkasida TO'LIQ ALMASHTIRADI. Zipda bo'lmagan bo'limlar
    xatosiz o'tkazib yuboriladi.

    Himoya qatlamlari /database/restore bilan bir xil: admin joriy
    PAROLINI qayta kiritishi shart, alohida qattiq tezlik chegarasi bor,
    va almashtirishdan OLDIN joriy baza avtomatik zaxiralanadi.
    """
    security.enforce_rate_limit(
        request, "config_bundle_import", max_calls=5, window_seconds=3600
    )

    settings = db.query(models.SiteSettings).first()
    if settings is None or not security.verify_password(
        current_password, settings.password_hash
    ):
        raise HTTPException(status_code=400, detail="Joriy parol noto'g'ri.")

    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(
            status_code=400, detail="Faqat .zip kengaytmali fayl qabul qilinadi."
        )

    max_bytes = config.MAX_CONFIG_BUNDLE_UPLOAD_SIZE_MB * 1024 * 1024
    contents = file.file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Fayl hajmi {config.MAX_CONFIG_BUNDLE_UPLOAD_SIZE_MB}MB dan katta bo'lmasligi kerak.",
        )

    tmp_path = config.DATA_DIR / f".config_bundle_import_{uuid.uuid4().hex}.zip"
    tmp_path.write_bytes(contents)
    try:
        result = config_bundle.import_config_bundle(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    return result
