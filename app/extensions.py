from celery import Celery
import os

redis_url = os.environ.get('REDIS_URL')
#print(redis_url)

# create the Celery instance
celery = Celery(
    'tasks', 
    broker=redis_url,
    backend=redis_url
    )