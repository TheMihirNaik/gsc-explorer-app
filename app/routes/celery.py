
from celery import Celery
from app import redis_host
import os
from app.routes.gsc_api_auth import * 
from app.routes.gsc_routes import *
import pandas as pd
from celery.utils.log import get_task_logger
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


logger = get_task_logger(__name__)

redis_url = os.environ.get('REDIS_URL')
#print(redis_url)

# create the Celery instance
celery = Celery(
    'tasks', 
    broker=redis_url,
    backend=redis_url
    )

#define a dummy task for testing
@celery.task
def add(x, y):
    print("multiplication - celery task in progress")
    return x + y


import gc

@celery.task
def celery_test_gsc_data(credentials_data, selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups):
    logger.info("gscdata ------ celery task in progress")
    # Rebuild credentials
    credentials = Credentials(**credentials_data)

    # Rebuild the webmasters_service within the Celery task
    webmasters_service = build(API_SERVICE_NAME, API_VERSION, credentials=credentials)
    logger.info("web master service built successfully")

    gsc_data = fetch_search_console_data(webmasters_service, selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups)
    logger.info(f"GSC Data: {gsc_data}")
    gc.collect()
    return 'data fetched'
