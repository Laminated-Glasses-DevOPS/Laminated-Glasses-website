"""So'rov va javob ma'lumotlarini tekshiruvchi Pydantic sxemalari."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


def _clean_name(value: str) -> str:
    return " ".join(value.split()).strip()


class ProductPublic(BaseModel):
    """Mijozga ko'rinadigan mahsulot. Tannarx va foyda bu yerda yo'q."""

    id: int
    name: str
    description: str
    category: str
    sale_price: float
    image_url: Optional[str] = None
    image_urls: List[str] = []

    class Config:
        from_attributes = True


class SiteInfo(BaseModel):
    """Saytning ommaviy ma'lumoti. Telegram username bu yerda ATAYIN yo'q --
    u faqat buyurtmani rasmiylashtirish javobida beriladi."""

    site_title: str
    cart_ttl_days: int


class CustomerIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)
    name: str = Field(min_length=2, max_length=120)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        v = _clean_name(v)
        if len(v) < 2:
            raise ValueError("Ism juda qisqa.")
        return v

    @field_validator("device_id")
    @classmethod
    def normalize_device(cls, v: str) -> str:
        return v.strip()


class CustomerOut(BaseModel):
    id: int
    name: str
    device_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class CartItemIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)
    product_id: int
    quantity: int = Field(default=1, ge=1, le=99)


class CartQuantityIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)
    quantity: int = Field(ge=1, le=99)


class CartItemOut(BaseModel):
    id: int
    product_id: int
    name: str
    category: str
    unit_price: float
    quantity: int
    line_total: float
    image_url: Optional[str] = None
    expires_at: datetime
    days_left: int


class CartOut(BaseModel):
    items: List[CartItemOut]
    total_quantity: int
    total_amount: float
    cart_ttl_days: int
    removed_expired: int = 0


class CheckoutIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)


class CheckoutOut(BaseModel):
    """Telegram username FAQAT shu javobda qaytariladi."""

    order_code: str
    customer_name: str
    total_amount: float
    telegram_username: str
    telegram_url: str
    message_text: str


class ProductAdmin(BaseModel):
    id: int
    name: str
    description: str
    category: str
    cost_price: float
    sale_price: float
    profit: float
    profit_margin_percent: float
    image_url: Optional[str] = None
    image_urls: List[str] = []
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    category: str = Field(min_length=1, max_length=120)
    cost_price: float = Field(ge=0)
    sale_price: float = Field(ge=0)
    is_active: bool = True

    @field_validator("name", "category")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    category: Optional[str] = Field(default=None, min_length=1, max_length=120)
    cost_price: Optional[float] = Field(default=None, ge=0)
    sale_price: Optional[float] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class CategoryOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=4, max_length=200)


class UpdateTelegramRequest(BaseModel):
    telegram_username: str = Field(min_length=2, max_length=120)

    @field_validator("telegram_username")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        v = v.strip()
        if v.startswith("https://t.me/"):
            v = v.replace("https://t.me/", "")
        if not v.startswith("@"):
            v = "@" + v
        return v


class TelegramOut(BaseModel):
    telegram_username: str
    telegram_url: str
    site_title: str


class OrderItemOut(BaseModel):
    product_name: str
    quantity: int
    unit_price: float
    line_total: float

    class Config:
        from_attributes = True


class OrderAdminOut(BaseModel):
    id: int
    code: str
    customer_name: str
    total_amount: float
    total_profit: float
    status: str
    admin_note: str
    created_at: datetime
    confirmed_at: Optional[datetime] = None
    items: List[OrderItemOut]

    class Config:
        from_attributes = True


class OrderStatusUpdate(BaseModel):
    status: str
    admin_note: str = Field(default="", max_length=1000)

    @field_validator("status")
    @classmethod
    def check_status(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"new", "sold", "cancelled"}:
            raise ValueError("status faqat new, sold yoki cancelled bo'lishi mumkin.")
        return v


class VisitIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)


class DailyVisitPoint(BaseModel):
    date: str
    label: str
    unique_visitors: int


class AnalyticsResponse(BaseModel):
    today_visitors: int
    yesterday_visitors: int
    total_unique_devices: int
    total_views: int
    daily: List[DailyVisitPoint]


class StatsResponse(BaseModel):
    total_products: int
    active_products: int
    total_categories: int
    total_potential_revenue: float
    total_potential_cost: float
    total_potential_profit: float
    average_profit_margin_percent: float
    total_orders: int
    new_orders: int
    sold_orders: int
    sold_revenue: float
    sold_profit: float
