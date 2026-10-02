"""So'rov va javob ma'lumotlarini tekshiruvchi Pydantic sxemalari."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator


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
    # Ijtimoiy ko'rsatkichlar (like va izohlar soni; `liked` -- shu mijoz
    # like bosganmi, kirmagan mehmon uchun doim False).
    like_count: int = 0
    comment_count: int = 0
    liked: bool = False

    class Config:
        from_attributes = True


class SiteInfo(BaseModel):
    """Saytning ommaviy ma'lumoti. Telegram username bu yerda ATAYIN yo'q --
    u faqat buyurtmani rasmiylashtirish javobida beriladi."""

    site_title: str
    cart_ttl_days: int
    # Google Client ID ommaviy qiymat (brauzerdagi Google tugmasi uchun kerak);
    # u backend sozlamasidan (GOOGLE_CLIENT_ID) olinadi, frontendda qotirilmaydi.
    google_client_id: str = ""


class GoogleLoginIn(BaseModel):
    """Google tugmasi bosilgach brauzer olgan ID token (JWT)."""

    credential: str = Field(min_length=20, max_length=8192)
    # Faqat eski (ism bilan ro'yxatdan o'tgan) mijozning savatini yangi
    # akkauntga ko'chirish uchun; ixtiyoriy.
    device_id: Optional[str] = Field(default=None, max_length=64)


class CustomerOut(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    picture_url: Optional[str] = None
    created_at: datetime
    # False bo'lsa frontend ism so'rash oynasini ochadi.
    name_confirmed: bool = False

    class Config:
        from_attributes = True


class ProfileUpdateIn(BaseModel):
    """Profilda faqat ism o'zgaradi. Email bu yerda ATAYIN yo'q -- u Google'dan
    keladi va foydalanuvchi o'zgartira olmaydi."""

    name: str = Field(min_length=1, max_length=200)


class ConstructorLimitOut(BaseModel):
    """Konstruktor limiti holati (akkaunt bo'yicha)."""

    allowed: bool          # hozir yangi foydalanishni boshlash mumkinmi
    limit_hours: int       # limit oynasi (soat)
    retry_after_seconds: int = 0  # allowed=False bo'lsa, qancha soniyadan keyin


class AuthOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_days: int
    is_new: bool
    customer: CustomerOut


class CartItemIn(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=99)


class CartQuantityIn(BaseModel):
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
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)

    @field_validator("new_password")
    @classmethod
    def strong_enough(cls, v: str) -> str:
        if v.isdigit():
            raise ValueError("Parol faqat raqamlardan iborat bo'lmasligi kerak.")
        if len(set(v)) < 4:
            raise ValueError("Parol juda oddiy: turli belgilardan foydalaning.")
        if v.lower() in {"password", "12345678", "qwertyui", "admin123", "11111111"}:
            raise ValueError("Bu parol juda keng tarqalgan. Boshqasini tanlang.")
        return v


class UpdateSiteRequest(BaseModel):
    site_title: str = Field(min_length=2, max_length=200)

    @field_validator("site_title")
    @classmethod
    def clean_title(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Sayt nomi juda qisqa.")
        return v


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


class HoneypotMessageCreate(BaseModel):
    """Admin panelidan bitta IP manziliga yuboriladigan honeypot xabari."""

    ip_address: str = Field(min_length=3, max_length=64)
    message: str = Field(min_length=1, max_length=1000)
    telegram_username: Optional[str] = Field(default=None, max_length=120)

    @field_validator("ip_address", "message")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("telegram_username")
    @classmethod
    def normalize_username(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if v.startswith("https://t.me/"):
            v = v.replace("https://t.me/", "")
        v = v.lstrip("@")
        return v


class HoneypotMessageOut(BaseModel):
    id: int
    ip_address: str
    message: str
    telegram_username: Optional[str] = None
    is_active: bool
    created_at: datetime
    shown_count: int
    last_shown_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @field_serializer("created_at", "last_shown_at")
    def _serialize_utc(self, value: Optional[datetime]) -> Optional[str]:
        """Bazadagi vaqtlar naive UTC (datetime.utcnow()) -- frontend buni
        to'g'ri o'qishi uchun "Z" bilan aniq UTC ekanini bildiramiz,
        aks holda brauzer buni mahalliy vaqt deb noto'g'ri talqin qiladi."""
        if value is None:
            return None
        return value.isoformat() + "Z"


class PaneSize(BaseModel):
    """Bitta panelning o'z eni/bo'yi (sm). Har bir o'lchamda pane_count
    ta shundan bo'ladi -- endi ularning hammasi bir xil bo'lishi shart
    emas, har biri alohida sozlanadi."""

    width_cm: float = Field(gt=0, le=1000)
    height_cm: float = Field(gt=0, le=1000)


class ConstructorSizeOut(BaseModel):
    """Konstruktor sahifasida (ommaviy) ko'rinadigan o'lcham."""

    id: int
    label: str
    pane_count: int
    width_cm: float
    height_cm: float
    panes: List[PaneSize]
    price: float

    class Config:
        from_attributes = True


class ConstructorSizeAdminOut(ConstructorSizeOut):
    is_active: bool
    sort_order: int
    created_at: datetime


class ConstructorSizeCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    panes: List[PaneSize] = Field(min_length=1, max_length=20)
    price: float = Field(ge=0, default=0)
    is_active: bool = True
    sort_order: int = Field(default=0)

    @field_validator("label")
    @classmethod
    def strip_label(cls, v: str) -> str:
        return _clean_name(v)


class ConstructorSizeUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=120)
    panes: Optional[List[PaneSize]] = Field(default=None, min_length=1, max_length=20)
    price: Optional[float] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None

    @field_validator("label")
    @classmethod
    def strip_label(cls, v: Optional[str]) -> Optional[str]:
        return _clean_name(v) if v is not None else v


class ConstructorShareOut(BaseModel):
    """Konstruktor sahifasidagi \"Share\" tugmasi bosilganda qaytadigan
    javob: ikkala rasm (asl va oynalarga bo'lingan tayyor dizayn) diskka
    saqlanadi, so'ng mijozning Telegram ilovasi shu ikki havola bilan
    tayyor matn ochiladigan qilib qaytariladi -- xuddi checkout oqimidagi
    kabi, jo'natishni mijozning o'zi tasdiqlaydi (Telegram "Yuborish"
    tugmasini bosadi)."""

    telegram_username: str
    telegram_url: str
    original_image_url: str
    final_image_url: str
    message_text: str


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
    # Haqiqiy noyob odamlar: Google orqali kirgan odam qurilma sonidan
    # qat'i nazar 1 ta, kirmagan mehmon -- qurilma bo'yicha 1 ta.
    unique_visitors: int
    user_visitors: int = 0    # shundan Google orqali kirganlar
    guest_visitors: int = 0   # shundan kirmagan mehmonlar
    new_users: int = 0        # shu kuni ro'yxatdan o'tgan yangi foydalanuvchilar


class RecentUserOut(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    picture_url: Optional[str] = None
    login_count: int
    last_login_at: Optional[datetime] = None
    registered_at: Optional[datetime] = None

    @field_serializer("last_login_at", "registered_at")
    def _serialize_utc(self, value: Optional[datetime]) -> Optional[str]:
        return (value.isoformat() + "Z") if value else None


class AnalyticsResponse(BaseModel):
    today_visitors: int
    yesterday_visitors: int
    today_users: int = 0
    today_guests: int = 0
    total_unique_visitors: int = 0
    total_views: int
    # Foydalanuvchilar (faqat Google orqali kirganlar)
    total_users: int = 0
    new_users_today: int = 0
    new_users_yesterday: int = 0
    new_users_7d: int = 0
    active_users_7d: int = 0
    daily: List[DailyVisitPoint]
    recent_users: List[RecentUserOut] = []


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
    total_users: int = 0


class BackupFileOut(BaseModel):
    """Admin panelidagi \"Zaxira nusxalar\" bo'limida ko'rsatiladigan bitta
    Excel zaxira fayli haqidagi ma'lumot."""

    filename: str
    section: str
    section_label: str
    created_at: datetime
    size_kb: float

    @field_serializer("created_at")
    def _serialize_utc(self, value: datetime) -> str:
        return value.isoformat() + "Z"


class DatabaseTableCount(BaseModel):
    table: str
    label: str
    rows: int


class DatabaseStatusOut(BaseModel):
    """Admin panelidagi \"Baza holati\" bo'limi uchun: baza fayli, uploads/
    va backups/ hajmi, umumiy disk holati va har bir jadvaldagi qatorlar
    soni."""

    db_size_kb: float
    uploads_size_kb: float
    backups_size_kb: float
    disk_total_kb: float
    disk_used_kb: float
    disk_free_kb: float
    disk_used_percent: float
    tables: List[DatabaseTableCount]
    last_snapshot_at: Optional[datetime] = None

    @field_serializer("last_snapshot_at")
    def _serialize_last_snapshot(self, value: Optional[datetime]) -> Optional[str]:
        return (value.isoformat() + "Z") if value else None


class ConfigBundleImportOut(BaseModel):
    """Admin panelidagi \"Konfiguratsiyani qayta yuklash\" natijasi: zipda
    qaysi bo'limlar topilib qo'llanilgani (`applied`) va qaysilari
    topilmagani uchun o'tkazib yuborilgani (`skipped`)."""

    applied: List[str]
    skipped: List[str]
    snapshot_filename: Optional[str] = None
    restored_at: datetime

    @field_serializer("restored_at")
    def _serialize_restored(self, value: datetime) -> str:
        return value.isoformat() + "Z"


class DatabaseSnapshotOut(BaseModel):
    """Bazani \"tiklash\" (restore) dan OLDIN avtomatik yaratiladigan
    xavfsizlik nusxasi haqida ma'lumot."""

    filename: str
    created_at: datetime
    size_kb: float

    @field_serializer("created_at")
    def _serialize_created(self, value: datetime) -> str:
        return value.isoformat() + "Z"


class DatabaseRestoreConfirm(BaseModel):
    """Bazani tiklashdan oldin admin joriy parolini qayta kiritadi -- bu,
    o'g'irlangan/session-hijack qilingan tokenning bunday halokatli amalni
    (butun bazani almashtirish) bajarishiga qo'shimcha to'siq."""

    current_password: str = Field(min_length=1, max_length=200)


class CommentIn(BaseModel):
    """Izoh matni. Aniq uzunlik/belgilar tekshiruvi utils.clean_comment_text
    da (xato matni foydalanuvchiga chiroyli ko'rinishi uchun); bu yerda faqat
    juda katta so'rovlardan himoya."""

    body: str = Field(min_length=1, max_length=1000)


class CommentOut(BaseModel):
    """Ommaviy izoh: FAQAT ism va matn (+ vaqt). Email, rasm, mijoz ID'si yo'q."""

    id: int
    name: str
    body: str
    created_at: datetime
    edited: bool = False
    is_mine: bool = False
    # Profil rasmi (faqat Google rasm serveri manzili) va admin belgisi.
    avatar: Optional[str] = None
    is_admin: bool = False
    # Faqat izoh egasi uchun: yana necha marta tahrirlash mumkin.
    edits_left: int = 0

    @field_serializer("created_at")
    def _serialize_utc(self, value: datetime) -> str:
        return value.isoformat() + "Z"


class ProductSocialOut(BaseModel):
    like_count: int
    liked: bool
    comment_count: int
    comments: List[CommentOut]
    my_comment_count: int = 0
    comment_limit: int
    comment_max_length: int
    comment_max_edits: int = 3


class LikeOut(BaseModel):
    liked: bool
    like_count: int


class AdminCommentOut(BaseModel):
    """Admin moderatsiyasi uchun izoh: ommaviy javobdan farqli o'laroq admin
    izoh egasining emailini ham ko'radi (kim yozganini aniqlash uchun)."""

    id: int
    product_id: int
    product_name: str
    customer_id: int
    customer_name: str
    customer_email: Optional[str] = None
    customer_is_staff: bool = False
    body: str
    created_at: datetime
    edited_at: Optional[datetime] = None
    edit_count: int = 0

    @field_serializer("created_at", "edited_at")
    def _serialize_utc(self, value: Optional[datetime]) -> Optional[str]:
        return (value.isoformat() + "Z") if value else None


class AdminCommentListOut(BaseModel):
    total: int
    items: List[AdminCommentOut]


class AdminUserOut(BaseModel):
    """Admin panel: admin tayinlash uchun foydalanuvchi qatori."""

    id: int
    name: str
    email: Optional[str] = None
    picture_url: Optional[str] = None
    is_staff: bool = False
    last_login_at: Optional[datetime] = None

    @field_serializer("last_login_at")
    def _serialize_utc(self, value: Optional[datetime]) -> Optional[str]:
        return (value.isoformat() + "Z") if value else None


class AdminUserListOut(BaseModel):
    total: int
    items: List[AdminUserOut]


class StaffToggleIn(BaseModel):
    is_staff: bool
