#!/usr/bin/env bash
# Laminated Glasses -- VPS'ga BIRINCHI marta o'rnatish skripti (Ubuntu/Debian).
#
# Ishlatish (repo papkasidan, root yoki sudo huquqi bilan):
#   sudo bash deploy/install.sh domen.uz
#
# "domen.uz" o'rniga haligacha domen yo'q bo'lsa, server IP manzilini yozing
# (masalan 203.0.113.10) -- keyin domen ulanganda deploy/set-domain.sh orqali
# almashtirish mumkin.
#
# Nima qiladi:
#   1) Python, nginx, venv o'rnatadi (allaqachon bo'lsa, o'tkazib yuboradi)
#   2) Loyihani /opt/laminated_glasses ga nusxalaydi
#   3) Alohida, imtiyozsiz tizim foydalanuvchisi (laminated_glasses) yaratadi
#   4) Doimiy ma'lumotlar papkasini (/var/lib/laminated_glasses) tayyorlaydi
#   5) .env faylini yaratadi (admin parol va JWT kaliti avtomatik generatsiya qilinadi)
#   6) systemd xizmatini va nginx'ni sozlab, ishga tushiradi
#
# SSL (HTTPS) BU SKRIPTGA KIRMAYDI -- domen DNS orqali shu serverga
# yo'naltirilgandan so'ng, alohida ishga tushiring:
#   sudo apt install -y certbot python3-certbot-nginx
#   sudo certbot --nginx -d domen.uz -d www.domen.uz

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Iltimos, root yoki sudo bilan ishga tushiring: sudo bash deploy/install.sh domen.uz" >&2
  exit 1
fi

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
  echo "Foydalanish: sudo bash deploy/install.sh domen.uz" >&2
  echo "(Domen hali yo'q bo'lsa, server IP manzilini yozing.)" >&2
  exit 1
fi

APP_DIR="/opt/laminated_glasses"
DATA_DIR="/var/lib/laminated_glasses"
APP_USER="laminated_glasses"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Paketlar o'rnatilmoqda..."
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nginx rsync

echo "==> Tizim foydalanuvchisi tayyorlanmoqda..."
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

echo "==> Loyiha fayllari $APP_DIR ga nusxalanmoqda..."
mkdir -p "$APP_DIR"
rsync -a --delete \
  --exclude ".git" --exclude "backend/.venv" --exclude "backend/.env" \
  --exclude "backend/app/uploads" --exclude "backend/app/backups" \
  --exclude "__pycache__" \
  "$SCRIPT_DIR"/ "$APP_DIR"/

echo "==> Doimiy ma'lumotlar papkasi tayyorlanmoqda ($DATA_DIR)..."
mkdir -p "$DATA_DIR"
chown -R "$APP_USER":"$APP_USER" "$DATA_DIR"
chmod 700 "$DATA_DIR"

echo "==> Python virtual muhit va kutubxonalar..."
python3 -m venv "$APP_DIR/backend/.venv"
"$APP_DIR/backend/.venv/bin/pip" install --upgrade pip -q
"$APP_DIR/backend/.venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"

ENV_FILE="$APP_DIR/backend/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "==> .env fayli yaratilmoqda (${ENV_FILE})..."
  SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
  cp "$APP_DIR/backend/.env.example" "$ENV_FILE"
  # Faqat bo'sh kelgan qatorlarni to'ldiramiz -- foydalanuvchi keyin
  # GOOGLE_CLIENT_ID kabi qolganlarini o'zi .env faylida tahrirlaydi.
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|" "$ENV_FILE"
  sed -i "s|^DATA_DIR=.*|DATA_DIR=${DATA_DIR}|" "$ENV_FILE"
  if [[ "$DOMAIN" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    # IP manzil berilgan bo'lsa, hali HTTPS yo'q -- http:// bilan yozamiz.
    sed -i "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=http://${DOMAIN}|" "$ENV_FILE"
  else
    sed -i "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://${DOMAIN}|" "$ENV_FILE"
  fi
else
  echo "==> .env fayli allaqachon mavjud, o'zgartirilmadi."
fi
chown "$APP_USER":"$APP_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "==> Egalik huquqlari..."
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

echo "==> systemd xizmati sozlanmoqda..."
cp "$APP_DIR/deploy/laminated-glasses.service" /etc/systemd/system/laminated-glasses.service
systemctl daemon-reload
systemctl enable --now laminated-glasses

echo "==> nginx sozlanmoqda (domen: ${DOMAIN})..."
sed "s/domen\.uz www\.domen\.uz/${DOMAIN}/" "$APP_DIR/deploy/nginx.conf" > /etc/nginx/sites-available/laminated_glasses
ln -sf /etc/nginx/sites-available/laminated_glasses /etc/nginx/sites-enabled/laminated_glasses
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo ""
echo "============================================================"
echo "  O'RNATISH TUGADI."
echo "  Sayt hozircha: http://${DOMAIN}"
echo ""
echo "  QOLGAN QADAMLAR:"
echo "   1) ${ENV_FILE} faylini oching va GOOGLE_CLIENT_ID ni yozing"
echo "      (Google kirish kerak bo'lsa), so'ng:"
echo "        sudo systemctl restart laminated-glasses"
echo "   2) Admin boshlang'ich paroli konsol logida ko'rinadi:"
echo "        sudo journalctl -u laminated-glasses -n 50 --no-pager"
echo "   3) DNS orqali ${DOMAIN} shu serverga yo'naltirilgandan so'ng, SSL:"
echo "        sudo apt install -y certbot python3-certbot-nginx"
echo "        sudo certbot --nginx -d ${DOMAIN}"
echo "============================================================"
