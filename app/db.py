"""SQLite connection handling, migrations, and token encryption.

Deliberately thin and driver-agnostic: connections come from one place, SQL is
written portably, and nothing above this module knows it is talking to SQLite.
Moving to Postgres later means changing this file, not the callers.

A note on where the file lives. SQLite keeps everything in one file on local
disk, so on a platform with an ephemeral filesystem -- the Procfile here points
at that kind of host -- the database is destroyed on every deploy and restart.
Set DATABASE_PATH to a mounted volume, or move to Postgres, before this holds
anything anyone would miss. The app logs the resolved path at startup so it is
visible rather than assumed.
"""

import base64
import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

import flask

DEFAULT_DATABASE_PATH = os.path.join('data', 'gsc_explorer.db')
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), 'migrations')

_migration_lock = threading.Lock()
_migrations_applied = False


def database_path():
    """Where the SQLite file lives. Override with DATABASE_PATH."""
    return os.environ.get('DATABASE_PATH') or DEFAULT_DATABASE_PATH


def storage_is_configured():
    """Whether someone has deliberately chosen where the database lives.

    An unset DATABASE_PATH means the file sits inside the container's own
    filesystem. On Coolify, Heroku, Render and most container hosts that is
    wiped on every redeploy, taking every account, connection and segment with
    it -- and it fails silently, because a fresh empty database works fine
    until someone notices their data is gone.
    """
    return bool(os.environ.get('DATABASE_PATH'))


def utcnow():
    """Timestamps are ISO-8601 UTC strings, which sort correctly as text."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# --------------------------------------------------------------------------
# Connections
# --------------------------------------------------------------------------

def _configure(connection):
    connection.row_factory = sqlite3.Row
    # SQLite ignores foreign keys unless asked, per connection, every time.
    connection.execute('PRAGMA foreign_keys = ON')
    # WAL lets readers run while a writer holds the file, which matters with
    # gunicorn's eight threads sharing one process.
    connection.execute('PRAGMA journal_mode = WAL')
    connection.execute('PRAGMA synchronous = NORMAL')
    # Wait rather than raising "database is locked" the instant a write collides.
    connection.execute('PRAGMA busy_timeout = 5000')
    return connection


def connect():
    """A new connection with the pragmas applied. Caller closes it."""
    path = database_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    return _configure(sqlite3.connect(path))


def get_db():
    """The connection for this request, opened on first use."""
    if flask.has_app_context():
        connection = getattr(flask.g, '_database', None)
        if connection is None:
            connection = flask.g._database = connect()
        return connection
    return connect()


def close_db(_exception=None):
    connection = getattr(flask.g, '_database', None) if flask.has_app_context() else None
    if connection is not None:
        flask.g._database = None
        connection.close()


# --------------------------------------------------------------------------
# Query helpers
# --------------------------------------------------------------------------

def query(sql, params=(), one=False):
    """Read rows as dicts. `one=True` returns a single row or None."""
    cursor = get_db().execute(sql, params)
    rows = cursor.fetchall()
    cursor.close()
    if one:
        return dict(rows[0]) if rows else None
    return [dict(row) for row in rows]


def execute(sql, params=()):
    """Write, commit, and return the new row id."""
    connection = get_db()
    cursor = connection.execute(sql, params)
    connection.commit()
    row_id = cursor.lastrowid
    cursor.close()
    return row_id


# --------------------------------------------------------------------------
# Migrations
# --------------------------------------------------------------------------

def _applied_migrations(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    connection.commit()
    return {row['filename'] for row in
            connection.execute('SELECT filename FROM schema_migrations')}


def run_migrations(logger=None):
    """Apply every .sql file in app/migrations that has not run yet.

    Files run in filename order and each runs in one transaction, so a broken
    migration leaves the database on the previous version rather than halfway.
    """
    global _migrations_applied

    with _migration_lock:
        connection = connect()
        try:
            already = _applied_migrations(connection)
            pending = sorted(
                name for name in os.listdir(MIGRATIONS_DIR)
                if name.endswith('.sql') and name not in already)

            for name in pending:
                with open(os.path.join(MIGRATIONS_DIR, name), encoding='utf-8') as handle:
                    sql = handle.read()
                try:
                    connection.executescript('BEGIN;\n' + sql + '\nCOMMIT;')
                    connection.execute(
                        'INSERT INTO schema_migrations (filename, applied_at) VALUES (?, ?)',
                        (name, utcnow()))
                    connection.commit()
                    if logger:
                        logger.info('Applied migration %s', name)
                except Exception:
                    connection.rollback()
                    raise

            _migrations_applied = True
            return pending
        finally:
            connection.close()


# --------------------------------------------------------------------------
# Token encryption
# --------------------------------------------------------------------------

def _encryption_key():
    """Key for encrypting OAuth tokens at rest.

    Prefers TOKEN_ENCRYPTION_KEY. Falls back to a key derived from SECRET_KEY,
    which means rotating SECRET_KEY invalidates stored tokens and everyone
    reconnects -- an inconvenience, and still far better than plaintext refresh
    tokens sitting in a file.
    """
    explicit = os.environ.get('TOKEN_ENCRYPTION_KEY')
    if explicit:
        return explicit.encode() if isinstance(explicit, str) else explicit

    secret = os.environ.get('SECRET_KEY') or ''
    digest = hashlib.sha256(f'gsc-explorer-token-key:{secret}'.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_token(value):
    """Encrypt a token for storage. Returns None for a missing token."""
    if not value:
        return None
    from cryptography.fernet import Fernet
    return Fernet(_encryption_key()).encrypt(value.encode()).decode()


def decrypt_token(value):
    """Decrypt a stored token, or None when it cannot be read.

    A token encrypted under a previous SECRET_KEY fails here rather than
    raising into a request; the caller treats that as "needs reconnecting".
    """
    if not value:
        return None
    from cryptography.fernet import Fernet, InvalidToken
    try:
        return Fernet(_encryption_key()).decrypt(value.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return None


# --------------------------------------------------------------------------
# JSON columns
# --------------------------------------------------------------------------

def load_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def dump_json(value):
    return json.dumps(value, separators=(',', ':'))
