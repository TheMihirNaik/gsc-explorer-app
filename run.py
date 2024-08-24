from app import app
from app.routes.celery import *
import os

if __name__ == '__main__':
    # GSC - When running in production *do not* leave this option enabled.
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    app.run(debug=True)
