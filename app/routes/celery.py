
from celery import Celery
from app import redis_host
import os
from app.routes.gsc_api_auth import * 
from app.routes.gsc_routes import *

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
    print("celery task in progress")
    return x + y

@celery.task
def celery_test_gsc_data(webmasters_service, selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups):
    print("celery task in progress")

    gsc_data = fetch_search_console_data(webmasters_service, selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups)

    return gsc_data

