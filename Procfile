web: gunicorn -c gunicorn.conf.py run:app
celery: celery -A app.extensions.celery worker --loglevel=info
