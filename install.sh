#!/usr/bin/env bash
#
# Madis SIP Proxy — Linux installer
# Supports Debian/Ubuntu and RHEL/CentOS/Fedora/Rocky/AlmaLinux
#
set -euo pipefail

# ── defaults (override with env vars before running) ─────────────────────────
MADIS_DB_NAME="${MADIS_DB_NAME:-madis}"
MADIS_DB_USER="${MADIS_DB_USER:-madis}"
MADIS_DB_PASS="${MADIS_DB_PASS:-}"
MADIS_INSTALL_DIR="${MADIS_INSTALL_DIR:-/opt/madis}"
MADIS_CONF_DIR="${MADIS_CONF_DIR:-/etc/madis}"
MADIS_LOG_DIR="${MADIS_LOG_DIR:-/var/log/madis}"
MADIS_USER="${MADIS_USER:-madis}"
MADIS_SIP_PORT="${MADIS_SIP_PORT:-5060}"
MADIS_TLS_PORT="${MADIS_TLS_PORT:-5061}"
MADIS_WSS_PORT="${MADIS_WSS_PORT:-8443}"
MADIS_ADMIN_PORT="${MADIS_ADMIN_PORT:-8080}"
MADIS_SIP_ADMIN_PORT="${MADIS_SIP_ADMIN_PORT:-9090}"
MADIS_ADMIN_TOKEN="${MADIS_ADMIN_TOKEN:-}"
MADIS_CARRIER_API_TOKEN="${MADIS_CARRIER_API_TOKEN:-}"
MADIS_CONTROL_API_TOKEN="${MADIS_CONTROL_API_TOKEN:-}"
MADIS_CONTROL_API_READ_TOKEN="${MADIS_CONTROL_API_READ_TOKEN:-}"
MADIS_APP_TOKEN="${MADIS_APP_TOKEN:-}"
MADIS_MODULE_TOKEN="${MADIS_MODULE_TOKEN:-}"
MADIS_ADMIN_PASSWORD="${MADIS_ADMIN_PASSWORD:-}"
MADIS_VERSION="${MADIS_VERSION:-}"
MADIS_MAKO_VERSION="0.4.16"
MADIS_CLI_DIR="${MADIS_CLI_DIR:-/usr/local/bin}"

# ── colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[madis]${NC} $1"; }
warn()  { echo -e "${YELLOW}[madis]${NC} $1"; }
fail()  { echo -e "${RED}[madis]${NC} $1"; exit 1; }

# ── preflight ────────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || fail "Please run as root (sudo $0)"

detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO_ID="${ID}"
        DISTRO_FAMILY="${ID_LIKE:-$ID}"
    elif [ -f /etc/redhat-release ]; then
        DISTRO_ID="rhel"
        DISTRO_FAMILY="rhel"
    elif [ -f /etc/debian_version ]; then
        DISTRO_ID="debian"
        DISTRO_FAMILY="debian"
    else
        fail "Could not detect Linux distribution."
    fi
}

detect_distro

is_debian() {
    [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "ubuntu" || \
       "$DISTRO_ID" == "linuxmint" || "$DISTRO_FAMILY" == *"debian"* ]]
}

is_rhel() {
    [[ "$DISTRO_ID" == "rhel" || "$DISTRO_ID" == "centos" || \
       "$DISTRO_ID" == "fedora" || "$DISTRO_ID" == "rocky" || \
       "$DISTRO_ID" == "almalinux" || "$DISTRO_FAMILY" == *"rhel"* || \
       "$DISTRO_FAMILY" == *"fedora"* ]]
}

if is_debian; then
    info "Detected Debian-based system ($DISTRO_ID)"
elif is_rhel; then
    info "Detected RHEL-based system ($DISTRO_ID)"
else
    fail "Unsupported distribution: $DISTRO_ID"
fi

# ── generate db password if not provided ─────────────────────────────────────
if [ -z "$MADIS_DB_PASS" ]; then
    MADIS_DB_PASS=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24 || true)
    info "Generated database password."
fi

if [ -z "$MADIS_ADMIN_TOKEN" ]; then
    MADIS_ADMIN_TOKEN=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32 || true)
    info "Generated admin API token."
fi

if [ -z "$MADIS_CARRIER_API_TOKEN" ]; then
    MADIS_CARRIER_API_TOKEN=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 48 || true)
    info "Generated carrier integration API token."
fi

if [ -z "$MADIS_CONTROL_API_TOKEN" ]; then
    MADIS_CONTROL_API_TOKEN=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 48 || true)
    info "Generated control API token."
fi

if [ -z "$MADIS_CONTROL_API_READ_TOKEN" ]; then
    MADIS_CONTROL_API_READ_TOKEN=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 48 || true)
    info "Generated read-only control API token."
fi

if [ -z "$MADIS_APP_TOKEN" ]; then
    MADIS_APP_TOKEN=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 48 || true)
    info "Generated SIP application gateway token."
fi

if [ -z "$MADIS_MODULE_TOKEN" ]; then
    MADIS_MODULE_TOKEN=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 48 || true)
    info "Generated external module bus token."
fi

if [ -z "$MADIS_ADMIN_PASSWORD" ]; then
    MADIS_ADMIN_PASSWORD=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24 || true)
    info "Generated WebUI admin password."
fi

if [ "$MADIS_SIP_ADMIN_PORT" = "$MADIS_ADMIN_PORT" ]; then
    fail "MADIS_SIP_ADMIN_PORT and MADIS_ADMIN_PORT must be different"
fi

# ── detect public IP (GCP, AWS, Azure, or bare metal) ────────────────────────
detect_public_ip() {
    local pub_ip=""

    # GCP metadata
    pub_ip=$(curl -sf -m 3 -H "Metadata-Flavor: Google" \
        "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip" 2>/dev/null || true)
    if [ -n "$pub_ip" ]; then
        CLOUD_PROVIDER="GCP"
        echo "$pub_ip"
        return
    fi

    # AWS EC2 metadata (IMDSv2)
    local token
    token=$(curl -sf -m 2 -X PUT -H "X-aws-ec2-metadata-token-ttl-seconds: 60" \
        "http://169.254.169.254/latest/api/token" 2>/dev/null || true)
    if [ -n "$token" ]; then
        pub_ip=$(curl -sf -m 2 -H "X-aws-ec2-metadata-token: $token" \
            "http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null || true)
        if [ -n "$pub_ip" ]; then
            CLOUD_PROVIDER="AWS"
            echo "$pub_ip"
            return
        fi
    fi

    # Azure IMDS
    pub_ip=$(curl -sf -m 3 -H "Metadata: true" \
        "http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01&format=text" 2>/dev/null || true)
    if [ -n "$pub_ip" ]; then
        CLOUD_PROVIDER="Azure"
        echo "$pub_ip"
        return
    fi

    # Fallback: external lookup
    pub_ip=$(curl -sf -m 5 https://ifconfig.me 2>/dev/null || curl -sf -m 5 https://api.ipify.org 2>/dev/null || true)
    if [ -n "$pub_ip" ]; then
        CLOUD_PROVIDER="unknown"
        echo "$pub_ip"
        return
    fi
}

CLOUD_PROVIDER="bare-metal"
MADIS_PUBLIC_IP="${MADIS_PUBLIC_IP:-}"
if [ -z "$MADIS_PUBLIC_IP" ]; then
    MADIS_PUBLIC_IP=$(detect_public_ip)
fi

# Detect the private/bind IP
MADIS_PRIVATE_IP="${MADIS_PRIVATE_IP:-}"
if [ -z "$MADIS_PRIVATE_IP" ]; then
    MADIS_PRIVATE_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "0.0.0.0")
fi

if [ -n "$MADIS_PUBLIC_IP" ] && [ "$MADIS_PUBLIC_IP" != "$MADIS_PRIVATE_IP" ]; then
    info "Cloud/NAT detected ($CLOUD_PROVIDER)"
    info "  Private IP: $MADIS_PRIVATE_IP (bind address)"
    info "  Public IP:  $MADIS_PUBLIC_IP (SIP/SDP headers)"
else
    info "Public IP: ${MADIS_PUBLIC_IP:-not detected}"
fi

# ── install system packages ──────────────────────────────────────────────────
info "Installing system dependencies..."

if is_debian; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq \
        postgresql postgresql-client \
        build-essential gcc make \
        libssl-dev libpq-dev \
        curl wget git \
        net-tools \
        logrotate \
        > /dev/null 2>&1
elif is_rhel; then
    if command -v dnf &> /dev/null; then
        PKG_MGR="dnf"
    else
        PKG_MGR="yum"
    fi
    $PKG_MGR install -y -q \
        postgresql-server postgresql \
        gcc make \
        openssl-devel libpq-devel \
        curl wget git \
        net-tools \
        logrotate \
        > /dev/null 2>&1
fi

info "System packages installed."

# ── start and configure postgresql ───────────────────────────────────────────
info "Setting up PostgreSQL..."

if is_debian; then
    systemctl enable postgresql > /dev/null 2>&1
    systemctl start postgresql
elif is_rhel; then
    # RHEL-family needs initdb before first start
    if [ ! -f /var/lib/pgsql/data/PG_VERSION ]; then
        postgresql-setup --initdb 2>/dev/null || postgresql-setup initdb 2>/dev/null || true
    fi
    # allow md5 auth for local connections
    PG_HBA=$(find /var/lib/pgsql -name pg_hba.conf 2>/dev/null | head -1)
    if [ -n "$PG_HBA" ]; then
        if grep -q "ident" "$PG_HBA"; then
            sed -i 's/^\(host.*all.*all.*\)ident/\1md5/' "$PG_HBA"
            sed -i 's/^\(local.*all.*all.*\)peer/\1md5/' "$PG_HBA"
        fi
    fi
    systemctl enable postgresql > /dev/null 2>&1
    systemctl start postgresql
fi

# wait for postgres to be ready
for i in $(seq 1 10); do
    if su - postgres -c "psql -c 'SELECT 1'" > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# create db user and database
su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='$MADIS_DB_USER'\"" | grep -q 1 || \
    su - postgres -c "psql -c \"CREATE USER $MADIS_DB_USER WITH PASSWORD '$MADIS_DB_PASS';\""

su - postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='$MADIS_DB_NAME'\"" | grep -q 1 || \
    su - postgres -c "psql -c \"CREATE DATABASE $MADIS_DB_NAME OWNER $MADIS_DB_USER;\""

su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE $MADIS_DB_NAME TO $MADIS_DB_USER;\""

info "PostgreSQL database '$MADIS_DB_NAME' ready."

# ── create database schema ───────────────────────────────────────────────────
info "Creating database schema..."

PGPASSWORD="$MADIS_DB_PASS" psql -h 127.0.0.1 -U "$MADIS_DB_USER" -d "$MADIS_DB_NAME" -q <<'SCHEMA'

-- SIP users and authentication
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    password_ha1    TEXT NOT NULL,
    password_ha1_sha256 TEXT DEFAULT '',
    domain          TEXT DEFAULT 'mako.local',
    display_name    TEXT,
    email           TEXT,
    max_contacts    INT DEFAULT 5,
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMP DEFAULT NOW()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS password_ha1_sha256 TEXT DEFAULT '';

-- IP-based authentication (carriers, trunks)
CREATE TABLE IF NOT EXISTS ip_auth (
    id              SERIAL PRIMARY KEY,
    ip_address      TEXT UNIQUE NOT NULL,
    description     TEXT,
    tenant          TEXT DEFAULT 'default',
    account_id      INT,
    max_channels    INT DEFAULT 100,
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Access control lists
CREATE TABLE IF NOT EXISTS access_control (
    id              SERIAL PRIMARY KEY,
    source_ip       TEXT DEFAULT '*',
    sip_user        TEXT DEFAULT '*',
    action          TEXT DEFAULT 'allow',
    skip_auth       BOOLEAN DEFAULT false,
    tenant          TEXT DEFAULT 'default',
    max_channels    INT DEFAULT 0,
    priority        INT DEFAULT 10,
    enabled         BOOLEAN DEFAULT true,
    description     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Legacy ACL table retained only to migrate older installations.
CREATE TABLE IF NOT EXISTS acl (
    id              SERIAL PRIMARY KEY,
    source_ip       TEXT DEFAULT '*',
    sip_user        TEXT DEFAULT '*',
    action          TEXT DEFAULT 'allow',
    priority        INT DEFAULT 10,
    description     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS madis_schema_migrations (
    key             TEXT PRIMARY KEY,
    applied_at      TIMESTAMP DEFAULT NOW()
);
INSERT INTO access_control (source_ip, sip_user, action, priority, description)
SELECT source_ip, sip_user, action, priority, description FROM acl
WHERE NOT EXISTS (SELECT 1 FROM madis_schema_migrations WHERE key = 'acl-to-access-control')
  AND NOT EXISTS (SELECT 1 FROM access_control);
INSERT INTO madis_schema_migrations (key) VALUES ('acl-to-access-control') ON CONFLICT DO NOTHING;

-- Registrations (legacy single-binding table)
CREATE TABLE IF NOT EXISTS registrations (
    aor             TEXT PRIMARY KEY,
    contact         TEXT NOT NULL,
    transport       TEXT DEFAULT 'UDP',
    node_id         TEXT DEFAULT '',
    user_agent      TEXT,
    updated_at      TIMESTAMP DEFAULT NOW(),
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Registration bindings (multi-contact)
CREATE TABLE IF NOT EXISTS registration_bindings (
    id              SERIAL PRIMARY KEY,
    aor             TEXT NOT NULL,
    contact         TEXT NOT NULL,
    transport       TEXT DEFAULT 'UDP',
    node_id         TEXT DEFAULT '',
    source_ip       TEXT DEFAULT '',
    source_port     INT DEFAULT 0,
    expires_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(aor, contact)
);

-- Gateways
CREATE TABLE IF NOT EXISTS gateways (
    id              SERIAL PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,
    address         TEXT NOT NULL,
    port            INT DEFAULT 5060,
    transport       TEXT DEFAULT 'UDP',
    auth_user       TEXT,
    auth_pass       TEXT,
    caller_id       TEXT,
    max_channels    INT DEFAULT 100,
    number_format   TEXT DEFAULT 'e164',
    tech_prefix     TEXT DEFAULT '',
    caller_id_override TEXT DEFAULT '',
    health_status   TEXT DEFAULT 'unknown',
    last_health_code INT DEFAULT 0,
    last_health_check TIMESTAMP,
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Dispatch sets (load balancing groups)
CREATE TABLE IF NOT EXISTS dispatch_sets (
    id              SERIAL PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,
    algorithm       TEXT DEFAULT 'round-robin',
    description     TEXT,
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Dispatch members
CREATE TABLE IF NOT EXISTS dispatch_members (
    id              SERIAL PRIMARY KEY,
    set_id          INT NOT NULL,
    gateway_id      INT NOT NULL,
    priority        INT DEFAULT 10,
    weight          INT DEFAULT 100,
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Routes
CREATE TABLE IF NOT EXISTS routes (
    id              SERIAL PRIMARY KEY,
    prefix          TEXT NOT NULL,
    gateway_id      INT,
    dispatch_set_id INT,
    priority        INT DEFAULT 10,
    weight          INT DEFAULT 100,
    cost_per_min    NUMERIC(8,4) DEFAULT 0,
    time_start      TIME DEFAULT '00:00',
    time_end        TIME DEFAULT '23:59',
    enabled         BOOLEAN DEFAULT true,
    description     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Routing rules
CREATE TABLE IF NOT EXISTS routing_rules (
    id              SERIAL PRIMARY KEY,
    match_prefix    TEXT DEFAULT '',
    match_caller    TEXT DEFAULT '',
    match_src_ip    TEXT DEFAULT '',
    match_time_start TEXT DEFAULT '',
    match_time_end  TEXT DEFAULT '',
    match_day       TEXT DEFAULT '',
    match_ani_group TEXT DEFAULT '',
    action          TEXT NOT NULL,
    priority        INT DEFAULT 10,
    enabled         BOOLEAN DEFAULT true,
    description     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ani_groups (
    id              SERIAL PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,
    description     TEXT DEFAULT '',
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ani_ranges (
    id              SERIAL PRIMARY KEY,
    group_id        INT NOT NULL,
    range_start     TEXT NOT NULL,
    range_end       TEXT NOT NULL,
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- DIDs (inbound numbers)
CREATE TABLE IF NOT EXISTS dids (
    id              SERIAL PRIMARY KEY,
    number          TEXT UNIQUE NOT NULL,
    destination_user TEXT NOT NULL,
    description     TEXT,
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Dial plan
CREATE TABLE IF NOT EXISTS dialplan (
    id              SERIAL PRIMARY KEY,
    match_prefix    TEXT NOT NULL,
    callee_action   TEXT NOT NULL DEFAULT '',
    caller_action   TEXT DEFAULT '',
    direction       TEXT DEFAULT 'outbound',
    priority        INT DEFAULT 10,
    enabled         BOOLEAN DEFAULT true,
    description     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Call detail records
CREATE TABLE IF NOT EXISTS cdr (
    call_id         TEXT PRIMARY KEY,
    caller          TEXT,
    callee          TEXT,
    status          TEXT,
    gateway         TEXT,
    source_ip       TEXT,
    destination     TEXT,
    transport       TEXT,
    from_uri        TEXT,
    to_uri          TEXT,
    user_agent      TEXT,
    sip_code        INT,
    started_at      TIMESTAMP DEFAULT NOW(),
    ended_at        TIMESTAMP,
    duration_sec    INT
);

-- Versioned, idempotent billing/charging outbox. payload_json is deliberately
-- extensible: carrier applications own the data/schema inside the envelope.
CREATE TABLE IF NOT EXISTS billing_events (
    event_id        TEXT PRIMARY KEY,
    call_id         TEXT NOT NULL DEFAULT '',
    event_type      TEXT NOT NULL,
    payload_json    JSONB NOT NULL,
    occurred_at     TIMESTAMP DEFAULT NOW(),
    available_at    TIMESTAMP DEFAULT NOW(),
    delivered_at    TIMESTAMP,
    attempts        INT NOT NULL DEFAULT 0,
    last_error      TEXT NOT NULL DEFAULT '',
    CONSTRAINT billing_event_id_size CHECK (char_length(event_id) BETWEEN 16 AND 128),
    CONSTRAINT billing_event_payload_size CHECK (octet_length(payload_json::text) <= 65536)
);

CREATE INDEX IF NOT EXISTS idx_billing_events_pending ON billing_events (occurred_at, event_id) WHERE delivered_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_billing_events_call ON billing_events (call_id, occurred_at);

-- SIP transaction log
CREATE TABLE IF NOT EXISTS sip_transactions (
    id              SERIAL PRIMARY KEY,
    call_id         TEXT,
    direction       TEXT,
    method          TEXT,
    source          TEXT,
    ts              TIMESTAMP DEFAULT NOW()
);

-- Header manipulation rules
CREATE TABLE IF NOT EXISTS header_rules (
    id              SERIAL PRIMARY KEY,
    match_method    TEXT DEFAULT '*',
    match_direction TEXT DEFAULT 'outbound',
    action          TEXT NOT NULL,
    header_name     TEXT NOT NULL,
    header_value    TEXT DEFAULT '',
    priority        INT DEFAULT 10,
    enabled         BOOLEAN DEFAULT true,
    description     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Cluster nodes
CREATE TABLE IF NOT EXISTS cluster_nodes (
    id              TEXT PRIMARY KEY,
    address         TEXT NOT NULL,
    port            INT DEFAULT 5060,
    region          TEXT DEFAULT 'default',
    weight          INT DEFAULT 100,
    status          TEXT DEFAULT 'active',
    last_heartbeat  TIMESTAMP DEFAULT NOW(),
    started_at      TIMESTAMP DEFAULT NOW()
);

-- Configuration key/value store
CREATE TABLE IF NOT EXISTS config (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    description     TEXT
);

-- Security: ban list
CREATE TABLE IF NOT EXISTS security_bans (
    source_ip       TEXT PRIMARY KEY,
    reason          TEXT DEFAULT '',
    ban_count       INT DEFAULT 1,
    expires_at      TIMESTAMP,
    permanent       BOOLEAN DEFAULT false,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Security: event log
CREATE TABLE IF NOT EXISTS security_events (
    id              SERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    source_ip       TEXT DEFAULT '',
    sip_user        TEXT DEFAULT '',
    severity        TEXT DEFAULT 'low',
    details         TEXT DEFAULT '',
    ts              TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_reg_bindings_aor_exp ON registration_bindings (aor, expires_at);
CREATE INDEX IF NOT EXISTS idx_routes_pfx ON routes (prefix, enabled);
CREATE INDEX IF NOT EXISTS idx_dids_num ON dids (number) WHERE enabled = true;
CREATE INDEX IF NOT EXISTS idx_acl_ip ON access_control (source_ip);
CREATE INDEX IF NOT EXISTS idx_cdr_time ON cdr (started_at);
CREATE INDEX IF NOT EXISTS idx_users_name ON users (username) WHERE enabled = true;
CREATE INDEX IF NOT EXISTS idx_ipauth_ip ON ip_auth (ip_address) WHERE enabled = true;
CREATE INDEX IF NOT EXISTS idx_routing_rules_pri ON routing_rules (priority) WHERE enabled = true;
CREATE INDEX IF NOT EXISTS idx_security_events_ip_ts ON security_events (source_ip, ts);

-- Default config values
INSERT INTO config (key, value, description) VALUES
    ('stir_shaken_enabled', 'false', 'Enable STIR/SHAKEN'),
    ('stir_shaken_attestation', 'A', 'Default attestation level A/B/C'),
    ('stir_shaken_cert_url', '', 'STI certificate URL (x5u)'),
    ('stir_shaken_mode', 'auto', 'Verify mode: auto|hs256|rs256|jwks'),
    ('stir_shaken_secret', '', 'HS256 secret (lab sign/verify)'),
    ('stir_shaken_private_key', '', 'ES256 private key PEM/path for production signing'),
    ('stir_shaken_public_key', '', 'RS256 public key PEM path or inline'),
    ('stir_shaken_jwks', '', 'JWKS JSON path or inline'),
    ('stir_shaken_jwks_url', '', 'JWKS HTTPS URL'),
    ('security_enabled', 'true', 'Enable SIP security controls'),
    ('security_max_auth_failures', '5', 'Auth failures before temporary ban'),
    ('security_ban_duration_min', '30', 'Temporary ban duration in minutes')
ON CONFLICT DO NOTHING;

SCHEMA

info "Database schema created."

# ── create system user ───────────────────────────────────────────────────────
if ! id "$MADIS_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$MADIS_USER"
    info "Created system user '$MADIS_USER'."
fi

# ── create directories ───────────────────────────────────────────────────────
mkdir -p "$MADIS_INSTALL_DIR"
mkdir -p "$MADIS_CONF_DIR"
mkdir -p "$MADIS_LOG_DIR"

# ── copy source files ────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "$MADIS_VERSION" ] && [ -r "$SCRIPT_DIR/VERSION" ]; then
    MADIS_VERSION=$(tr -d '[:space:]' < "$SCRIPT_DIR/VERSION")
fi
MADIS_VERSION="${MADIS_VERSION:-0.1.0}"

info "Copying source files to $MADIS_INSTALL_DIR..."
cp "$SCRIPT_DIR"/*.mko "$MADIS_INSTALL_DIR/" 2>/dev/null || true
if [ -f "$SCRIPT_DIR/madis_memory.c" ]; then
    cp "$SCRIPT_DIR/madis_memory.c" "$MADIS_INSTALL_DIR/madis_memory.c"
fi
for support_dir in api sdk; do
    if [ -d "$SCRIPT_DIR/$support_dir" ]; then
        cp -r "$SCRIPT_DIR/$support_dir" "$MADIS_INSTALL_DIR/"
    fi
done
if [ -d "$SCRIPT_DIR/tests" ]; then
    cp -r "$SCRIPT_DIR/tests" "$MADIS_INSTALL_DIR/"
fi
if [ -d "$SCRIPT_DIR/admin" ]; then
    mkdir -p "$MADIS_INSTALL_DIR/admin"
    cp -r "$SCRIPT_DIR/admin/." "$MADIS_INSTALL_DIR/admin/"
    info "Installed Mako SIP WebUI source."
fi
if [ -f "$SCRIPT_DIR/VERSION" ]; then
    cp "$SCRIPT_DIR/VERSION" "$MADIS_INSTALL_DIR/VERSION"
fi

if [ -f "$SCRIPT_DIR/scripts/madis" ]; then
    install -d "$MADIS_CLI_DIR"
    install -m 0755 "$SCRIPT_DIR/scripts/madis" "$MADIS_CLI_DIR/madis"
    ln -sf madis "$MADIS_CLI_DIR/madisctl"
    info "Installed madis CLI as $MADIS_CLI_DIR/madis (and madisctl)."
fi

# If a pre-built binary exists, copy that too. Otherwise build the SIP worker
# from emitted C so the external Mako 0.4.16 ownership bridge is linked.
if [ -f "$SCRIPT_DIR/main" ]; then
    cp "$SCRIPT_DIR/main" "$MADIS_INSTALL_DIR/madis"
    chmod +x "$MADIS_INSTALL_DIR/madis"
    info "Installed pre-built binary."
elif [ -f "$MADIS_INSTALL_DIR/main.mko" ]; then
    MADIS_MAKO_BIN="${MADIS_MAKO_BIN:-mako}"
    if ! command -v "$MADIS_MAKO_BIN" >/dev/null 2>&1; then
        fail "Mako 0.4.16 is required to build the SIP worker; install it or provide MADIS_MAKO_BIN."
    fi
    MAKO_VERSION_TEXT=$($MADIS_MAKO_BIN --version 2>/dev/null || true)
    [[ "$MAKO_VERSION_TEXT" == *"0.4.16"* ]] || fail "Mako 0.4.16 is required (found: ${MAKO_VERSION_TEXT:-unknown})."
    MADIS_MAKO_RUNTIME="${MAKO_RUNTIME:-/usr/local/share/mako/runtime}"
    [ -d "$MADIS_MAKO_RUNTIME" ] || fail "Mako runtime not found at $MADIS_MAKO_RUNTIME; set MAKO_RUNTIME."
    info "Building Madis SIP worker with Mako 0.4.16..."
    rm -f "$MADIS_INSTALL_DIR/main.c"
    emit_log="$MADIS_INSTALL_DIR/mako-build.log"
    if ! (cd "$MADIS_INSTALL_DIR" && MAKO_RUNTIME="$MADIS_MAKO_RUNTIME" "$MADIS_MAKO_BIN" \
        build --emit-c --release --strip --no-incremental main.mko -o .mako-ignored >"$emit_log" 2>&1); then
        [ -s "$MADIS_INSTALL_DIR/main.c" ] || { cat "$emit_log" >&2; fail "Mako C emission failed."; }
    fi
    cc -std=c11 -O3 -DNDEBUG -w \
        -I"$MADIS_MAKO_RUNTIME" -I/usr/include/postgresql \
        -DMAKO_HAS_OPENSSL -DMAKO_USE_OPENSSL -DMAKO_HAS_LIBPQ \
        "$MADIS_INSTALL_DIR/main.c" "$MADIS_INSTALL_DIR/madis_memory.c" \
        -o "$MADIS_INSTALL_DIR/madis" -pthread -lm -ldl -lresolv -lssl -lcrypto -lpq
    chmod +x "$MADIS_INSTALL_DIR/madis"
    rm -f "$MADIS_INSTALL_DIR/main.c" "$MADIS_INSTALL_DIR/.mako-ignored" "$emit_log"
    info "Built Madis SIP worker."
fi

# Build the standalone WebUI when Mako is available. A pre-built admin-bin
# remains supported for offline/production packaging.
if [ -f "$SCRIPT_DIR/admin-bin" ]; then
    cp "$SCRIPT_DIR/admin-bin" "$MADIS_INSTALL_DIR/admin-bin"
    chmod +x "$MADIS_INSTALL_DIR/admin-bin"
    info "Installed pre-built WebUI binary."
elif [ -f "$MADIS_INSTALL_DIR/admin/main.mko" ]; then
    MADIS_MAKO_BIN="${MADIS_MAKO_BIN:-mako}"
    if command -v "$MADIS_MAKO_BIN" >/dev/null 2>&1; then
        MAKO_VERSION_TEXT=$("$MADIS_MAKO_BIN" --version 2>/dev/null || true)
        if [[ "$MAKO_VERSION_TEXT" != *"0.4.16"* ]]; then
            fail "Mako 0.4.16 is required to build the WebUI (found: ${MAKO_VERSION_TEXT:-unknown})."
        fi
        info "Building Mako SIP WebUI with ${MADIS_MAKO_BIN}..."
        if [ -n "${MAKO_RUNTIME:-}" ]; then
            (cd "$MADIS_INSTALL_DIR" && MAKO_RUNTIME="$MAKO_RUNTIME" "$MADIS_MAKO_BIN" \
                build --release --strip --no-incremental admin/main.mko -o admin-bin)
        else
            (cd "$MADIS_INSTALL_DIR" && "$MADIS_MAKO_BIN" \
                build --release --strip --no-incremental admin/main.mko -o admin-bin)
        fi
        chmod +x "$MADIS_INSTALL_DIR/admin-bin"
        info "Built WebUI binary."
    else
        warn "Mako compiler not found; WebUI source was installed but admin-bin was not built."
        warn "Install Mako 0.4.16 or set MADIS_MAKO_BIN, then build admin/main.mko."
    fi
fi

# ── write environment file ───────────────────────────────────────────────────
cat > "$MADIS_CONF_DIR/madis.env" <<EOF
# Madis SIP Proxy configuration
MADIS_VERSION=${MADIS_VERSION}
MADIS_MAKO_VERSION=${MADIS_MAKO_VERSION}
MADIS_INSTALL_DIR=${MADIS_INSTALL_DIR}
# Database
SIP_DB_URL=postgres://${MADIS_DB_USER}:${MADIS_DB_PASS}@127.0.0.1:5432/${MADIS_DB_NAME}

# Network
SIP_UDP_PORT=${MADIS_SIP_PORT}
SIP_TLS_PORT=${MADIS_TLS_PORT}
SIP_WSS_PORT=${MADIS_WSS_PORT}
# The WebUI uses the SIP worker's internal control plane for live metrics.
SIP_ADMIN_PORT=${MADIS_SIP_ADMIN_PORT}
SIP_METRICS_HOST=127.0.0.1
SIP_METRICS_PORT=${MADIS_SIP_ADMIN_PORT}
SIP_ADMIN_PASSWORD=${MADIS_ADMIN_PASSWORD}
SIP_BIND_IP=${MADIS_PRIVATE_IP:-0.0.0.0}
SIP_PUBLIC_IP=${MADIS_PUBLIC_IP:-}
SIP_IPV6=1

# Identity
SIP_REALM=madis.local
SIP_NODE_ID=node1
SIP_NODE_ADDR=127.0.0.1
SIP_REGION=default

# Workers
SIP_UDP_WORKERS=1
SIP_TCP_WORKERS=1
# Optional fixed Mako crew/kick pool; 0 keeps one pthread per kicked listener.
SIP_SCHED_WORKERS=0

# B2BUA is opt-in. Ordinary routing remains proxy behavior.
SIP_B2BUA_MODE=proxy
# SIP_B2BUA_STATE_MS=1800000
# SIP_B2BUA_CALLID_HOST=madis.local

# Auth
SIP_DIGEST_ALGORITHM=md5
SIP_ADMIN_TOKEN=${MADIS_ADMIN_TOKEN}
SIP_CARRIER_API_TOKEN=${MADIS_CARRIER_API_TOKEN}
SIP_CONTROL_API_TOKEN=${MADIS_CONTROL_API_TOKEN}
SIP_CONTROL_API_READ_TOKEN=${MADIS_CONTROL_API_READ_TOKEN}
SIP_APP_TOKEN=${MADIS_APP_TOKEN}
SIP_MODULE_TOKEN=${MADIS_MODULE_TOKEN}

# Billing / online charging. Outbox is local and non-blocking for SIP.
SIP_BILLING_MODE=outbox
SIP_BILLING_TENANT=default
# SIP_BILLING_MODE=preauth is fail-closed and opt-in.
# SIP_CHARGING_PROTOCOL=http
# SIP_CHARGING_URL=
# SIP_CHARGING_FAIL_OPEN=0
# SIP_CHARGING_TIMEOUT_MS=150
# Native RFC 8506 Diameter CC over verified TLS/TCP (or explicitly protected SCTP):
# SIP_DIAMETER_HOST=
# SIP_DIAMETER_PORT=5658  # 3868 for explicitly enabled plaintext
# SIP_DIAMETER_TLS=1
# SIP_DIAMETER_TRANSPORT=tcp  # sctp requires platform SCTP and external protection
# SIP_DIAMETER_ALLOW_PLAINTEXT=0
# SIP_DIAMETER_PERSISTENT=1  # serialized verified-TLS peer reuse
# SIP_DIAMETER_CA=
# SIP_DIAMETER_CLIENT_CERT=
# SIP_DIAMETER_CLIENT_KEY=
# SIP_DIAMETER_ORIGIN_HOST=madis.localhost
# SIP_DIAMETER_ORIGIN_REALM=localhost
# SIP_DIAMETER_DEST_REALM=localhost
# SIP_IMS_CX=1              # fail-closed Cx UAR/SAR on REGISTER
# SIP_IMS_VISITED_NETWORK=
# SIP_IMS_SERVER_NAME=
# SIP_IMS_DEST_HOST=

# Standalone Mako SIP WebUI
ADMIN_BIND=127.0.0.1
ADMIN_PORT=${MADIS_ADMIN_PORT}
ADMIN_SECURE_COOKIE=1
ADMIN_SESSION_TTL_SECS=86400
ADMIN_LOGIN_MAX_FAILS=5
ADMIN_LOGIN_LOCK_SECS=900

# TLS (uncomment and set paths to enable)
# SIP_TLS_CERT=/etc/madis/tls/cert.pem
# SIP_TLS_KEY=/etc/madis/tls/key.pem

# Registration
SIP_MAX_REG_EXPIRES=3600
SIP_MIN_EXPIRES=60

# STIR/SHAKEN (disabled by default)
# STIR_SHAKEN_ENABLED=true
# STIR_SHAKEN_CERT_URL=
# STIR_SHAKEN_ATTESTATION=C
# STIR_SHAKEN_PRIVATE_KEY=

# Config file reload trigger (optional)
# SIP_CONFIG_FILE=/etc/madis/reload.trigger
EOF

chmod 640 "$MADIS_CONF_DIR/madis.env"
chown root:"$MADIS_USER" "$MADIS_CONF_DIR/madis.env"

info "Configuration written to $MADIS_CONF_DIR/madis.env"

# ── write systemd service ───────────────────────────────────────────────────
cat > /etc/systemd/system/madis.service <<EOF
[Unit]
Description=Madis SIP Proxy
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=${MADIS_USER}
Group=${MADIS_USER}
EnvironmentFile=${MADIS_CONF_DIR}/madis.env
ExecStart=${MADIS_INSTALL_DIR}/madis
WorkingDirectory=${MADIS_INSTALL_DIR}
Restart=on-failure
RestartSec=5
LimitNOFILE=65536
StandardOutput=append:${MADIS_LOG_DIR}/madis.log
StandardError=append:${MADIS_LOG_DIR}/madis-error.log

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${MADIS_LOG_DIR}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
info "Systemd service installed."

cat > /etc/systemd/system/madis-admin.service <<EOF
[Unit]
Description=Madis SIP WebUI
After=network.target postgresql.service
Requires=postgresql.service
ConditionPathExists=${MADIS_INSTALL_DIR}/admin-bin

[Service]
Type=simple
User=${MADIS_USER}
Group=${MADIS_USER}
EnvironmentFile=${MADIS_CONF_DIR}/madis.env
ExecStart=${MADIS_INSTALL_DIR}/admin-bin
WorkingDirectory=${MADIS_INSTALL_DIR}
Restart=on-failure
RestartSec=5
LimitNOFILE=65536
StandardOutput=append:${MADIS_LOG_DIR}/madis-admin.log
StandardError=append:${MADIS_LOG_DIR}/madis-admin-error.log

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${MADIS_LOG_DIR}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

info "WebUI systemd service installed."
systemctl daemon-reload

# ── set up log rotation ─────────────────────────────────────────────────────
cat > /etc/logrotate.d/madis <<EOF
${MADIS_LOG_DIR}/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    copytruncate
}
EOF

# ── fix ownership ────────────────────────────────────────────────────────────
chown -R "$MADIS_USER":"$MADIS_USER" "$MADIS_INSTALL_DIR"
chown -R "$MADIS_USER":"$MADIS_USER" "$MADIS_LOG_DIR"

# ── open firewall ports (if firewall is active) ──────────────────────────────
if command -v ufw &> /dev/null && ufw status | grep -q "active"; then
    ufw allow "$MADIS_SIP_PORT"/udp > /dev/null 2>&1 || true
    ufw allow "$MADIS_SIP_PORT"/tcp > /dev/null 2>&1 || true
    ufw allow "$MADIS_TLS_PORT"/tcp > /dev/null 2>&1 || true
    ufw allow "$MADIS_WSS_PORT"/tcp > /dev/null 2>&1 || true
    info "Firewall rules added (ufw)."
elif command -v firewall-cmd &> /dev/null && systemctl is-active firewalld &> /dev/null; then
    firewall-cmd --permanent --add-port="$MADIS_SIP_PORT"/udp > /dev/null 2>&1 || true
    firewall-cmd --permanent --add-port="$MADIS_SIP_PORT"/tcp > /dev/null 2>&1 || true
    firewall-cmd --permanent --add-port="$MADIS_TLS_PORT"/tcp > /dev/null 2>&1 || true
    firewall-cmd --permanent --add-port="$MADIS_WSS_PORT"/tcp > /dev/null 2>&1 || true
    firewall-cmd --reload > /dev/null 2>&1 || true
    info "Firewall rules added (firewalld)."
fi

# ── summary ──────────────────────────────────────────────────────────────────
echo ""
echo "==========================================="
echo "  Madis SIP Proxy — installation complete"
echo "==========================================="
echo ""
echo "  Install dir: $MADIS_INSTALL_DIR"
echo "  Version:     madis $MADIS_VERSION (Mako $MADIS_MAKO_VERSION)"
echo "  Config:      $MADIS_CONF_DIR/madis.env"
echo "  Logs:        $MADIS_LOG_DIR"
echo ""
echo "  ── Network ────────────────────────────"
echo "  Bind IP:     ${MADIS_PRIVATE_IP:-0.0.0.0}"
if [ -n "$MADIS_PUBLIC_IP" ] && [ "$MADIS_PUBLIC_IP" != "$MADIS_PRIVATE_IP" ]; then
echo "  Public IP:   $MADIS_PUBLIC_IP (used in SIP/SDP headers)"
echo "  Environment: $CLOUD_PROVIDER (NAT)"
fi
echo "  SIP UDP/TCP: $MADIS_SIP_PORT"
echo "  SIP TLS:     $MADIS_TLS_PORT"
echo "  WebSocket:   $MADIS_WSS_PORT"
echo "  Admin HTTP:  $MADIS_ADMIN_PORT"
echo "  SIP metrics: 127.0.0.1:$MADIS_SIP_ADMIN_PORT (internal)"
echo "  WebUI:       http://127.0.0.1:${MADIS_ADMIN_PORT}/admin/login"
echo "  CLI:         $MADIS_CLI_DIR/madis"
echo ""
echo "  ── Credentials (save these now) ───────"
echo "  DB name:     $MADIS_DB_NAME"
echo "  DB user:     $MADIS_DB_USER"
echo "  DB password: $MADIS_DB_PASS"
echo "  DB URL:      postgres://${MADIS_DB_USER}:****@127.0.0.1:5432/${MADIS_DB_NAME}"
echo ""
echo "  Admin token: $MADIS_ADMIN_TOKEN"
echo "  Carrier API token: $MADIS_CARRIER_API_TOKEN"
echo "  Control API token: $MADIS_CONTROL_API_TOKEN"
echo "  Control read token: $MADIS_CONTROL_API_READ_TOKEN"
echo "  SIP application token: $MADIS_APP_TOKEN"
echo "  Module bus token: $MADIS_MODULE_TOKEN"
echo "  (used as: Authorization: Bearer <token>)"
echo "  WebUI user:  admin"
echo "  WebUI pass:  $MADIS_ADMIN_PASSWORD"
echo ""
echo "  These credentials are stored in:"
echo "    $MADIS_CONF_DIR/madis.env"
echo ""
echo "  ── Next steps ─────────────────────────"
echo ""
echo "  Build from source (requires Mako 0.4.16):"
echo "    cd $MADIS_INSTALL_DIR"
echo "    MAKO_BIN=mako MAKO_RUNTIME=/path/to/mako/runtime ./scripts/build-native.sh main.mko madis"
echo ""
echo "  Start the service:"
echo "    systemctl start madis"
echo "    systemctl enable madis"
echo "    systemctl start madis-admin"
echo "    systemctl enable madis-admin"
echo ""
echo "  Check status:"
echo "    madis status"
echo "    madis health"
echo "    madis webui"
echo ""
