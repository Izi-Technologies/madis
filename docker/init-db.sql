-- Madis SIP Proxy — database schema

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

CREATE TABLE IF NOT EXISTS registrations (
    aor             TEXT PRIMARY KEY,
    contact         TEXT NOT NULL,
    transport       TEXT DEFAULT 'UDP',
    node_id         TEXT DEFAULT '',
    user_agent      TEXT,
    updated_at      TIMESTAMP DEFAULT NOW(),
    created_at      TIMESTAMP DEFAULT NOW()
);

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

CREATE TABLE IF NOT EXISTS dispatch_sets (
    id              SERIAL PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,
    algorithm       TEXT DEFAULT 'round-robin',
    description     TEXT,
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dispatch_members (
    id              SERIAL PRIMARY KEY,
    set_id          INT NOT NULL,
    gateway_id      INT NOT NULL,
    priority        INT DEFAULT 10,
    weight          INT DEFAULT 100,
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMP DEFAULT NOW()
);

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

CREATE TABLE IF NOT EXISTS dids (
    id              SERIAL PRIMARY KEY,
    number          TEXT UNIQUE NOT NULL,
    destination_user TEXT NOT NULL,
    description     TEXT,
    enabled         BOOLEAN DEFAULT true,
    created_at      TIMESTAMP DEFAULT NOW()
);

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

CREATE TABLE IF NOT EXISTS sip_transactions (
    id              SERIAL PRIMARY KEY,
    call_id         TEXT,
    direction       TEXT,
    method          TEXT,
    source          TEXT,
    ts              TIMESTAMP DEFAULT NOW()
);

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

CREATE TABLE IF NOT EXISTS config (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    description     TEXT
);

CREATE TABLE IF NOT EXISTS security_bans (
    source_ip       TEXT PRIMARY KEY,
    reason          TEXT DEFAULT '',
    ban_count       INT DEFAULT 1,
    expires_at      TIMESTAMP,
    permanent       BOOLEAN DEFAULT false,
    created_at      TIMESTAMP DEFAULT NOW()
);

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

-- Default config
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
