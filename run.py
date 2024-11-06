from app import app
from app.tasks.celery_tasks import *
from app.extensions import celery
from werkzeug.middleware.proxy_fix import ProxyFix
import os

# Set environment variable conditionally for development only
if os.getenv('FLASK_ENV') == 'development':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# Use ProxyFix to handle HTTPS forwarded headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

if __name__ == '__main__':
    app.run()
