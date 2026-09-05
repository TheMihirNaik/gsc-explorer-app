"""Domain operations over the database.

Views call these; nothing above this file writes SQL. Each function takes and
returns plain dicts so the rest of the app stays unaware of the driver.

The model in one paragraph: an *account* is a person, identified by their
Google subject id. A *workspace* is the team that owns work; a solo user gets
one automatically. A *google_connection* is one OAuth grant, and a workspace
can hold several -- an agency connecting a client's Google account, or two
staff accounts with different property access. A *property* belongs to the
workspace, and *property_access* separately records which grants can currently
reach it, so losing a connection never loses the property or its history.
"""

from urllib.parse import urlparse

from app import db


# --------------------------------------------------------------------------
# Accounts and workspaces
# --------------------------------------------------------------------------

def upsert_account(google_sub, email, name=None, picture_url=None):
    """Find or create the person signing in, and stamp last seen.

    Keyed on google_sub, not email: people change email addresses and Google
    reissues neither. Email is stored for display and for future invitations.
    """
    now = db.utcnow()
    existing = db.query('SELECT * FROM account WHERE google_sub = ?', (google_sub,), one=True)

    if existing:
        db.execute(
            'UPDATE account SET email = ?, name = ?, picture_url = ?, last_seen_at = ? '
            'WHERE id = ?',
            (email, name, picture_url, now, existing['id']))
        return db.query('SELECT * FROM account WHERE id = ?', (existing['id'],), one=True)

    account_id = db.execute(
        'INSERT INTO account (google_sub, email, name, picture_url, created_at, last_seen_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (google_sub, email, name, picture_url, now, now))
    return db.query('SELECT * FROM account WHERE id = ?', (account_id,), one=True)


def workspaces_for_account(account_id):
    """Every workspace this person belongs to, with their role."""
    return db.query(
        'SELECT w.*, m.role FROM workspace w '
        'JOIN membership m ON m.workspace_id = w.id '
        'WHERE m.account_id = ? ORDER BY w.created_at',
        (account_id,))


def ensure_personal_workspace(account):
    """The workspace a new account lands in.

    Solo users never see the concept -- they get one workspace and it is
    invisible. It exists from day one so that an agency inviting a second
    person is a membership row, not a migration.
    """
    existing = workspaces_for_account(account['id'])
    if existing:
        return existing[0]

    now = db.utcnow()
    label = account.get('name') or (account.get('email') or 'My').split('@')[0]
    workspace_id = db.execute(
        'INSERT INTO workspace (name, kind, created_by_account_id, created_at) '
        'VALUES (?, ?, ?, ?)',
        (f"{label}'s workspace", 'personal', account['id'], now))
    db.execute(
        'INSERT INTO membership (workspace_id, account_id, role, created_at) '
        'VALUES (?, ?, ?, ?)',
        (workspace_id, account['id'], 'owner', now))

    return db.query('SELECT * FROM workspace WHERE id = ?', (workspace_id,), one=True)


def membership_role(workspace_id, account_id):
    """This person's role in a workspace, or None when they are not a member."""
    row = db.query(
        'SELECT role FROM membership WHERE workspace_id = ? AND account_id = ?',
        (workspace_id, account_id), one=True)
    return row['role'] if row else None


def add_member(workspace_id, account_id, role='member'):
    """Add someone to a workspace, or change their role if already present."""
    existing = membership_role(workspace_id, account_id)
    if existing:
        db.execute('UPDATE membership SET role = ? WHERE workspace_id = ? AND account_id = ?',
                   (role, workspace_id, account_id))
        return
    db.execute(
        'INSERT INTO membership (workspace_id, account_id, role, created_at) VALUES (?, ?, ?, ?)',
        (workspace_id, account_id, role, db.utcnow()))


# --------------------------------------------------------------------------
# Google connections
# --------------------------------------------------------------------------

def upsert_connection(workspace_id, account_id, google_sub, google_email,
                      refresh_token, access_token, token_expiry, scopes):
    """Store or refresh an OAuth grant.

    Google only returns a refresh token on the first consent, so a re-auth that
    omits one must not wipe the stored one.
    """
    now = db.utcnow()
    scopes_text = ' '.join(scopes or [])
    existing = db.query(
        'SELECT * FROM google_connection WHERE workspace_id = ? AND google_sub = ?',
        (workspace_id, google_sub), one=True)

    if existing:
        keep_refresh = existing['refresh_token']
        db.execute(
            'UPDATE google_connection SET google_email = ?, refresh_token = ?, '
            'access_token = ?, token_expiry = ?, scopes = ?, status = ?, '
            'account_id = ?, updated_at = ? WHERE id = ?',
            (google_email,
             db.encrypt_token(refresh_token) if refresh_token else keep_refresh,
             db.encrypt_token(access_token), token_expiry, scopes_text, 'active',
             account_id, now, existing['id']))
        return db.query('SELECT * FROM google_connection WHERE id = ?',
                        (existing['id'],), one=True)

    connection_id = db.execute(
        'INSERT INTO google_connection (workspace_id, account_id, google_sub, google_email, '
        'refresh_token, access_token, token_expiry, scopes, status, created_at, updated_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (workspace_id, account_id, google_sub, google_email,
         db.encrypt_token(refresh_token), db.encrypt_token(access_token),
         token_expiry, scopes_text, 'active', now, now))
    return db.query('SELECT * FROM google_connection WHERE id = ?', (connection_id,), one=True)


def get_connection(connection_id):
    return db.query('SELECT * FROM google_connection WHERE id = ?', (connection_id,), one=True)


def connections_for_workspace(workspace_id, active_only=True):
    sql = 'SELECT * FROM google_connection WHERE workspace_id = ?'
    params = [workspace_id]
    if active_only:
        sql += " AND status = 'active'"
    return db.query(sql + ' ORDER BY created_at', tuple(params))


def connection_tokens(connection):
    """Decrypted tokens for a connection row, or None values when unreadable."""
    return {
        'refresh_token': db.decrypt_token(connection.get('refresh_token')),
        'access_token': db.decrypt_token(connection.get('access_token')),
        'token_expiry': connection.get('token_expiry'),
        'scopes': (connection.get('scopes') or '').split() or None,
    }


def update_connection_tokens(connection_id, access_token, token_expiry):
    """Persist a refreshed access token so the next request skips the refresh."""
    db.execute(
        'UPDATE google_connection SET access_token = ?, token_expiry = ?, updated_at = ? '
        'WHERE id = ?',
        (db.encrypt_token(access_token), token_expiry, db.utcnow(), connection_id))


def mark_connection(connection_id, status):
    db.execute('UPDATE google_connection SET status = ?, updated_at = ? WHERE id = ?',
               (status, db.utcnow(), connection_id))


# --------------------------------------------------------------------------
# Properties
# --------------------------------------------------------------------------

def classify_site_url(site_url):
    """(property_type, domain) for a Search Console site URL.

    Two shapes exist and both must round-trip unchanged as the API key:
    'sc-domain:example.com' and 'https://example.com/'.
    """
    if site_url.startswith('sc-domain:'):
        return 'domain', site_url[len('sc-domain:'):].lower()

    parsed = urlparse(site_url)
    return 'url_prefix', (parsed.hostname or site_url).lower()


def upsert_property(workspace_id, site_url):
    """Find or create a property row for this workspace."""
    existing = db.query(
        'SELECT * FROM property WHERE workspace_id = ? AND site_url = ?',
        (workspace_id, site_url), one=True)
    if existing:
        return existing

    property_type, domain = classify_site_url(site_url)
    property_id = db.execute(
        'INSERT INTO property (workspace_id, site_url, property_type, domain, created_at) '
        'VALUES (?, ?, ?, ?, ?)',
        (workspace_id, site_url, property_type, domain, db.utcnow()))
    return db.query('SELECT * FROM property WHERE id = ?', (property_id,), one=True)


def record_property_access(property_id, connection_id, permission_level):
    """Note that this grant can currently reach this property."""
    now = db.utcnow()
    existing = db.query(
        'SELECT id FROM property_access WHERE property_id = ? AND connection_id = ?',
        (property_id, connection_id), one=True)
    if existing:
        db.execute(
            'UPDATE property_access SET permission_level = ?, last_seen_at = ? WHERE id = ?',
            (permission_level, now, existing['id']))
        return
    db.execute(
        'INSERT INTO property_access (property_id, connection_id, permission_level, last_seen_at) '
        'VALUES (?, ?, ?, ?)',
        (property_id, connection_id, permission_level, now))


def sync_properties(workspace_id, connection_id, site_entries):
    """Reconcile one sites.list response into property + property_access rows.

    Properties this connection can no longer see lose their access row but keep
    the property, its settings and its segments -- another connection may still
    reach it, and even if not, the work should outlive the grant.
    """
    seen_ids = []
    for entry in site_entries or []:
        site_url = entry.get('siteUrl')
        permission = entry.get('permissionLevel')
        if not site_url or permission == 'siteUnverifiedUser':
            continue
        prop = upsert_property(workspace_id, site_url)
        record_property_access(prop['id'], connection_id, permission)
        seen_ids.append(prop['id'])

    if seen_ids:
        placeholders = ','.join('?' for _ in seen_ids)
        db.execute(
            f'DELETE FROM property_access WHERE connection_id = ? '
            f'AND property_id NOT IN ({placeholders})',
            tuple([connection_id] + seen_ids))
    else:
        db.execute('DELETE FROM property_access WHERE connection_id = ?', (connection_id,))

    return seen_ids


def properties_for_workspace(workspace_id):
    """Properties this workspace can currently reach, with how many grants reach each."""
    return db.query(
        'SELECT p.*, COUNT(a.id) AS access_count '
        'FROM property p '
        'JOIN property_access a ON a.property_id = p.id '
        'JOIN google_connection c ON c.id = a.connection_id AND c.status = \'active\' '
        'WHERE p.workspace_id = ? '
        'GROUP BY p.id ORDER BY p.domain, p.site_url',
        (workspace_id,))


def get_property_by_site_url(workspace_id, site_url):
    return db.query('SELECT * FROM property WHERE workspace_id = ? AND site_url = ?',
                    (workspace_id, site_url), one=True)


def connection_for_property(property_id):
    """An active grant that can reach this property, preferring the strongest.

    With several, any will do -- but an owner-level grant is least likely to be
    missing data, so it goes first.
    """
    rows = db.query(
        "SELECT c.* FROM google_connection c "
        "JOIN property_access a ON a.connection_id = c.id "
        "WHERE a.property_id = ? AND c.status = 'active' "
        "ORDER BY CASE a.permission_level "
        "  WHEN 'siteOwner' THEN 0 WHEN 'siteFullUser' THEN 1 ELSE 2 END, c.id",
        (property_id,))
    return rows[0] if rows else None


# --------------------------------------------------------------------------
# Per-property settings
# --------------------------------------------------------------------------

def get_brand_keywords(property_id):
    row = db.query('SELECT brand_keywords FROM property_settings WHERE property_id = ?',
                   (property_id,), one=True)
    return db.load_json(row['brand_keywords'], []) if row else []


def set_brand_keywords(property_id, keywords):
    """Brand terms belong to a property, not to the session.

    Held in the session they followed the user between properties, so an agency
    switching from client A to client B classified B's traffic with A's terms.
    """
    payload = db.dump_json([k.strip() for k in keywords if k and k.strip()])
    now = db.utcnow()
    existing = db.query('SELECT property_id FROM property_settings WHERE property_id = ?',
                        (property_id,), one=True)
    if existing:
        db.execute('UPDATE property_settings SET brand_keywords = ?, updated_at = ? '
                   'WHERE property_id = ?', (payload, now, property_id))
    else:
        db.execute('INSERT INTO property_settings (property_id, brand_keywords, updated_at) '
                   'VALUES (?, ?, ?)', (property_id, payload, now))


# --------------------------------------------------------------------------
# Segments
# --------------------------------------------------------------------------

def list_segments(workspace_id, property_id=None):
    """Segments visible for a property: workspace-wide ones plus its own."""
    if property_id is None:
        return db.query(
            'SELECT * FROM segment WHERE workspace_id = ? ORDER BY name COLLATE NOCASE',
            (workspace_id,))
    return db.query(
        'SELECT * FROM segment WHERE workspace_id = ? AND (property_id IS NULL OR property_id = ?) '
        'ORDER BY name COLLATE NOCASE',
        (workspace_id, property_id))


def get_segment(workspace_id, segment_id):
    """One segment, scoped to the workspace so an id from elsewhere cannot be read."""
    try:
        segment_id = int(segment_id)
    except (TypeError, ValueError):
        return None
    return db.query('SELECT * FROM segment WHERE id = ? AND workspace_id = ?',
                    (segment_id, workspace_id), one=True)


def create_segment(workspace_id, name, dimension, operator, expression,
                   property_id=None, account_id=None):
    now = db.utcnow()
    segment_id = db.execute(
        'INSERT INTO segment (workspace_id, property_id, name, dimension, operator, '
        'expression, created_by_account_id, created_at, updated_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (workspace_id, property_id, name, dimension, operator, expression,
         account_id, now, now))
    return db.query('SELECT * FROM segment WHERE id = ?', (segment_id,), one=True)


def delete_segment(workspace_id, segment_id):
    """Delete within the workspace. Returns True when a row was removed."""
    segment = get_segment(workspace_id, segment_id)
    if not segment:
        return False
    db.execute('DELETE FROM segment WHERE id = ? AND workspace_id = ?',
               (segment['id'], workspace_id))
    return True


def count_segments(workspace_id):
    row = db.query('SELECT COUNT(*) AS n FROM segment WHERE workspace_id = ?',
                   (workspace_id,), one=True)
    return row['n'] if row else 0
