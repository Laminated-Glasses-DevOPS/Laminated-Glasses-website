# VPS'ga o'rnatish (Ubuntu/Debian)

Loyiha endi uchta joyda muammosiz ishlaydi:
- **VPS + nginx** (bu qo'llanma)
- **VPS + Cloudflare Tunnel** (nginx shart emas, pastga qarang)
- **Render.com** (o'zgarishsiz, `render.yaml` orqali)

## 1) Birinchi o'rnatish

```bash
# Serverga loyihani ko'chiring (git clone yoki scp/rsync orqali), masalan:
git clone <repo-url> laminated_glasses
cd laminated_glasses

sudo bash deploy/install.sh domen.uz
# Domen hali yo'q bo'lsa, server IP manzilini yozing:
#   sudo bash deploy/install.sh 203.0.113.10
```

Skript avtomatik qiladi:
- Python, nginx o'rnatadi, virtual muhit yaratadi
- Alohida, imtiyozsiz `laminated_glasses` tizim foydalanuvchisi yaratadi
- Ma'lumotlarni `/var/lib/laminated_glasses` ga (kod papkasidan ALOHIDA,
  doimiy) joylaydi -- kodni yangilasangiz ham (`update.sh`) baza, rasmlar,
  admin parol va JWT kaliti saqlanib qoladi
- `.env` faylini yaratadi, `SECRET_KEY` ni avtomatik generatsiya qiladi
- systemd xizmati (`laminated-glasses`) va nginx'ni sozlab ishga tushiradi

O'rnatilgach, admin boshlang'ich parolini ko'ring:

```bash
sudo journalctl -u laminated-glasses -n 50 --no-pager
```

## 2) Domen ulash

**Agar domen `install.sh` ga darhol berilgan bo'lsa** -- hech narsa qilish
shart emas, nginx allaqachon o'sha domenga sozlangan. Faqat domenning DNS
(A yozuvi) shu server IP'siga yo'nalganini tekshiring, so'ng SSL oling:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d domen.uz -d www.domen.uz
```

**Agar avval IP bilan o'rnatgan bo'lsangiz va endi domen qo'shmoqchi
bo'lsangiz:**

```bash
sudo bash deploy/set-domain.sh domen.uz
sudo certbot --nginx -d domen.uz -d www.domen.uz
```

Certbot SSL sertifikatini avtomatik yangilab turadi (systemd timer orqali) --
qo'shimcha hech narsa qilish shart emas.

## 3) Kodni yangilash

Serverdagi loyiha papkasiga yangi kodni tushirgandan so'ng (git pull yoki
qayta yuklash), shu papkadan:

```bash
sudo bash deploy/update.sh
```

Bu faqat kod fayllarini yangilaydi -- baza, uploads/, `.env` ga tegilmaydi.

## 4) Foydali buyruqlar

```bash
# Holat va so'nggi loglar
sudo systemctl status laminated-glasses
sudo journalctl -u laminated-glasses -f

# Qayta ishga tushirish (masalan .env o'zgartirgandan keyin)
sudo systemctl restart laminated-glasses

# nginx sozlamasini tekshirish/yangilash
sudo nginx -t && sudo systemctl reload nginx
```

## 5) Cloudflare Tunnel bilan (nginx'siz, muqobil variant)

Agar VPS o'rniga yoki VPS ustida nginx'siz, to'g'ridan-to'g'ri `cloudflared`
orqali chiqarmoqchi bo'lsangiz:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
cloudflared tunnel run <tunnel-nomi>
```

`.env` da `TRUST_X_FORWARDED_FOR=auto` (standart) qoldiring -- Cloudflare
Tunnel `CF-Connecting-IP` headerini qo'yadi va bu avtomatik, xavfsiz tarzda
ishlatiladi, qo'shimcha sozlash kerak emas.

## 6) Backup / ma'lumotlarni saqlash

Buyurtmalar, yangiliklar va xavfsizlik jurnali endi **avtomatik
o'chirilmaydi va Excel'ga zaxiralanmaydi** -- faqat admin siz xohlagan
vaqtda, admin panel -> tegishli bo'lim orqali qo'lda o'chirasiz.

To'liq ma'lumotlarni (mahsulotlar, buyurtmalar, sozlamalar) saqlab qo'yish
uchun admin panel -> "Baza holati" -> ".db faylni yuklab olish" dan
foydalaning. Buni davriy ravishda (masalan haftada bir marta) qo'lda qilib
turishni tavsiya qilamiz, yoki serverda oddiy cron bilan avtomatlashtiring:

```bash
# /etc/cron.d/laminated_glasses_backup (namuna -- ixtiyoriy)
0 3 * * * root cp /var/lib/laminated_glasses/laminated_glasses.db /var/backups/lg_$(date +\%F).db
```
