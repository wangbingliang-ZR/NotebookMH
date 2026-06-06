#!/bin/bash
set -e

echo "========================================"
echo "  NotebookMH (超级笔记本) 一键部署脚本"
echo "========================================"
echo ""

# 配置
APP_DIR="/opt/notebookmh"
REPO_URL="https://github.com/wangbingliang-ZR/NotebookMH.git"
NGINX_SITE="/etc/nginx/sites-available/notebookmh"
SERVICE_FILE="/etc/systemd/system/notebookmh.service"
WWW_DIR="/var/www/hiroai"

# 检查 sudo 权限
if ! sudo -n true 2>/dev/null; then
    echo "错误：请用 sudo 运行此脚本"
    exit 1
fi

echo "[1/7] 克隆/更新代码..."
sudo mkdir -p "$APP_DIR"
sudo chown $USER:$USER "$APP_DIR"
cd "$APP_DIR"

if [ ! -d ".git" ]; then
    git clone "$REPO_URL" .
else
    git pull
fi

echo "[2/7] 创建 Python 虚拟环境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r NotebookMH/requirements.txt

echo "[3/7] 创建 .env 配置文件..."
cat > NotebookMH/.env << 'ENVEOF'
# NotebookMH 生产环境配置
DEEPSEEK_API_KEY=sk-e3bb80932b9c48b2872364655bcf3595
AI_BASE_URL=https://api.deepseek.com/v1
AI_MODEL=deepseek-chat
CHROMA_PERSIST_DIR=./data/chroma_db
LOG_LEVEL=INFO
ENV=production
PYVISTA_OFF_SCREEN=true
TELEMETRY_ENABLED=true
ENVEOF

echo "[4/7] 创建 systemd 服务..."
sudo tee "$SERVICE_FILE" > /dev/null << 'SVCEOF'
[Unit]
Description=NotebookMH (超级笔记本) Streamlit 应用
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/notebookmh/NotebookMH
Environment="PATH=/opt/notebookmh/venv/bin"
ExecStart=/opt/notebookmh/venv/bin/streamlit run app.py \
    --server.port=8501 \
    --server.address=127.0.0.1 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable notebookmh

echo "[5/7] 配置 Nginx 反向代理..."
sudo tee "$NGINX_SITE" > /dev/null << 'NGXEOF'
server {
    listen 80;
    server_name notebook.hiroai.cn;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
    }

    location /_stcore/stream {
        proxy_pass http://127.0.0.1:8501/_stcore/stream;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
NGXEOF

sudo ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

echo "[6/7] 更新静态网站到 $WWW_DIR..."
sudo mkdir -p "$WWW_DIR"
if [ -d "$APP_DIR/website" ]; then
    sudo cp -r "$APP_DIR/website/"* "$WWW_DIR/"
fi

echo "[7/7] 启动 NotebookMH 服务..."
sudo systemctl restart notebookmh
sleep 3

if sudo systemctl is-active --quiet notebookmh; then
    echo ""
    echo "========================================"
    echo "  ✅ 部署成功！"
    echo "========================================"
    echo ""
    echo "  Streamlit 状态: $(sudo systemctl is-active notebookmh)"
    echo "  本地访问: http://127.0.0.1:8501"
    echo "  域名访问: http://notebook.hiroai.cn"
    echo ""
    echo "  ⚠️  重要：请在腾讯云 DNS 添加记录："
    echo "     notebook.hiroai.cn A -> $(curl -s ip.sb || hostname -I | awk '{print $1}')"
    echo ""
    echo "  查看日志: sudo journalctl -u notebookmh -f"
    echo "  重启服务: sudo systemctl restart notebookmh"
    echo ""
else
    echo ""
    echo "========================================"
    echo "  ❌ 服务启动失败，查看日志："
    echo "========================================"
    sudo journalctl -u notebookmh --no-pager -n 50
    exit 1
fi
