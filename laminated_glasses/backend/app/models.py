"""Ma'lumotlar bazasi jadvallari."""

from datetime import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, default="")
    category = Column(String(120), nullable=False, index=True)

    cost_price = Column(Float, nullable=False, default=0.0)
    sale_price = Column(Float, nullable=False, default=0.0)

    image_filename = Column(String(255), nullable=True)
    is_active = Column(Integer, default=1)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def profit(self) -> float:
        return round(self.sale_price - self.cost_price, 2)

    @property
    def profit_margin_percent(self) -> float:
        if not self.sale_price:
            return 0.0
        return round((self.profit / self.sale_price) * 100, 2)


class Customer(Base):
    """Saytga ismini kiritib kirgan foydalanuvchi.

    device_id -- brauzer birinchi marta ochilganda yaratiladigan va
    localStorage da saqlanadigan yagona identifikator. Shu tufayli
    foydalanuvchi ismini faqat bir marta kiritadi.
    """

    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cart_items = relationship(
        "CartItem", back_populates="customer", cascade="all, delete-orphan"
    )
    orders = relationship("Order", back_populates="customer")


class CartItem(Base):
    """Savatdagi bitta qator. expires_at -- 7 kundan keyingi sana."""

    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)

    customer = relationship("Customer", back_populates="cart_items")
    product = relationship("Product")


class Order(Base):
    """Rasmiylashtirilgan buyurtma.

    status:
        new       -- mijoz rasmiylashtirdi, sotuvchi hali tasdiqlamagan
        sold      -- tovar sotildi (admin tasdiqladi)
        cancelled -- bekor qilindi
    """

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False, index=True)

    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    customer_name = Column(String(120), nullable=False)

    total_amount = Column(Float, nullable=False, default=0.0)
    total_cost = Column(Float, nullable=False, default=0.0)

    status = Column(String(20), nullable=False, default="new", index=True)
    admin_note = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    confirmed_at = Column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="orders")
    items = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )

    @property
    def total_profit(self) -> float:
        return round(self.total_amount - self.total_cost, 2)


class OrderItem(Base):
    """Buyurtma tarkibidagi mahsulot. Narx va nom buyurtma paytidagi holatda
    saqlanadi -- keyin mahsulot narxi o'zgarsa ham tarix buzilmaydi."""

    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, nullable=True)
    product_name = Column(String(200), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Float, nullable=False, default=0.0)
    unit_cost = Column(Float, nullable=False, default=0.0)

    order = relationship("Order", back_populates="items")

    @property
    def line_total(self) -> float:
        return round(self.unit_price * self.quantity, 2)


class SiteSettings(Base):
    """Yagona qator sifatida saqlanadigan umumiy sozlamalar."""

    __tablename__ = "site_settings"

    id = Column(Integer, primary_key=True, default=1)
    password_hash = Column(String(255), nullable=False)
    telegram_username = Column(String(120), nullable=False, default="@laminated_glasses")
    site_title = Column(String(200), nullable=False, default="Laminated Glasses")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VisitLog(Base):
    """Saytga tashriflarni hisoblash uchun jadval.

    Bitta qurilma (device_id) bir kunda bir necha marta kirsa ham, shu kun
    uchun faqat bitta qator yoziladi -- shu tufayli statistikada "1 ta
    qurilma = 1 ta ko'rish (view)" tamoyili saqlanadi. (device_id, visit_date)
    juftligi unique bo'lgani uchun takroriy yozuv bazada hech qachon
    hosil bo'lmaydi.
    """

    __tablename__ = "visit_logs"
    __table_args__ = (
        UniqueConstraint("device_id", "visit_date", name="uq_visit_device_day"),
    )

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(64), nullable=False, index=True)
    visit_date = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LoginAttempt(Base):
    """Admin login uchun brute-force himoyasi (IP bo'yicha)."""

    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(String(64), index=True, nullable=False)
    attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
