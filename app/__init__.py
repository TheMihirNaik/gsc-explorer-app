from flask import Flask
from flask_compress import Compress
#from pymongo import MongoClient
from datetime import timedelta

import os
from dotenv import load_dotenv

dotenv_path = '.env'  # Specify the path to your .env file
load_dotenv(dotenv_path)

#VALUESERP_API_KEY = os.getenv('VALUESERP_API_KEY')
#print(VALUESERP_API_KEY)
SECRET_KEY = os.getenv('SECRET_KEY')
#print(SECRET_KEY)
#MONGO_URI = os.getenv('MONGO_URI')
#print(MONGO_URI)
#MONGO_DB_NAME = os.getenv('MONGO_DB_NAME')
#print(MONGO_DB_NAME)
#OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
#print(OPENAI_API_KEY)

redis_host = os.getenv('REDIS_HOST')

# Initialize Flask app
app = Flask(__name__)

app.config['PREFERRED_URL_SCHEME'] = 'https'

# Session configuration
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=300)

# Access environment variables.
#
# Fail at startup rather than on the first request that touches the session:
# with no key Flask raises deep inside a route, which reads as an application
# bug rather than as missing configuration.
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set. Generate one with "
        "`python -c \"import secrets; print(secrets.token_hex(32))\"` "
        "and set it in the environment (see .env.example).")

app.config['SECRET_KEY'] = SECRET_KEY

# Compress responses. The report routes ship large, highly repetitive payloads
# (DataTables JSON, pandas to_html tables, clustering scatter data) that were
# going out raw.
Compress(app)

# Configure logging
import logging
from logging.handlers import RotatingFileHandler
import sys

if not app.debug:
    # Set up file handler
    file_handler = RotatingFileHandler('app.log', maxBytes=10240, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    
    # Set up console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    console_handler.setLevel(logging.INFO)
    app.logger.addHandler(console_handler)
    
    app.logger.setLevel(logging.INFO)
    app.logger.info('GSC Explorer startup')

# Session storage.
#
# Flask's default session is a signed -- but not encrypted -- cookie, so the
# Google OAuth credentials kept in it, refresh token included, travel to the
# browser on every request and are readable by anyone holding the cookie.
# When Redis is configured the session payload lives server-side and the
# cookie carries only an opaque id. If Redis is unavailable we log loudly and
# fall back to the cookie session rather than failing to boot.
redis_url = os.getenv('REDIS_URL')

if redis_url:
    try:
        import redis as redis_client_lib
        from flask_session import Session

        session_redis = redis_client_lib.from_url(redis_url)
        session_redis.ping()

        app.config['SESSION_TYPE'] = 'redis'
        app.config['SESSION_REDIS'] = session_redis
        app.config['SESSION_PERMANENT'] = True
        app.config['SESSION_KEY_PREFIX'] = 'gscx_session:'
        Session(app)

        app.logger.info('Server-side sessions enabled (Redis)')
    except Exception as session_error:
        app.logger.warning(
            'Could not enable server-side sessions (%s). Falling back to '
            'cookie sessions -- OAuth credentials will be stored in the '
            'client cookie.', session_error)
else:
    app.logger.warning(
        'REDIS_URL is not set. Using cookie sessions -- OAuth credentials '
        'will be stored in the client cookie.')

# Database. SQLite by default; see app/db.py for the deployment caveat about
# ephemeral filesystems.
from app import db as _db

app.teardown_appcontext(_db.close_db)

try:
    _applied = _db.run_migrations(logger=app.logger)
    app.logger.info('Database ready at %s%s', _db.database_path(),
                    f' (applied {len(_applied)} migration(s))' if _applied else '')
    if not _db.storage_is_configured():
        app.logger.warning(
            'DATABASE_PATH is not set, so the database lives at %s inside the '
            'container. On a container host this is destroyed on every '
            'redeploy. Mount a volume and point DATABASE_PATH at it.',
            os.path.abspath(_db.database_path()))
except Exception as _migration_error:
    app.logger.error('Database migrations failed: %s', _migration_error, exc_info=True)
    raise

# Initialize MongoDB client
#cluster = MongoClient(MONGO_URI)

# fetch a database from cluster connection
#database = cluster[MONGO_DB_NAME]

# Import OpenAI and create client
#from openai import OpenAI

#client = OpenAI(
#    api_key=OPENAI_API_KEY
#    )

# Import routes and models
from app.routes import default_routes, customer_support, datatables, plotly, gsc_api_auth, gsc_routes

