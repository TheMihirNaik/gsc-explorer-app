"""Who is signed in, which workspace they are in, and which grant to use.

Before this, the app had no notion of a user at all: it asked Google only for
Search Console scopes, never read an ID token, and kept an anonymous OAuth
grant in the session. There was no stable identifier to key anything to, which
is why nothing could be saved.

Now the OAuth flow also asks for `openid email profile`, and the ID token in
the response gives a subject id that is stable for the life of the Google
account. That is the account key; everything else hangs off it.
"""

import google.oauth2.credentials
from flask import session

from app import app
from app import repositories as repo
from app.routes.google_oauth_config import get_client_secret

TOKEN_URI = 'https://oauth2.googleapis.com/token'


def current_account():
    """The signed-in person, or None."""
    account_id = session.get('account_id')
    if not account_id:
        return None
    from app import db
    return db.query('SELECT * FROM account WHERE id = ?', (account_id,), one=True)


def current_workspace():
    """The workspace being worked in, or None."""
    workspace_id = session.get('workspace_id')
    if not workspace_id:
        return None
    from app import db
    return db.query('SELECT * FROM workspace WHERE id = ?', (workspace_id,), one=True)


def current_workspace_id():
    return session.get('workspace_id')


def current_role():
    """This person's role in the current workspace, or None."""
    account_id, workspace_id = session.get('account_id'), session.get('workspace_id')
    if not account_id or not workspace_id:
        return None
    return repo.membership_role(workspace_id, account_id)


def can_edit():
    """Viewers can run reports; everyone else can also change things."""
    return current_role() in ('owner', 'admin', 'member')


def current_property_row():
    """The chosen property as a database row, or None."""
    workspace_id = session.get('workspace_id')
    site_url = session.get('selected_property')
    if not workspace_id or not site_url:
        return None
    return repo.get_property_by_site_url(workspace_id, site_url)


def sign_in(id_info, credentials):
    """Turn a completed OAuth flow into an account, workspace and connection.

    Returns the connection row. The session afterwards holds only ids -- no
    tokens travel to the browser.
    """
    account = repo.upsert_account(
        google_sub=id_info['sub'],
        email=id_info.get('email') or '',
        name=id_info.get('name'),
        picture_url=id_info.get('picture'))

    workspace = repo.ensure_personal_workspace(account)

    expiry = credentials.expiry.isoformat() if getattr(credentials, 'expiry', None) else None
    connection = repo.upsert_connection(
        workspace_id=workspace['id'],
        account_id=account['id'],
        google_sub=id_info['sub'],
        google_email=id_info.get('email') or '',
        refresh_token=credentials.refresh_token,
        access_token=credentials.token,
        token_expiry=expiry,
        scopes=list(credentials.scopes or []))

    session['account_id'] = account['id']
    session['workspace_id'] = workspace['id']
    session['connection_id'] = connection['id']
    session.permanent = True

    app.logger.info('Signed in account=%s workspace=%s connection=%s',
                    account['id'], workspace['id'], connection['id'])
    return connection


def sign_out():
    """Forget the session. Stored tokens and work are untouched."""
    for key in ('account_id', 'workspace_id', 'connection_id', 'credentials',
                'selected_property', 'brand_keywords', 'latest_date_cache', 'segments'):
        session.pop(key, None)


def credentials_for_connection(connection):
    """Build Google credentials from a stored connection row.

    The client secret is application configuration, so it is attached here
    rather than stored per connection.
    """
    tokens = repo.connection_tokens(connection)
    if not tokens['refresh_token'] and not tokens['access_token']:
        return None

    return google.oauth2.credentials.Credentials(
        token=tokens['access_token'],
        refresh_token=tokens['refresh_token'],
        token_uri=TOKEN_URI,
        client_id=_client_id(),
        client_secret=get_client_secret(),
        scopes=tokens['scopes'])


def _client_id():
    from app.routes.google_oauth_config import get_client_config
    config = get_client_config() or {}
    section = config.get('web') or config.get('installed') or {}
    return section.get('client_id')


def active_connection():
    """The grant to use for this request.

    Prefers the one the session signed in with. If the chosen property is only
    reachable through a different grant -- an agency case, where a colleague
    connected the account that can see this client -- use that one instead.
    """
    prop = current_property_row()
    if prop:
        connection = repo.connection_for_property(prop['id'])
        if connection:
            return connection

    connection_id = session.get('connection_id')
    if connection_id:
        connection = repo.get_connection(connection_id)
        if connection and connection['status'] == 'active':
            return connection

    workspace_id = session.get('workspace_id')
    if workspace_id:
        connections = repo.connections_for_workspace(workspace_id)
        if connections:
            return connections[0]

    return None


@app.context_processor
def inject_identity():
    """Account, workspace and role for the page chrome."""
    if not session.get('account_id'):
        return {'current_account': None, 'current_workspace': None, 'current_role': None}
    return {
        'current_account': current_account(),
        'current_workspace': current_workspace(),
        'current_role': current_role(),
    }
