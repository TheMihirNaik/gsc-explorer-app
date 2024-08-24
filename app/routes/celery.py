
from celery import Celery
from app import redis_host
import os
from app.routes.gsc_api_auth import * 
from app.routes.gsc_routes import *
import pandas as pd
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

redis_url = os.environ.get('REDIS_URL')
print(redis_url)

# create the Celery instance
celery = Celery(
    'tasks', 
    broker=redis_url,
    backend=redis_url
    )

#define a dummy task for testing
@celery.task
def add(x, y):
    print("celery task in progress")
    return x + y

@celery.task
def celery_test_gsc_data(selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups):
    logger.info("celery task in progress")
    webmasters_service = build_gsc_service()
    gsc_data = fetch_search_console_data(webmasters_service, selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups)
    logger.info(f"GSC Data: {gsc_data}")
    return 'data fetched'

