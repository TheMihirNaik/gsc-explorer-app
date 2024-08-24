from celery import Celery
from app import redis_host

print('celery routes imported')

# create the Celery instance
celery = Celery(
    'tasks', 
    broker=redis_host,
    backend=redis_host
    )
print("celery instance created")

#define a dummy task for testing
@celery.task
def add(x, y):
    return x + y

