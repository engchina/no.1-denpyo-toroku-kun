#!/bin/bash
set -euo pipefail

# Redirect all output to log file
exec > >(tee -a /var/log/init_script.log) 2>&1

echo "アプリケーションのセットアップを初期化中..."

# Configuration
INSTALL_DIR="/u01/aipoc"

# Read configuration flags
COMPUTE_SUBNET_PRIVATE="auto"
APT_BACKGROUND_SUSPENDED=0

if [ -f "${INSTALL_DIR}/props/compute_subnet_is_private.txt" ]; then
    COMPUTE_SUBNET_PRIVATE=$(tr -d '[:space:]' < "${INSTALL_DIR}/props/compute_subnet_is_private.txt" | tr '[:upper:]' '[:lower:]')
    case "$COMPUTE_SUBNET_PRIVATE" in
        true|false) ;;
        *)
            COMPUTE_SUBNET_PRIVATE="auto"
            ;;
    esac
fi

echo "ComputeサブネットPrivate判定: $COMPUTE_SUBNET_PRIVATE"
NODE_VERSION="20.x"
INSTANTCLIENT_VERSION="23.26.0.0.0"
INSTANTCLIENT_ZIP="instantclient-basic-linux.x64-${INSTANTCLIENT_VERSION}.zip"
INSTANTCLIENT_URL="https://download.oracle.com/otn_software/linux/instantclient/2326000/${INSTANTCLIENT_ZIP}"
INSTANTCLIENT_SQLPLUS_ZIP="instantclient-sqlplus-linux.x64-${INSTANTCLIENT_VERSION}.zip"
INSTANTCLIENT_SQLPLUS_URL="https://download.oracle.com/otn_software/linux/instantclient/2326000/${INSTANTCLIENT_SQLPLUS_ZIP}"
LIBAIO_DEB="libaio1_0.3.113-4_amd64.deb"
LIBAIO_URL="http://ftp.de.debian.org/debian/pool/main/liba/libaio/${LIBAIO_DEB}"
INSTANTCLIENT_DIR="${INSTALL_DIR}/instantclient_23_26"

# Helper function for retrying commands
retry_command() {
    local max_attempts=5
    local timeout=10
    local attempt=1
    local exit_code=0

    while [ $attempt -le $max_attempts ]; do
        echo "Attempt $attempt of $max_attempts: $@"
        "$@" && return 0
        exit_code=$?
        echo "Command failed with exit code $exit_code. Retrying in $timeout seconds..."
        sleep $timeout
        attempt=$((attempt + 1))
        timeout=$((timeout * 2))
    done

    echo "Command failed after $max_attempts attempts."
    return $exit_code
}

wait_for_apt_availability() {
    local timeout="${1:-1800}"
    local interval=5
    local elapsed=0
    local lock_holders=""
    local service=""
    local lock_files=(
        /var/lib/apt/lists/lock
        /var/cache/apt/archives/lock
        /var/lib/dpkg/lock
        /var/lib/dpkg/lock-frontend
    )
    local services=(
        apt-daily.service
        apt-daily-upgrade.service
        unattended-upgrades.service
    )
    local active_services=()

    while [ "$elapsed" -lt "$timeout" ]; do
        active_services=()
        for service in "${services[@]}"; do
            if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$service"; then
                active_services+=("$service")
            fi
        done

        lock_holders=""
        if command -v fuser >/dev/null 2>&1; then
            lock_holders=$(fuser "${lock_files[@]}" 2>/dev/null | tr ' ' '\n' | sed '/^$/d' | sort -u | tr '\n' ' ' | xargs 2>/dev/null || true)
        else
            lock_holders=$(ps -eo pid=,comm= | awk '$2 ~ /^(apt|apt-get|dpkg|unattended-upgr|unattended-upgrade|packagekitd)$/ {print $1}' | xargs 2>/dev/null || true)
        fi

        if [ ${#active_services[@]} -eq 0 ] && [ -z "$lock_holders" ]; then
            return 0
        fi

        echo "apt/dpkg is busy. Waiting ${interval}s for package manager locks to clear..."
        if [ ${#active_services[@]} -gt 0 ]; then
            echo "Active package services: ${active_services[*]}"
        fi
        if [ -n "$lock_holders" ]; then
            echo "Lock holder PIDs: $lock_holders"
        fi

        sleep "$interval"
        elapsed=$((elapsed + interval))
    done

    echo "Timed out waiting for apt/dpkg availability after ${timeout}s."
    if [ -n "$lock_holders" ]; then
        ps -fp $lock_holders || true
    fi
    return 1
}

retry_apt_get() {
    wait_for_apt_availability 1800
    retry_command apt-get -o DPkg::Lock::Timeout=600 -o Acquire::Retries=5 "$@"
}

suspend_apt_background_services() {
    if ! command -v systemctl >/dev/null 2>&1; then
        return 0
    fi

    echo "Temporarily suspending automatic apt background services during bootstrap..."
    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl stop apt-daily.timer apt-daily-upgrade.timer || true
    systemctl stop unattended-upgrades.service apt-daily.service apt-daily-upgrade.service || true
    systemctl mask unattended-upgrades.service apt-daily.service apt-daily-upgrade.service >/dev/null 2>&1 || true
    systemctl daemon-reload >/dev/null 2>&1 || true
    APT_BACKGROUND_SUSPENDED=1
    wait_for_apt_availability 600
}

restore_apt_background_services() {
    if [ "${APT_BACKGROUND_SUSPENDED:-0}" -ne 1 ]; then
        return 0
    fi

    if ! command -v systemctl >/dev/null 2>&1; then
        return 0
    fi

    echo "Restoring automatic apt background services..."
    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl unmask unattended-upgrades.service apt-daily.service apt-daily-upgrade.service >/dev/null 2>&1 || true
    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl start apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true
    APT_BACKGROUND_SUSPENDED=0
}

trap 'restore_apt_background_services' EXIT

is_valid_ipv4() {
    local ip="${1:-}"
    local octet=""

    if [[ ! "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
        return 1
    fi

    IFS='.' read -r -a octets <<< "$ip"
    for octet in "${octets[@]}"; do
        if [ "$octet" -lt 0 ] || [ "$octet" -gt 255 ]; then
            return 1
        fi
    done
    return 0
}

# OCI metadata for vnics only exposes privateIp in IMDS v2.
detect_private_access_ip() {
    local detected_ip=""
    local default_iface=""

    detected_ip=$(curl -s -m 5 -H "Authorization: Bearer Oracle" http://169.254.169.254/opc/v2/vnics/ 2>/dev/null | grep -oE '"privateIp"[[:space:]]*:[[:space:]]*"[0-9.]+"' | head -n 1 | cut -d '"' -f 4 || true)
    if is_valid_ipv4 "$detected_ip"; then
        echo "$detected_ip"
        return 0
    fi

    default_iface=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
    if [ -n "$default_iface" ]; then
        detected_ip=$(ip -4 addr show dev "$default_iface" scope global 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | head -n 1)
        if is_valid_ipv4 "$detected_ip"; then
            echo "$detected_ip"
            return 0
        fi
    fi

    detected_ip=$(hostname -I 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i !~ /^127\./ && $i !~ /^169\.254\./) {print $i; exit}}')
    if is_valid_ipv4 "$detected_ip"; then
        echo "$detected_ip"
        return 0
    fi

    return 1
}

detect_public_access_ip() {
    local detected_ip=""
    local vnic_id=""

    # Prefer OCI control-plane query when OCI CLI is available.
    # This avoids NAT egress IP being mistaken as instance public IP.
    if command -v oci >/dev/null 2>&1; then
        vnic_id=$(curl -s -m 5 -H "Authorization: Bearer Oracle" http://169.254.169.254/opc/v2/vnics/ 2>/dev/null | grep -oE '"vnicId"[[:space:]]*:[[:space:]]*"[^"]+"' | head -n 1 | cut -d '"' -f 4 || true)
        if [ -n "$vnic_id" ]; then
            detected_ip=$(oci network vnic get --vnic-id "$vnic_id" --auth instance_principal --query 'data."public-ip"' --raw-output 2>/dev/null | tr -d '[:space:]' || true)
            if is_valid_ipv4 "$detected_ip"; then
                echo "$detected_ip"
                return 0
            fi
        fi
    fi

    detected_ip=$(curl -s -m 10 http://whatismyip.akamai.com/ 2>/dev/null || true)
    if is_valid_ipv4 "$detected_ip"; then
        echo "$detected_ip"
        return 0
    fi

    return 1
}

# Detect access IP for URL generation.
# true  (private subnet)  -> use private IP.
# false (public subnet)   -> use public IP.
# auto                    -> best effort: public first, then private.
detect_access_ip() {
    local detected_ip=""

    if [ "$COMPUTE_SUBNET_PRIVATE" = "true" ]; then
        detected_ip=$(detect_private_access_ip || true)
        if is_valid_ipv4 "$detected_ip"; then
            echo "$detected_ip"
            return 0
        fi
    elif [ "$COMPUTE_SUBNET_PRIVATE" = "false" ]; then
        detected_ip=$(detect_public_access_ip || true)
        if is_valid_ipv4 "$detected_ip"; then
            echo "$detected_ip"
            return 0
        fi

        detected_ip=$(detect_private_access_ip || true)
        if is_valid_ipv4 "$detected_ip"; then
            echo "$detected_ip"
            return 0
        fi
    else
        # Unknown subnet mode: prefer private IP to avoid NAT egress IP false positives.
        detected_ip=$(detect_private_access_ip || true)
        if is_valid_ipv4 "$detected_ip"; then
            echo "$detected_ip"
            return 0
        fi

        detected_ip=$(detect_public_access_ip || true)
        if is_valid_ipv4 "$detected_ip"; then
            echo "$detected_ip"
            return 0
        fi
    fi

    echo "localhost"
    return 1
}

cd "$INSTALL_DIR"

export DEBIAN_FRONTEND=noninteractive
suspend_apt_background_services

# Install essential dependencies
echo "必須の依存関係をインストール中..."
retry_apt_get update -y
retry_apt_get install -y \
    curl \
    wget \
    unzip \
    git \
    build-essential \
    ca-certificates \
    gnupg \
    nginx \
    libreoffice \
    poppler-utils \
    fonts-ipafont-gothic \
    fonts-ipafont-mincho \
    fonts-noto-cjk \
    fonts-noto-cjk-extra \
    fonts-ipafont \
    fonts-takao \
    fonts-wqy-microhei \
    fonts-wqy-zenhei

# フォントキャッシュを更新
echo "フォントキャッシュを更新中..."
fc-cache -fv

# 日本語フォントの検証（TXT/MD変換に必要）
echo "日本語フォントを検証中..."
REQUIRED_FONTS=(
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf:fonts-ipafont-gothic"
    "/usr/share/fonts/truetype/takao-gothic/TakaoGothic.ttf:fonts-takao"
)

FONT_FOUND=false
for font_info in "${REQUIRED_FONTS[@]}"; do
    font_path="${font_info%%:*}"
    package_name="${font_info##*:}"
    if [ -f "$font_path" ]; then
        echo "✓ 日本語フォント検証成功: $font_path"
        FONT_FOUND=true
        break
    fi
done

if [ "$FONT_FOUND" = "false" ]; then
    echo "警告: 推奨される日本語フォントが見つかりません。TXT/MD変換で日本語が正しく表示されない可能性があります。"
    echo "  以下のコマンドでインストールしてください:"
    echo "  apt-get install -y fonts-ipafont-gothic fonts-takao"
fi

# Install Node.js
echo "Node.js $NODE_VERSION LTS をインストール中..."
if ! command -v node >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION} | bash -
    retry_apt_get update -y
    retry_apt_get install -y nodejs
else
    echo "Node.jsは既にインストールされています。"
fi

# Verify Node.js and npm
echo "Node.jsとnpmのインストールを検証中..."
node -v
if ! command -v npm >/dev/null 2>&1; then
    echo "npmが見つかりません。明示的にインストール中..."
    retry_apt_get install -y npm
fi
npm -v

# Install uv (Python package manager)
echo "uv（Pythonパッケージマネージャー）をインストール中..."
if [ ! -f "/root/.local/bin/uv" ]; then
    retry_command curl -LsSf https://astral.sh/uv/install.sh | sh
else
    echo "uvは既にインストールされています。"
fi

# Ensure uv is in PATH for current session
export PATH="/root/.local/bin:$PATH"

# Idempotent addition to .bashrc
if ! grep -q 'export PATH="/root/.local/bin:$PATH"' /root/.bashrc; then
    echo 'export PATH="/root/.local/bin:$PATH"' >> /root/.bashrc
fi

# Install Oracle Instant Client
echo "Oracle Instant Clientをインストール中..."
if [ ! -d "${INSTANTCLIENT_DIR}" ]; then
    if [ ! -f "$INSTANTCLIENT_ZIP" ]; then
        retry_command wget "$INSTANTCLIENT_URL" -O "$INSTANTCLIENT_ZIP"
    fi
    unzip -o "$INSTANTCLIENT_ZIP" -d ./
    
    # Install SQL*Plus
    echo "SQL*Plusをインストール中..."
    if [ ! -f "$INSTANTCLIENT_SQLPLUS_ZIP" ]; then
        retry_command wget "$INSTANTCLIENT_SQLPLUS_URL" -O "$INSTANTCLIENT_SQLPLUS_ZIP"
    fi
    unzip -o "$INSTANTCLIENT_SQLPLUS_ZIP" -d ./

    if [ ! -f "$LIBAIO_DEB" ]; then
        retry_command wget "$LIBAIO_URL"
    fi
    dpkg -i "$LIBAIO_DEB" || retry_apt_get install -f -y
    
    sh -c "echo ${INSTANTCLIENT_DIR} > /etc/ld.so.conf.d/oracle-instantclient.conf"
    ldconfig
    
    if ! grep -q "LD_LIBRARY_PATH=${INSTANTCLIENT_DIR}" /etc/profile; then
        echo "export LD_LIBRARY_PATH=${INSTANTCLIENT_DIR}:\$LD_LIBRARY_PATH" >> /etc/profile
        echo "export PATH=${INSTANTCLIENT_DIR}:\$PATH" >> /etc/profile
    fi
else
    echo "Oracle Instant Clientは既にインストールされています。"
fi

restore_apt_background_services

# Safe sourcing of profile
set +eu
source /etc/profile
set -eu
# Explicitly export in case sourcing failed or didn't pick up immediately
export LD_LIBRARY_PATH="${INSTANTCLIENT_DIR}:${LD_LIBRARY_PATH:-}"
export PATH="${INSTANTCLIENT_DIR}:$PATH"

# Verify sqlplus installation
if command -v sqlplus >/dev/null 2>&1; then
    echo "SQL*Plusのインストール検証が成功しました"
else
    echo "エラー: SQL*Plusのインストール検証に失敗しました"
    exit 1
fi

# Setup ADB wallet
WALLET_DIR="${INSTANTCLIENT_DIR}/network/admin"
echo "ADBウォレットをセットアップ中..."
if [ -f "${INSTALL_DIR}/wallet.zip" ]; then
    mkdir -p "${WALLET_DIR}"
    unzip -o "${INSTALL_DIR}/wallet.zip" -d "${WALLET_DIR}"
    
    # 必須ウォレットファイルのチェック（Thin mode用）
    echo "必須ウォレットファイルをチェック中... (Thin mode)"
    REQUIRED_FILES=("cwallet.sso" "ewallet.pem" "sqlnet.ora" "tnsnames.ora")
    MISSING_FILES=()
    
    for file in "${REQUIRED_FILES[@]}"; do
        if [ ! -f "${WALLET_DIR}/${file}" ]; then
            MISSING_FILES+=("$file")
        fi
    done
    
    if [ ${#MISSING_FILES[@]} -gt 0 ]; then
        echo "エラー: 以下の必須ウォレットファイルが見つかりません:"
        for file in "${MISSING_FILES[@]}"; do
            echo "  ⚠️ $file"
        done
        exit 1
    fi
    
    echo "✓ すべての必須ウォレットファイルが確認されました (Thin mode)"
    echo "  - cwallet.sso (自動ログイン)"
    echo "  - ewallet.pem (PEM形式証明書)"
    echo "  - sqlnet.ora (ネットワーク設定)"
    echo "  - tnsnames.ora (接続文字列)"
    
    echo "ADBウォレットのセットアップが完了しました"
else
    echo "警告: ${INSTALL_DIR}/wallet.zip が見つかりません。ウォレットのセットアップをスキップします。"
fi

# Setup no.1-denpyo-toroku-kun project
PROJECT_DIR="${INSTALL_DIR}/no.1-denpyo-toroku-kun"
if [ -d "$PROJECT_DIR" ]; then
    echo "伝票登録くんプロジェクトをセットアップ中..."
    cd "$PROJECT_DIR"
    
    # Make scripts executable
    if [ -d "scripts" ]; then
        chmod +x scripts/*.sh
    fi
    
    # Environment Setup
    # Check for property files before reading
    if [ -f "${INSTALL_DIR}/props/db.env" ]; then
        DB_CONNECTION_STRING=$(cat "${INSTALL_DIR}/props/db.env")
    else
        echo "警告: ${INSTALL_DIR}/props/db.env が見つかりません！"
        DB_CONNECTION_STRING=""
    fi

    if [ -f "${INSTALL_DIR}/props/compartment_id.txt" ]; then
        COMPARTMENT_ID=$(cat "${INSTALL_DIR}/props/compartment_id.txt")
    else
        echo "警告: ${INSTALL_DIR}/props/compartment_id.txt が見つかりません！"
        COMPARTMENT_ID=""
    fi

    cp .env.example .env
    
    if [ -n "$DB_CONNECTION_STRING" ]; then
        sed -i "s|ORACLE_26AI_CONNECTION_STRING=.*|ORACLE_26AI_CONNECTION_STRING=$DB_CONNECTION_STRING|g" .env
    fi
    
    if [ -n "$COMPARTMENT_ID" ]; then
        sed -i "s|OCI_CONFIG_COMPARTMENT=.*|OCI_CONFIG_COMPARTMENT=$COMPARTMENT_ID|g" .env
    fi
    
    ADB_NAME=$(cat "${INSTALL_DIR}/props/adb_name.txt" 2>/dev/null || true)
    
    # Set ADB OCID (if available)
    if [ -f "${INSTALL_DIR}/props/adb_ocid.txt" ]; then
        ADB_OCID=$(cat "${INSTALL_DIR}/props/adb_ocid.txt")
        sed -i "s|ADB_OCID=.*|ADB_OCID=${ADB_OCID}|g" .env
    fi
    
    # Set Oracle Client Library Directory
    sed -i "s|ORACLE_CLIENT_LIB_DIR=.*|ORACLE_CLIENT_LIB_DIR=${INSTANTCLIENT_DIR}|g" .env
    
    # Set OCI Region (from properties or environment)
    if [ -f "${INSTALL_DIR}/props/oci_region.txt" ]; then
        OCI_REGION=$(cat "${INSTALL_DIR}/props/oci_region.txt")
        sed -i "s|OCI_REGION=.*|OCI_REGION=${OCI_REGION}|g" .env
    elif [ -n "${OCI_REGION:-}" ]; then
        sed -i "s|OCI_REGION=.*|OCI_REGION=${OCI_REGION}|g" .env
    fi
    
    # Set OCI Namespace (get from OCI API or properties)
    if [ -f "${INSTALL_DIR}/props/oci_namespace.txt" ]; then
        OCI_NAMESPACE=$(cat "${INSTALL_DIR}/props/oci_namespace.txt")
        sed -i "s|OCI_NAMESPACE=.*|OCI_NAMESPACE=${OCI_NAMESPACE}|g" .env
    fi
    
    # Set OCI Bucket (default or from properties)
    if [ -f "${INSTALL_DIR}/props/oci_bucket.txt" ]; then
        OCI_BUCKET=$(cat "${INSTALL_DIR}/props/oci_bucket.txt")
        sed -i "s|OCI_BUCKET=.*|OCI_BUCKET=${OCI_BUCKET}|g" .env
    fi
    
    # Set Gunicorn bind to port 8080
    sed -i "s|GUNICORN_BIND=.*|GUNICORN_BIND=0.0.0.0:8080|g" .env
    
    # Detect access IP (public subnet: public IP, private subnet: private IP)
    EXTERNAL_IP=$(detect_access_ip || true)
    echo "アクセス用IP: $EXTERNAL_IP"
    
    # Debug Mode
    if grep -q "^LOG_LEVEL=" .env; then
        sed -i "s|^LOG_LEVEL=.*|LOG_LEVEL=INFO|g" .env
    fi

    # Setup backend with Python 3.13
    echo "Python 3.13でバックエンドをセットアップ中..."
    cd "${PROJECT_DIR}"
    
    # Ensure specific python version
    uv python install 3.13
    
    # Create venv and install dependencies
    echo "依存関係をインストール中..."
    uv venv --python 3.13 .venv
    uv pip install -r requirements.txt --python .venv/bin/python
    
    echo "バックエンドのセットアップが完了しました。"
    
    # Setup frontend (Oracle JET)
    echo "フロントエンドをセットアップ中..."
    cd "${PROJECT_DIR}/denpyo_toroku/ui"
    
    # Install npm dependencies if package.json exists
    if [ -f "package.json" ]; then
        echo "npm install を実行中..."
        retry_command npm install --legacy-peer-deps --no-audit --no-fund
        
        echo "本番用フロントエンドをビルド中..."
        npm run build
    fi
    
    cd "${PROJECT_DIR}"
    
    # Configure nginx
    echo "nginxを設定中..."
    cat > /etc/nginx/sites-available/app << 'NGINX_EOF'
server {
    listen 80;
    server_name _;

    # ログ設定
    access_log /var/log/nginx/app.log;
    error_log /var/log/nginx/app-error.log warn;

    # クライアント最大ボディサイズ（アップロード用）
    client_max_body_size 100M;

    # 本アプリのAPI (/ai/api と /ai/api/)
    location /ai/api/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # /ai/api を /ai/api/ にリダイレクト
    location = /ai/api {
        return 301 /ai/api/;
    }

    # 画像プロキシエンドポイント (/oci/image)
    location /oci/image/ {
        proxy_pass http://127.0.0.1:8080/oci/image/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_buffering off;
        # キャッシュ設定（画像用）
        proxy_cache_valid 200 1h;
    }

    # OCI Object Storageプロキシ (/object) - ファイル・画像配信
    location /object/ {
        proxy_pass http://127.0.0.1:8080/object/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_buffering off;
        proxy_cache_valid 200 1h;
    }

    # 後方互換性: /img/ -> /object/
    location /img/ {
        return 307 /object/$request_uri;
    }

    # 本アプリのヘルスチェック
    location /ai/health {
        proxy_pass http://127.0.0.1:8080/studio/api/v1/health;
        proxy_set_header Host $host;
        access_log off;
    }

    # 本アプリのフロントエンド (/ai/ と /ai/xxx)
    location /ai/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    # /ai を /ai/ にリダイレクト
    location = /ai {
        return 301 /ai/;
    }

    # ルートパスは/ai/にリダイレクト
    location = / {
        return 302 /ai/;
    }

    # その他のルートパスも/ai/にリダイレクト
    location / {
        return 302 /ai/;
    }
}
NGINX_EOF

    # サイトを有効化
    ln -sf /etc/nginx/sites-available/app /etc/nginx/sites-enabled/
    
    # デフォルトサイトを無効化・削除
    rm -f /etc/nginx/sites-enabled/default
    rm -f /etc/nginx/sites-available/default
    
    # nginx設定をテスト
    echo "nginx設定をテスト中..."
    nginx -t
    
    # nginxをリロード
    echo "nginxをリロード中..."
    systemctl reload nginx || systemctl restart nginx
    
    # nginx自動起動を有効化
    echo "nginx自動起動を有効化中..."
    systemctl enable nginx
    
    # 完了メッセージ
    EXTERNAL_IP=$(detect_access_ip || true)
    echo "========================================"
    echo "初期化が完了しました。"
    echo "  本アプリ: http://${EXTERNAL_IP}/ai"
    echo "  API:      http://${EXTERNAL_IP}/ai/api"
    echo "  (ルート'/'は/aiにリダイレクトされます)"
    echo "========================================"
fi

# Create startup script
cat > "${INSTALL_DIR}/start_denpyo_toroku_services.sh" << 'EOF'
#!/bin/bash
if [ -f /root/.bashrc ]; then
  source /root/.bashrc
fi

export PATH="/root/.local/bin:$PATH"
cd /u01/aipoc/no.1-denpyo-toroku-kun

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Set TNS_ADMIN for Oracle Wallet
export TNS_ADMIN="${ORACLE_CLIENT_LIB_DIR}/network/admin"

# Set LD_LIBRARY_PATH for Oracle Instant Client
export LD_LIBRARY_PATH="${ORACLE_CLIENT_LIB_DIR}:${LD_LIBRARY_PATH:-}"
export PATH="${ORACLE_CLIENT_LIB_DIR}:$PATH"

echo "伝票登録くんバックエンドサービスを起動中..."
# Gunicornで起動 (gunicorn_config.py にbind/chdir/wsgi_app設定あり)
nohup .venv/bin/gunicorn -c gunicorn_config/gunicorn_config.py > /var/log/app-backend.log 2>&1 &

sleep 5

echo "伝票登録くんサービスが起動しました。"
EOF

chmod +x "${INSTALL_DIR}/start_denpyo_toroku_services.sh"

# Cron job (Idempotent)
echo "cronジョブをセットアップ中..."
CRON_CMD="@reboot ${INSTALL_DIR}/start_denpyo_toroku_services.sh"
(crontab -l 2>/dev/null | grep -v "$CRON_CMD" || true; echo "$CRON_CMD") | crontab -

# Start services
echo "伝票登録くんサービスを起動中..."
"${INSTALL_DIR}/start_denpyo_toroku_services.sh"

echo "初期化が完了しました。"
