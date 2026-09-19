"""Ommaviy API -- saytga kirgan har qanday mehmon foydalanadigan qism.

Bu yerda hech qachon tannarx yoki foyda qaytarilmaydi. Telegram username ham
faqat bitta joyda -- buyurtmani rasmiylashtirish (checkout) javobida beriladi.
"""

from datetime import datetime, timedelta
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config, models, schemas, utils
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


def _customer_or_404(db: Session, device_id: str) -> models.Customer:
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.device_id == device_id.strip())
        .first()
    )
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Avval saytga ismingizni kiritib kiring.",
        )
    return customer


@router.get("/site", response_model=schemas.SiteInfo)
def site_info(db: Session = Depends(get_db)):
    return schemas.SiteInfo(
        site_title=_settings(db).site_title,
        cart_ttl_days=config.CART_TTL_DAYS,
    )


@router.post("/visit", status_code=204)
def log_visit(payload: schemas.VisitIn, db: Session = Depends(get_db)):
    """Sayt tashrifini qayd qiladi. Bitta qurilma bir kunda bir necha marta
    kirsa ham, (device_id, kun) jufti unique bo'lgani uchun faqat bitta
    qator saqlanadi -- ya'ni 1 ta qurilma = 1 ta ko'rish (view)."""
    today = datetime.utcnow().date()
    exists = (
        db.query(models.VisitLog)
        .filter(
            models.VisitLog.device_id == payload.device_id.strip(),
            models.VisitLog.visit_date == today,
        )
        .first()
    )
    if exists is not None:
        return None

    db.add(models.VisitLog(device_id=payload.device_id.strip(), visit_date=today))
    try:
        db.commit()
    except IntegrityError:
        # Parallel so'rov bir vaqtda xuddi shu qatorni yozgan bo'lishi mumkin --
        # bu holatda ham natija bir xil: 1 ta qurilma = 1 ta ko'rish.
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


@router.get("/customer/{device_id}", response_model=schemas.CustomerOut)
def get_customer(device_id: str, db: Session = Depends(get_db)):
    """Qurilma avval ro'yxatdan o'tganmi? O'tgan bo'lsa ismini qaytaradi va
    foydalanuvchidan qaytib so'ralmaydi."""
    customer = _customer_or_404(db, device_id)
    customer.last_seen_at = datetime.utcnow()
    db.commit()
    return customer


@router.post("/customer", response_model=schemas.CustomerOut, status_code=201)
def register_customer(payload: schemas.CustomerIn, db: Session = Depends(get_db)):
    """Ismni bazaga yozadi -- faqat BIR MAROTABA. Shu device_id allaqachon
    ro'yxatdan o'tgan bo'lsa, ism o'zgartirilmaydi va mavjud yozuv o'zgarishsiz
    qaytariladi: ism qurilmaga bir marta bog'lanadi va keyin almashtirib
    bo'lmaydi."""
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.device_id == payload.device_id)
        .first()
    )
    if customer is None:
        customer = models.Customer(device_id=payload.device_id, name=payload.name)
        db.add(customer)
    else:
        # Ism allaqachon qayd qilingan -- qayta yozilmaydi, faqat faollik vaqti yangilanadi.
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


@router.get("/cart/{device_id}", response_model=schemas.CartOut)
def get_cart(device_id: str, db: Session = Depends(get_db)):
    customer = _customer_or_404(db, device_id)
    removed = utils.purge_expired_cart_items(db, customer.id)
    return _cart_response(db, customer, removed)


@router.post("/cart", response_model=schemas.CartOut, status_code=201)
def add_to_cart(payload: schemas.CartItemIn, db: Session = Depends(get_db)):
    customer = _customer_or_404(db, payload.device_id)
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
    item_id: int, payload: schemas.CartQuantityIn, db: Session = Depends(get_db)
):
    customer = _customer_or_404(db, payload.device_id)
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
def delete_cart_item(item_id: int, device_id: str, db: Session = Depends(get_db)):
    customer = _customer_or_404(db, device_id)
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


@router.delete("/cart/{device_id}", response_model=schemas.CartOut)
def clear_cart(device_id: str, db: Session = Depends(get_db)):
    customer = _customer_or_404(db, device_id)
    db.query(models.CartItem).filter(models.CartItem.customer_id == customer.id).delete()
    db.commit()
    return _cart_response(db, customer)


@router.post("/checkout", response_model=schemas.CheckoutOut, status_code=201)
def checkout(payload: schemas.CheckoutIn, db: Session = Depends(get_db)):
    """Savatni buyurtmaga aylantiradi va Telegram havolasini qaytaradi.

    Telegram username butun loyihada faqat shu javobda uchraydi.
    """
    customer = _customer_or_404(db, payload.device_id)
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
