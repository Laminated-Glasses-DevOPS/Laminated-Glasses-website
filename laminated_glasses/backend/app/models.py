"""Ma'lumotlar bazasi jadvallari."""

import json
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
    images_json = Column(Text, nullable=False, default="[]")
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
    """Google akkaunti orqali kirgan foydalanuvchi.

    HAR BIR GOOGLE AKKAUNT = BITTA MIJOZ. Akkauntning o'zgarmas identifikatori
    (`google_sub`, Google ID tokenidagi `sub`) unique -- shu sababli bir
    akkauntdan 2-, 3-marta kirilganda yangi yozuv ochilmaydi: mavjud yozuv
    topiladi, faqat `login_count` va `last_login_at` yangilanadi. Bir akkaunt
    bir necha qurilmadan kirsa ham bitta mijoz (va bitta savat) bo'lib qoladi.
    Email emas, aynan `sub` ishlatiladi -- email o'zgarishi mumkin, `sub` yo'q.

    device_id -- eski (faqat ism kiritiladigan) tizimdan qolgan ustun. Ustun
    NOT NULL/unique bo'lgani va SQLite'da uni o'zgartirib bo'lmagani uchun
    Google mijozlarida "google:<sub>" qiymati yoziladi. Eski mijozlarda esa
    asl qurilma identifikatori turadi (ular birinchi Google kirishida
    savati va buyurtmalari bilan shu akkauntga biriktiriladi).
    """

    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)

    google_sub = Column(String(64), unique=True, nullable=True, index=True)
    email = Column(String(255), nullable=True, index=True)
    email_verified = Column(Integer, nullable=False, default=0, server_default="0")
    picture_url = Column(String(500), nullable=True)
    given_name = Column(String(120), nullable=True)
    family_name = Column(String(120), nullable=True)
    locale = Column(String(20), nullable=True)
    # 1 = foydalanuvchi Google akkauntni tanlagach ismini o'zi kiritgan/tasdiqlagan.
    # 0 bo'lsa keyingi kirishda ism so'raladi; 1 bo'lgach Google ismi uni
    # qayta yozib yubormaydi (profilda o'zgartirilgan ism saqlanib qoladi).
    name_confirmed = Column(Integer, nullable=False, default=0, server_default="0")
    login_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_login_at = Column(DateTime, nullable=True)
    # Google akkaunt shu mijozga BIRINCHI marta bog'langan payt (yangi
    # foydalanuvchilar statistikasi shu bo'yicha; created_at eski, ism bilan
    # ro'yxatdan o'tgan mijozlarda eskiroq bo'lishi mumkin).
    google_registered_at = Column(DateTime, nullable=True)
    # 1 = admin paneldan "admin" qilib tayinlangan mijoz: izohlarida tasdiqlash
    # belgisi (✔ Admin) ko'rinadi. Bu admin panelga kirish huquqi BERMAYDI.
    is_staff = Column(Integer, nullable=False, default=0, server_default="0")

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
    uchun faqat bitta qator yoziladi. Google orqali kirgan odam esa qurilma
    sonidan qat'i nazar (customer_id bo'yicha) 1 ta hisoblanadi. (device_id, visit_date)
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
    # Tashrif qilgan odam Google orqali kirgan bo'lsa -- uning mijoz ID'si.
    # Statistikada "haqiqiy odam" = customer_id (bo'lsa), aks holda device_id:
    # bir odam ikki qurilmadan kirsa ham 1 ta hisoblanadi.
    customer_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LoginAttempt(Base):
    """Admin login uchun brute-force himoyasi (IP bo'yicha)."""

    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(String(64), index=True, nullable=False)
    attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SecurityEvent(Base):
    """Honeypot qatlami tutgan SQL Injection / XSS urinishlari jurnali.

    Haqiqiy zaiflik yo'q (ORM parametrlangan so'rovlar, chiqish escape
    qilinadi) -- bu jadval faqat kim, qachon va qanday usulda urinib
    ko'rganini kuzatish uchun."""

    __tablename__ = "security_events"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(20), nullable=False, index=True)  # "sql_injection" | "xss"
    xss_type = Column(String(60), nullable=True)
    ip_address = Column(String(64), index=True, nullable=False)
    path = Column(String(500), nullable=False)
    method = Column(String(10), nullable=False, default="GET")
    matched_sample = Column(String(300), nullable=False, default="")
    user_agent = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class HoneypotMessage(Base):
    """Admin honeypot orqali muayyan IP manziliga yuborgan shaxsiy xabar.

    Hujumchi (SQLi/XSS urinuvchi) keyingi safar honeypot sahifasiga
    tushganda, standart kinoyali matn o'rniga shu yerdagi `message`
    ko'rsatiladi, pastida esa (agar `telegram_username` bo'lsa) "Javob"
    tugmasi chiqadi -- bosilsa t.me/<username> ga olib boradi.

    is_active=0 qilingan yozuvlar honeypot tomonidan e'tiborga
    olinmaydi (admin bekor qilgan yoki eskirgan)."""

    __tablename__ = "honeypot_messages"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(String(64), nullable=False, index=True)
    message = Column(Text, nullable=False)
    telegram_username = Column(String(120), nullable=True)
    is_active = Column(Integer, nullable=False, default=1, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    shown_count = Column(Integer, nullable=False, default=0)
    last_shown_at = Column(DateTime, nullable=True)


class HoneypotHeartbeat(Base):
    """Honeypot 400-sahifasi ochiq turgan brauzerlardan kelayotgan "yurak
    urishi". Admin paneldagi Onlayn/Oflayn holati SecurityEvent.created_at
    (oxirgi HUJUM vaqti) emas, aynan shu jadval asosida hisoblanadi -- shu
    tufayli hujumchi hech narsa qilmay sahifada shunchaki turgan bo'lsa ham
    "Onlayn" ko'rinadi, brauzerini yopgach esa tezda "Oflayn"ga o'tadi."""

    __tablename__ = "honeypot_heartbeats"

    ip_address = Column(String(64), primary_key=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # 1 = sahifa ochiq deb hisoblanadi (heartbeat yoki dastlabki render orqali);
    # 0 = tab/sahifa yopilgani haqida aniq signal (sendBeacon) kelgan.
    is_open = Column(Integer, nullable=False, default=1)


class NewsPost(Base):
    __tablename__ = "news_posts"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(220), nullable=False)
    excerpt = Column(Text, nullable=False, default="")
    body = Column(Text, nullable=False, default="")
    image_url = Column(String(500), nullable=True)
    is_published = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ConstructorSize(Base):
    """Admin belgilagan, mijoz konstruktor sahifasida tanlashi mumkin bo'lgan
    oyna o'lchamlari (masalan: \"40 x 60 sm\"). Odatda 2-3 ta o'lcham
    yetarli, lekin admin xohlagancha qo'shishi/o'chirishi mumkin.

    pane_count -- shu o'lcham tanlanganda rasm nechta alohida oyna
    (panel)ga bo'lib ko'rsatilishi. Har bir panel endi O'ZINING alohida
    eni/bo'yiga ega bo'lishi mumkin -- bular `panes_json` da
    [{"width_cm":.., "height_cm":..}, ...] (uzunligi pane_count ga teng)
    shaklida saqlanadi. width_cm/height_cm ustunlari orqaga moslik va
    tezkor saralash/ko'rsatish uchun umumiy o'lcham sifatida saqlanadi:
    width_cm = barcha panellar enlarining yig'indisi (umumiy kenglik),
    height_cm = panellar bo'yining eng kattasi (umumiy balandlik).

    is_active=0 bo'lgan o'lchamlar konstruktor sahifasida ko'rinmaydi, lekin
    bazada saqlanib qoladi -- admin keyin qayta yoqishi mumkin."""

    __tablename__ = "constructor_sizes"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String(120), nullable=False)
    pane_count = Column(Integer, nullable=False, default=1)
    width_cm = Column(Float, nullable=False)
    height_cm = Column(Float, nullable=False)
    panes_json = Column(Text, nullable=True)
    price = Column(Float, nullable=False, default=0.0)
    is_active = Column(Integer, nullable=False, default=1)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def panes(self):
        """Har bir panelning alohida o'lchamini ro'yxat sifatida qaytaradi.

        Eski (panes_json hali yozilmagan) qatorlar uchun orqaga moslik:
        pane_count ta bir xil width_cm/height_cm dan iborat ro'yxat
        qaytariladi -- xuddi avvalgi "hammasi bir xil o'lchamda" xatti-
        harakati kabi."""
        if self.panes_json:
            try:
                data = json.loads(self.panes_json)
                if isinstance(data, list) and data:
                    return data
            except (ValueError, TypeError):
                pass
        count = max(1, int(self.pane_count or 1))
        return [
            {"width_cm": self.width_cm, "height_cm": self.height_cm}
            for _ in range(count)
        ]


class SiteLink(Base):
    __tablename__ = "site_links"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(40), unique=True, nullable=False, index=True)
    value = Column(String(500), nullable=False, default="")


class ConstructorUsage(Base):
    """Konstruktordan foydalanish jurnali -- LIMIT shu jadval asosida ishlaydi.

    Har bir Google akkaunt (customer_id) uchun `used_at` dan boshlab
    config.CONSTRUCTOR_LIMIT_HOURS (24) soat davomida yangi foydalanish
    boshlab bo'lmaydi. Limit akkaunt bo'yicha alohida: bir odam boshqa
    Gmail bilan kirsa, u akkaunt uchun o'z limiti bor. Muddati o'tgan
    yozuvlar cleanup.py tomonidan tozalab turiladi."""

    __tablename__ = "constructor_usage"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    used_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class ProductLike(Base):
    """Mahsulotga bosilgan "yurakcha". Bitta Google akkaunt bitta mahsulotga
    faqat BITTA like bosa oladi (unique) -- qayta bosilsa, like olib tashlanadi
    (qatori o'chadi). Faqat Google orqali kirgan mijoz bosa oladi."""

    __tablename__ = "product_likes"
    __table_args__ = (
        UniqueConstraint("product_id", "customer_id", name="uq_like_product_customer"),
    )

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProductComment(Base):
    """Mahsulotga yozilgan izoh -- barcha foydalanuvchilarga ko'rinadi.

    Izohni faqat Google orqali kirgan mijoz yozadi. Ommaviy javobda faqat
    mijozning ISMI va izoh matni chiqadi (email, rasm va ID chiqmaydi --
    xavfsizlik uchun). Mijoz o'z izohini tahrirlashi/o'chirishi mumkin;
    tahrirlanganda `edited_at` to'ldiriladi. Limit: bitta akkaunt bitta
    mahsulotga config.COMMENT_MAX_PER_USER_PER_PRODUCT tagacha izoh yozadi."""

    __tablename__ = "product_comments"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    body = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    edited_at = Column(DateTime, nullable=True)
    # Izoh necha marta tahrirlangan (limit: config.COMMENT_MAX_EDITS).
    edit_count = Column(Integer, nullable=False, default=0, server_default="0")
