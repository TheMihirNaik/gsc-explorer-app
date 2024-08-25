from app.extensions import celery
from app.routes.gsc_api_auth import * 
from app.routes.gsc_routes import *
import pandas as pd
from celery.utils.log import get_task_logger
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


logger = get_task_logger(__name__)

import gc

@celery.task
def celery_test_gsc_data(credentials_data, selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups):
    
    # Rebuild credentials
    credentials = Credentials(**credentials_data)

    # Rebuild the webmasters_service within the Celery task
    webmasters_service = build(API_SERVICE_NAME, API_VERSION, credentials=credentials)
    #logger.info("web master service built successfully")

    gsc_data = fetch_search_console_data(webmasters_service, selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups)
    #logger.info(f"GSC Data: {gsc_data}")

    # Generate HTML content from the fetched data
    html_content = '<table id="gsc-data-table" class="display"><thead><tr><th>Date</th><th>Query</th><th>Page</th></tr></thead><tbody>'
    
    for index, row in gsc_data.iterrows():
        html_content += f'<tr><td>{row["DATE"]}</td><td>{row["QUERY"]}</td><td>{row["PAGE"]}</td></tr>'
    
    html_content += '</tbody></table>'

    gc.collect()
    return html_content

    # gsc_data is a dataframe, convert it to json
    #gsc_data_json = gsc_data.to_json(orient='records')

    #gc.collect()
    #return gsc_data_json
