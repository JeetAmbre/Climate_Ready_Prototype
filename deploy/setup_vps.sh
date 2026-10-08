#!/usr/bin/env bash
# ==============================================================================
# ClimateReady - Ubuntu 24.04 LTS VPS Automated Setup Script
# ==============================================================================
set -e

APP_DIR="/var/www/climateready"

echo "=== 1. Updating System Packages ==="
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv python3-dev build-essential \
               nginx certbot python3-certbot-nginx git curl libgdal-dev gdal-bin

echo "=== 2. Setting up Application Directory ==="
mkdir -p "$APP_DIR"
cd "$APP_DIR"

if [ ! -d "venv" ]; then
    echo "=== 3. Creating Python Virtual Environment ==="
    python3 -m venv venv
fi

echo "=== 4. Installing Python Dependencies ==="
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== 5. Setting up Systemd Service ==="
cp "$APP_DIR/deploy/climateready.service" /etc/systemd/system/climateready.service
systemctl daemon-reload
systemctl enable climateready

echo "=== 6. Setting up Nginx ==="
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/climateready
ln -sf /etc/nginx/sites-available/climateready /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx

echo "=============================================================================="
echo "Setup complete! Next steps:"
echo "1. Edit $APP_DIR/.env with your Google Earth Engine credentials."
echo "2. Edit /etc/nginx/sites-available/climateready with your actual domain."
echo "3. Run: systemctl restart nginx && systemctl start climateready"
echo "4. Obtain free SSL by running: certbot --nginx -d yourdomain.com"
echo "=============================================================================="
