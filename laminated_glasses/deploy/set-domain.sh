#!/usr/bin/env bash
# Domenni (keyinroq) ulash yoki almashtirish uchun -- avval IP bilan
# o'rnatilgan bo'lsa, haqiqiy domen olingach shuni ishga tushiring.
#
# Ishlatish:
#   sudo bash deploy/set-domain.sh yangidomen.uz
# Keyin SSL uchun:
#   sudo certbot --nginx -d yangidomen.uz -d www.yangidomen.uz

set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo "sudo bilan ishga tushiring." >&2; exit 1
fi
DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
  echo "Foydalanish: sudo bash deploy/set-domain.sh domen.uz" >&2; exit 1
fi

ENV_FILE="/opt/laminated_glasses/backend/.env"
sed -i "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://${DOMAIN}|" "$ENV_FILE"

sed "s/server_name .*/server_name ${DOMAIN} www.${DOMAIN};/" \
  /opt/laminated_glasses/deploy/nginx.conf > /etc/nginx/sites-available/laminated_glasses
nginx -t
systemctl reload nginx
systemctl restart laminated-glasses

echo "Domen ${DOMAIN} ga sozlandi. Endi SSL uchun:"
echo "  sudo certbot --nginx -d ${DOMAIN} -d www.${DOMAIN}"
