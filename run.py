from app import app
from app.tasks.celery_tasks import *
from app.extensions import celery
import os

if __name__ == '__main__':
    # GSC - When running in production *do not* leave this option enabled.
    #os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    # run on a different port
    #app.run(host='0.0.0.0', port=6000, debug=True)
    #app.run(debug=True, port=5001)
    app.run(debug=True)
