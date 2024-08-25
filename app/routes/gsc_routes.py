from app import app
from flask import render_template, request, url_for, redirect, flash, session
from app.routes.gsc_api_auth import * 
from app.routes.gsc_api_auth import CLIENT_SECRETS_FILE, SCOPES, API_SERVICE_NAME, API_VERSION

# google auth related
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery

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
    
from datetime import datetime, timedelta

def format_dates(start_date_str, end_date_str):
    try:
        # Convert the dates to datetime objects
        start_date_obj = datetime.strptime(start_date_str, '%m/%d/%Y')
        end_date_obj = datetime.strptime(end_date_str, '%m/%d/%Y')

        # Format the dates in YYYY-MM-DD format
        start_date_formatted = start_date_obj.strftime('%Y-%m-%d')
        end_date_formatted = end_date_obj.strftime('%Y-%m-%d')

        return start_date_formatted, end_date_formatted
    except ValueError:
        return None, None  # Return None if there's an error in date conversion

def process_dates(start_date_str, end_date_str):
    current_period_start_date = start_date_str
    current_period_end_date = end_date_str

    current_start_date, current_end_date = format_dates(current_period_start_date, current_period_end_date)

    if current_start_date is None or current_end_date is None:
        return None, None, None, None, None, None

    current_start_date_obj = datetime.strptime(current_start_date, '%Y-%m-%d')
    current_end_date_obj = datetime.strptime(current_end_date, '%Y-%m-%d')

    # Previous period start date and end date
    previous_period_start_date = (current_start_date_obj - timedelta(days=1)).strftime('%Y-%m-%d')
    previous_period_end_date = (current_end_date_obj - timedelta(days=1)).strftime('%Y-%m-%d')

    # Previous year start date and end date
    previous_year_start_date = (current_start_date_obj - timedelta(days=365)).strftime('%Y-%m-%d')
    previous_year_end_date = (current_end_date_obj - timedelta(days=365)).strftime('%Y-%m-%d')

    return current_start_date, current_end_date, previous_period_start_date, previous_period_end_date, previous_year_start_date, previous_year_end_date

# Function to determine keyword type
def keyword_type(query, brand_terms):
    if not brand_terms:  # If brand_terms is an empty list
        return 'Branded'
    
    for term in brand_terms:
        if term in query:
            return 'Branded'
    
    return 'Non Branded'


def escape_special_chars(url):
    return re.escape(url)

def generate_regex_from_urls(urls):
    # Escape special characters in URLs
    escaped_urls = [escape_special_chars(url) for url in urls]
    
    # Construct the regex pattern
    expression_string = ""
    for i, url in enumerate(escaped_urls):
        if i == len(escaped_urls) - 1:
            # Last URL, do not add the '|' at the end
            expression_string += url + "$"
        else:
            expression_string += url + "$|"
    
    return expression_string

