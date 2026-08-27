"""OAuth client configuration for the Google Search Console integration.

The client id and secret are read from environment variables so that the
client secret never needs to live in the repository or on the container
filesystem. A local ``client_secrets.json`` is still honoured as a fallback
so development setups keep working unchanged.

Environment variables:
    GOOGLE_OAUTH_CLIENT_ID      (required in production)
    GOOGLE_OAUTH_CLIENT_SECRET  (required in production)
    GOOGLE_OAUTH_PROJECT_ID     (optional, informational)
    GOOGLE_CLIENT_SECRETS_FILE  (optional, overrides the fallback path)
"""

import json
import os

# Retained for backwards compatibility: local development may still place a
# client_secrets.json next to the application.
CLIENT_SECRETS_FILE = os.environ.get(
    "GOOGLE_CLIENT_SECRETS_FILE", "client_secrets.json")

_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_CERT_URI = "https://www.googleapis.com/oauth2/v1/certs"


def _config_from_env():
  """Build a client config dict from environment variables."""
  client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
  client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
  if not client_id or not client_secret:
    return None
  return {
      "web": {
          "client_id": client_id,
          "client_secret": client_secret,
          "project_id": os.environ.get("GOOGLE_OAUTH_PROJECT_ID", ""),
          "auth_uri": _AUTH_URI,
          "token_uri": _TOKEN_URI,
          "auth_provider_x509_cert_url": _CERT_URI,
      }
  }


def _config_from_file():
  """Load a client config dict from client_secrets.json, if present."""
  if not os.path.exists(CLIENT_SECRETS_FILE):
    return None
  with open(CLIENT_SECRETS_FILE) as handle:
    return json.load(handle)


def get_client_config():
  """Return the OAuth client config, preferring the environment.

  Returns None when the application has not been configured, which callers
  should treat as a server configuration error.
  """
  return _config_from_env() or _config_from_file()


def get_client_secret():
  """Return just the client secret, or None when not configured."""
  config = get_client_config()
  if not config:
    return None
  section = config.get("web") or config.get("installed") or {}
  return section.get("client_secret")


def is_configured():
  """True when OAuth credentials are available from env or file."""
  return get_client_config() is not None
