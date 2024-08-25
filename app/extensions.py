from celery import Celery
import os
from datetime import timedelta

redis_url = os.environ.get('REDIS_URL')
#print(redis_url)

# create the Celery instance
celery = Celery(
    'tasks', 
    broker=redis_url,
    backend=redis_url
    )

# Configure Celery
celery.conf.update(
    result_expires=timedelta(minutes=5),  # Set expiration to 5 minutes
)