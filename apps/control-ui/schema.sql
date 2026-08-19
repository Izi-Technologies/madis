ALTER TABLE dispatch_sets ADD COLUMN IF NOT EXISTS direction TEXT DEFAULT 'egress';
ALTER TABLE gateways ADD COLUMN IF NOT EXISTS gateway_type TEXT DEFAULT 'carrier';
ALTER TABLE gateways ADD COLUMN IF NOT EXISTS trusted_source BOOLEAN DEFAULT false;

CREATE TABLE IF NOT EXISTS control_facilities (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL UNIQUE,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS control_ivr_groups (
    id SERIAL PRIMARY KEY,
    facility_id INT REFERENCES control_facilities(id) ON DELETE CASCADE,
    name TEXT NOT NULL UNIQUE,
    dispatch_set_name TEXT NOT NULL UNIQUE,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS control_facility_anis (
    id SERIAL PRIMARY KEY,
    facility_id INT NOT NULL REFERENCES control_facilities(id) ON DELETE CASCADE,
    ani TEXT NOT NULL UNIQUE,
    range_start TEXT NOT NULL DEFAULT '',
    range_end TEXT NOT NULL DEFAULT '',
    match_type TEXT NOT NULL DEFAULT 'exact',
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT control_facility_anis_match_type CHECK (match_type IN ('exact', 'prefix', 'range'))
);

CREATE TABLE IF NOT EXISTS control_ivr_servers (
    id SERIAL PRIMARY KEY,
    group_id INT NOT NULL REFERENCES control_ivr_groups(id) ON DELETE CASCADE,
    name TEXT NOT NULL UNIQUE,
    ip TEXT NOT NULL,
    port INT NOT NULL DEFAULT 5060,
    transport TEXT NOT NULL DEFAULT 'UDP',
    gateway_name TEXT NOT NULL UNIQUE,
    trusted BOOLEAN NOT NULL DEFAULT true,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS control_carrier_groups (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    dispatch_set_name TEXT NOT NULL UNIQUE,
    strategy TEXT NOT NULL DEFAULT 'priority',
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS control_carriers (
    id SERIAL PRIMARY KEY,
    group_id INT NOT NULL REFERENCES control_carrier_groups(id) ON DELETE CASCADE,
    name TEXT NOT NULL UNIQUE,
    ip TEXT NOT NULL,
    port INT NOT NULL DEFAULT 5060,
    transport TEXT NOT NULL DEFAULT 'UDP',
    priority INT NOT NULL DEFAULT 10,
    weight INT NOT NULL DEFAULT 100,
    gateway_name TEXT NOT NULL UNIQUE,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS control_outbound_routes (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    prefix TEXT NOT NULL,
    carrier_group_id INT NOT NULL REFERENCES control_carrier_groups(id) ON DELETE CASCADE,
    priority INT NOT NULL DEFAULT 10,
    strip_prefix TEXT NOT NULL DEFAULT '',
    add_prefix TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS control_number_rewrites (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    match_prefix TEXT NOT NULL,
    strip_digits INT NOT NULL DEFAULT 0,
    add_prefix TEXT NOT NULL DEFAULT '',
    priority INT NOT NULL DEFAULT 10,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS control_signing_hops (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    host TEXT NOT NULL,
    port INT NOT NULL DEFAULT 5060,
    transport TEXT NOT NULL DEFAULT 'UDP',
    priority INT NOT NULL DEFAULT 10,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS control_audit_events (
    id BIGSERIAL PRIMARY KEY,
    actor TEXT NOT NULL DEFAULT 'operator',
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS control_users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS control_roles (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS control_permissions (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS control_role_permissions (
    role_id INT NOT NULL REFERENCES control_roles(id) ON DELETE CASCADE,
    permission_id INT NOT NULL REFERENCES control_permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS control_user_roles (
    user_id INT NOT NULL REFERENCES control_users(id) ON DELETE CASCADE,
    role_id INT NOT NULL REFERENCES control_roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

INSERT INTO control_roles (name,description) VALUES
  ('admin','Full administrative control'),
  ('operator','Create and manage facilities, IVRs, carriers, routes, rewrites, and signing hops'),
  ('viewer','Read-only access')
ON CONFLICT (name) DO NOTHING;

INSERT INTO control_permissions (name,description) VALUES
  ('facility:read','View facilities and ANI groups'),
  ('facility:write','Create facilities and ANI groups'),
  ('ivr:read','View IVR groups and trusted IVR servers'),
  ('ivr:write','Create IVR groups and trusted IVR servers'),
  ('carrier:read','View carrier groups and carrier IPs'),
  ('carrier:write','Create carrier groups and carrier IPs'),
  ('route:read','View outbound routes and rewrite rules'),
  ('route:write','Create outbound routes and rewrite rules'),
  ('signing:read','View identity signing SIP hops'),
  ('signing:write','Create identity signing SIP hops'),
  ('audit:read','View audit events'),
  ('user:manage','Create users and assign roles')
ON CONFLICT (name) DO NOTHING;

INSERT INTO control_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM control_roles r CROSS JOIN control_permissions p
WHERE r.name = 'admin'
ON CONFLICT DO NOTHING;

INSERT INTO control_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM control_roles r JOIN control_permissions p ON p.name IN (
  'facility:read','facility:write','ivr:read','ivr:write','carrier:read','carrier:write',
  'route:read','route:write','signing:read','signing:write','audit:read'
)
WHERE r.name = 'operator'
ON CONFLICT DO NOTHING;

INSERT INTO control_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM control_roles r JOIN control_permissions p ON p.name IN (
  'facility:read','ivr:read','carrier:read','route:read','signing:read','audit:read'
)
WHERE r.name = 'viewer'
ON CONFLICT DO NOTHING;

INSERT INTO control_permissions (name,description) VALUES
  ('report:read','View operational call reports')
ON CONFLICT (name) DO NOTHING;

INSERT INTO control_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM control_roles r JOIN control_permissions p ON p.name = 'report:read'
WHERE r.name IN ('admin','operator','viewer')
ON CONFLICT DO NOTHING;


ALTER TABLE control_facility_anis ADD COLUMN IF NOT EXISTS range_start TEXT NOT NULL DEFAULT '';
ALTER TABLE control_facility_anis ADD COLUMN IF NOT EXISTS range_end TEXT NOT NULL DEFAULT '';
ALTER TABLE control_facility_anis DROP CONSTRAINT IF EXISTS control_facility_anis_match_type;
ALTER TABLE control_facility_anis ADD CONSTRAINT control_facility_anis_match_type CHECK (match_type IN ('exact', 'prefix', 'range'));
UPDATE control_facility_anis SET range_start = ani, range_end = ani WHERE range_start = '' AND range_end = '';


ALTER TABLE control_facilities ADD COLUMN IF NOT EXISTS ivr_group_id INT REFERENCES control_ivr_groups(id) ON DELETE SET NULL;
UPDATE control_facilities f SET ivr_group_id = g.id
FROM control_ivr_groups g
WHERE g.facility_id = f.id AND f.ivr_group_id IS NULL;

CREATE TABLE IF NOT EXISTS control_borrowed_anis (
    id BIGSERIAL PRIMARY KEY,
    facility_id INT NOT NULL REFERENCES control_facilities(id) ON DELETE CASCADE,
    ani TEXT NOT NULL,
    borrowed_by TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT '',
    expires_at TIMESTAMP NOT NULL,
    returned_at TIMESTAMP,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE control_borrowed_anis ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT true;
DROP INDEX IF EXISTS control_borrowed_anis_active_ani;
CREATE UNIQUE INDEX IF NOT EXISTS control_borrowed_anis_active_ani
ON control_borrowed_anis (ani)
WHERE active = true;

INSERT INTO control_roles (name,description) VALUES
  ('engineer','Borrow facility ANIs for testing and view operational routing state')
ON CONFLICT (name) DO NOTHING;

INSERT INTO control_permissions (name,description) VALUES
  ('testing:read','View ANI testing loans'),
  ('testing:borrow','Borrow and return facility ANIs for testing')
ON CONFLICT (name) DO NOTHING;

INSERT INTO control_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM control_roles r JOIN control_permissions p ON p.name IN (
  'testing:read','testing:borrow','facility:read','ivr:read','carrier:read','route:read','report:read','audit:read'
)
WHERE r.name = 'engineer'
ON CONFLICT DO NOTHING;

INSERT INTO control_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM control_roles r JOIN control_permissions p ON p.name IN ('testing:read','testing:borrow')
WHERE r.name IN ('admin','operator')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS control_facility_ips (
    id SERIAL PRIMARY KEY,
    facility_id INT NOT NULL REFERENCES control_facilities(id) ON DELETE CASCADE,
    ip TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(facility_id, ip)
);
