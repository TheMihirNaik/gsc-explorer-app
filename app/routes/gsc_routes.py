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

from dateutil.relativedelta import relativedelta

def process_dates(start_date_str, end_date_str):
    current_period_start_date = start_date_str
    current_period_end_date = end_date_str

    current_start_date, current_end_date = format_dates(current_period_start_date, current_period_end_date)

    if current_start_date is None or current_end_date is None:
        return None, None, None, None, None, None

    current_start_date_obj = datetime.strptime(current_start_date, '%Y-%m-%d')
    current_end_date_obj = datetime.strptime(current_end_date, '%Y-%m-%d')

    # Calculate duration of the current period
    current_period_duration = (current_end_date_obj - current_start_date_obj).days + 1

    # Previous period start date and end date
    previous_period_start_date = (current_start_date_obj - timedelta(days=current_period_duration)).strftime('%Y-%m-%d')
    previous_period_end_date = (current_end_date_obj - timedelta(days=current_period_duration)).strftime('%Y-%m-%d')

    # Previous year start date and end date
    previous_year_start_date = (current_start_date_obj - relativedelta(years=1)).strftime('%Y-%m-%d')
    previous_year_end_date = (current_end_date_obj - relativedelta(years=1)).strftime('%Y-%m-%d')

    return current_start_date, current_end_date, previous_period_start_date, previous_period_end_date, previous_year_start_date, previous_year_end_date

# Function to determine keyword type
def keyword_type(query, brand_terms):
    if not brand_terms or brand_terms == "You haven't selected Brand Keywords.":
        return 'Branded'  # Default to branded if no brand terms defined
    
    # Convert query to lowercase for case-insensitive matching
    query_lower = query.lower()
    
    # If brand_terms is a string (comma-separated), convert it to a list
    if isinstance(brand_terms, str):
        brand_terms = [term.strip().lower() for term in brand_terms.split(',')]
    
    # Check each brand term
    for term in brand_terms:
        # Skip empty terms
        if not term:
            continue
            
        # Convert term to lowercase for case-insensitive matching
        term_lower = term.strip().lower()
        
        # Check if the term is in the query as a whole word
        # This prevents matching substrings (e.g., "apple" shouldn't match "pineapple")
        if re.search(r'\b' + re.escape(term_lower) + r'\b', query_lower):
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


def get_latest_available_date(service, property_url):
    """
    Queries GSC API to find the latest available data date.
    Checks the last 10 days including 'all' data state (fresh data).
    """
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=10)
        
        request_body = {
            'startDate': start_date.strftime('%Y-%m-%d'),
            'endDate': end_date.strftime('%Y-%m-%d'),
            'dimensions': ['date'],
            'dataState': 'all',  # fetch fresh data if available
            'rowLimit': 25
        }
        
        response = service.searchAnalytics().query(siteUrl=property_url, body=request_body).execute()
        
        if 'rows' in response:
            dates = [row['keys'][0] for row in response['rows']]
            if dates:
                return max(dates)
                
    except Exception as e:
        logger.error(f"Error fetching latest date for {property_url}: {e}")
    
    # Fallback: 2 days ago if API fails or returns no data
    return (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
