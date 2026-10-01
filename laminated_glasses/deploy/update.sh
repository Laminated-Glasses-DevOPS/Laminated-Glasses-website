#!/usr/bin/env bash
# Kodni yangilash (deploy) skripti -- VPS'da allaqachon o'rnatilgan loyihani
# yangi versiyaga ko'tarish uchun.
#
# Ishlatish (yangi kod papkasidan, root/sudo bilan):
#   sudo bash deploy/update.sh
#
# Ma'lumotlar (baza, uploads/, .env) HECH QACHON ustidan yozilmaydi --
# faqat kod fayllari yangilanadi.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Iltimos, root yoki sudo bilan ishga tushiring: sudo bash deploy/update.sh" >&2
  exit 1
fi

APP_DIR="/opt/laminated_glasses"
APP_USER="laminated_glasses"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Kod fayllari yangilanmoqda..."
rsync -a --delete \
  --exclude ".git" --exclude "backend/.venv" --exclude "backend/.env" \
  --exclude "backend/app/uploads" --exclude "backend/app/backups" \
  --exclude "__pycache__" \
  "$SCRIPT_DIR"/ "$APP_DIR"/

echo "==> Kutubxonalar yangilanmoqda (requirements.txt bo'yicha)..."
"$APP_DIR/backend/.venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"

chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
chown "$APP_USER":"$APP_USER" "$APP_DIR/backend/.env" 2>/dev/null || true

echo "==> Xizmat qayta ishga tushirilmoqda..."
systemctl restart laminated-glasses
sleep 1
systemctl --no-pager --full status laminated-glasses | head -n 8

echo ""
echo "Yangilash tugadi. Loglar: journalctl -u laminated-glasses -f"
