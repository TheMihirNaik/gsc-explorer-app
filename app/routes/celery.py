from celery import Celery
from app import redis_host
import os

print('celery routes imported')

redis_url = os.environ.get('REDIS_URL')
print(redis_url)

# create the Celery instance
celery = Celery(
    'tasks', 
    broker=redis_url,
    backend=redis_url
    )
print("celery instance created")

#define a dummy task for testing
@celery.task
def add(x, y):
    return x + y

