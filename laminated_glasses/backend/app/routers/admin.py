"""Admin API -- faqat to'g'ri JWT tokeni bo'lganlar kira oladigan qism."""

from datetime import datetime, timedelta
import json
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
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import config, models, schemas, security, utils
from ..database import get_db

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

    product = models.Product(
        name=name.strip(),
        description=description.strip(),
        category=category.strip(),
        cost_price=cost_price,
        sale_price=sale_price,
        is_active=1 if is_active else 0,
        image_filename=image_filename,
        images_json=json.dumps(saved),
    )
    db.add(product)

    if not db.query(models.Category).filter_by(name=product.category).first():
        db.add(models.Category(name=product.category))

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
        product.category = category.strip()
        if not db.query(models.Category).filter_by(name=product.category).first():
            db.add(models.Category(name=product.category))
    if cost_price is not None:
        product.cost_price = cost_price
    if sale_price is not None:
        product.sale_price = sale_price
    if is_active is not None:
        product.is_active = 1 if is_active else 0

    files = [f for f in images if f and f.filename]
    if image and image.filename: files.insert(0, image)
    if files:
        new_files = [utils.save_product_image(f) for f in files]
        product.images_json = json.dumps(new_files)
        product.image_filename = new_files[0]

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
    utils.delete_product_image(product.image_filename)
    db.delete(product)
    db.commit()
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
    if db.query(models.Category).filter_by(name=payload.name).first():
        raise HTTPException(status_code=409, detail="Bu kategoriya allaqachon mavjud.")
    category = models.Category(name=payload.name)
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

    total_revenue = sum(p.sale_price for p in products)
    total_cost = sum(p.cost_price for p in products)

    margins = [p.profit_margin_percent for p in products if p.sale_price]
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
