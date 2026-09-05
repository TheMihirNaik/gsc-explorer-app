-- GSC Explorer core schema.
--
-- Shape of the problem this models:
--
--   A person signs in with Google. That gives us a stable account id (the
--   OpenID `sub`) and an OAuth grant. The grant is what can reach Search
--   Console -- but the *work* (segments, brand terms, later snapshots) belongs
--   to a team, not to whoever happened to authorise.
--
--   That distinction is what agencies need. Two staff members may each hold a
--   grant that reaches the same client property; when one leaves, the property,
--   its settings and its history must survive. So a property belongs to a
--   workspace, and `property_access` records the separate question of which
--   grants can currently reach it.
--
-- SQL is kept portable: no SQLite-only syntax, so moving to Postgres is a
-- change of driver and id type, not a rewrite.

-- A person. Keyed by Google's subject id, which is stable for the life of the
-- Google account and survives an email change.
CREATE TABLE account (
    id                INTEGER PRIMARY KEY,
    google_sub        TEXT NOT NULL UNIQUE,
    email             TEXT NOT NULL,
    name              TEXT,
    picture_url       TEXT,
    created_at        TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL
);
CREATE INDEX idx_account_email ON account (email);

-- The team that owns work. A solo user gets one automatically and never sees
-- the concept; an agency has one per agency, or one per client if they prefer.
CREATE TABLE workspace (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT NOT NULL,
    kind                  TEXT NOT NULL DEFAULT 'personal',   -- personal | team
    created_by_account_id INTEGER REFERENCES account (id) ON DELETE SET NULL,
    created_at            TEXT NOT NULL
);

-- Who is in a workspace and what they may do.
--   owner  : billing, delete workspace, everything below
--   admin  : manage members, connections and properties
--   member : create and edit segments, run reports
--   viewer : run reports only
CREATE TABLE membership (
    id           INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    account_id   INTEGER NOT NULL REFERENCES account (id) ON DELETE CASCADE,
    role         TEXT NOT NULL DEFAULT 'member',
    created_at   TEXT NOT NULL,
    UNIQUE (workspace_id, account_id),
    CHECK (role IN ('owner', 'admin', 'member', 'viewer'))
);
CREATE INDEX idx_membership_account ON membership (account_id);

-- One Google OAuth grant. Several can belong to a workspace: an agency
-- connecting a client's Google account, or two staff accounts with different
-- property access.
CREATE TABLE google_connection (
    id                INTEGER PRIMARY KEY,
    workspace_id      INTEGER NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    account_id        INTEGER REFERENCES account (id) ON DELETE SET NULL,  -- who authorised
    google_sub        TEXT NOT NULL,      -- the Google account the tokens belong to
    google_email      TEXT NOT NULL,
    refresh_token     TEXT,               -- encrypted at rest; null if Google withheld one
    access_token      TEXT,               -- encrypted at rest
    token_expiry      TEXT,
    scopes            TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'active',   -- active | needs_reauth | revoked
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE (workspace_id, google_sub),
    CHECK (status IN ('active', 'needs_reauth', 'revoked'))
);
CREATE INDEX idx_connection_workspace ON google_connection (workspace_id);

-- A Search Console property as this workspace knows it.
-- site_url is the exact API key ('sc-domain:example.com' or 'https://example.com/')
-- and must round-trip unchanged; `domain` is derived for grouping and display.
CREATE TABLE property (
    id            INTEGER PRIMARY KEY,
    workspace_id  INTEGER NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    site_url      TEXT NOT NULL,
    property_type TEXT NOT NULL,          -- domain | url_prefix
    domain        TEXT NOT NULL,
    display_name  TEXT,                   -- an agency can label it "Client A - Blog"
    created_at    TEXT NOT NULL,
    UNIQUE (workspace_id, site_url),
    CHECK (property_type IN ('domain', 'url_prefix'))
);
CREATE INDEX idx_property_workspace ON property (workspace_id);
CREATE INDEX idx_property_domain ON property (workspace_id, domain);

-- Which grants can currently reach a property, and with what permission.
-- Separate from `property` on purpose: revoking one connection must not delete
-- the property or anything attached to it.
CREATE TABLE property_access (
    id               INTEGER PRIMARY KEY,
    property_id      INTEGER NOT NULL REFERENCES property (id) ON DELETE CASCADE,
    connection_id    INTEGER NOT NULL REFERENCES google_connection (id) ON DELETE CASCADE,
    permission_level TEXT,                -- siteOwner | siteFullUser | siteRestrictedUser
    last_seen_at     TEXT NOT NULL,       -- last time sites.list still reported it
    UNIQUE (property_id, connection_id)
);
CREATE INDEX idx_access_connection ON property_access (connection_id);

-- Per-property settings. Brand keywords were global to the session, so an
-- agency switching between clients carried client A's brand terms into
-- client B's reports.
CREATE TABLE property_settings (
    property_id    INTEGER PRIMARY KEY REFERENCES property (id) ON DELETE CASCADE,
    brand_keywords TEXT NOT NULL DEFAULT '[]',    -- JSON array of strings
    updated_at     TEXT NOT NULL
);

-- Saved segments. Owned by the workspace so a team shares them; property_id
-- NULL means "applies to every property", which is what a rule like /blog/
-- usually wants.
CREATE TABLE segment (
    id                    INTEGER PRIMARY KEY,
    workspace_id          INTEGER NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    property_id           INTEGER REFERENCES property (id) ON DELETE CASCADE,
    name                  TEXT NOT NULL,
    dimension             TEXT NOT NULL,
    operator              TEXT NOT NULL,
    expression            TEXT NOT NULL,
    created_by_account_id INTEGER REFERENCES account (id) ON DELETE SET NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    CHECK (dimension IN ('PAGE', 'QUERY'))
);
CREATE INDEX idx_segment_workspace ON segment (workspace_id);
CREATE INDEX idx_segment_property ON segment (property_id);
