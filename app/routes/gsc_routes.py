from app import app
from flask import render_template, request, url_for, redirect, flash, session
from app.routes.gsc_api_auth import * 
from app.routes.gsc_api_auth import CLIENT_SECRETS_FILE, SCOPES, API_SERVICE_NAME, API_VERSION
import logging

# Configure logging
logger = logging.getLogger(__name__)

# google auth related
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
import google.auth.transport.requests

from app.tasks.celery_tasks import *

import re
import os

# This variable specifies the name of a file that contains the OAuth 2.0
# information for this application, including its client_id and client_secret.
#CLIENT_SECRETS_FILE = "client_secrets.json"

# This OAuth 2.0 access scope allows for full read/write access to the
# authenticated user's account and requires requests to use an SSL connection.
#SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly', 'https://www.googleapis.com/auth/webmasters']
#API_SERVICE_NAME = 'searchconsole'
#API_VERSION = 'v1'

@app.route('/google-search-console/', methods=['POST', 'GET'])
def google_search_console():
    if request.method == 'POST':
        # Load credentials from the session.
        credentials = google.oauth2.credentials.Credentials(
            **session['credentials'])
        
        # Check if the token is expired and refresh it if needed
        if not credentials.valid and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(google.auth.transport.requests.Request())
                # Save updated credentials back to session
                session['credentials'] = credentials_to_dict(credentials)
            except Exception as e:
                flash("Failed to refresh access token. Please reauthorize.")
                return redirect(url_for('gsc_authorize'))
        
        # Retrieve list of properties in account
        search_console_service = googleapiclient.discovery.build(
            API_SERVICE_NAME, API_VERSION, credentials=credentials)
        site_list = search_console_service.sites().list().execute()
        return site_list
    
    # GET request & GSC is logged in.
    if 'credentials' in session:
        return redirect(url_for('dashboard'))

    # GSC is not logged in.
    return redirect(url_for('gsc_authorize'))
    
from app.utils import format_dates, process_dates, keyword_type, escape_special_chars, generate_regex_from_urls, get_latest_available_date
