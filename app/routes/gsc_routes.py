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
        # Load credentials from the session. Use the helper so the client
        # secret -- kept out of the session cookie on purpose -- is re-attached
        # server-side; without it a refresh can never succeed.
        credentials = credentials_from_session()

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
        # A query is non-branded until a brand term proves otherwise. Defaulting
        # the other way labelled 100% of traffic as branded whenever the user
        # had not configured any keywords, leaving every Non-Brand figure at 0.
        return 'Non Branded'
    
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


def get_data_freshness(service, property_url):
    """How current this property's data is, from the API's own metadata.

    A `dataState: 'all'` response carries `metadata.firstIncompleteDate` -- the
    first day Google is still collecting. The day before it is the last day
    whose numbers will not move again, which is what a date picker should
    default to; the newest row is how fresh the preliminary data runs.

    Returns {'final_date', 'fresh_date'}. Both fall back to two days ago, which
    is roughly Search Console's usual lag, if the call fails.
    """
    fallback = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    freshness = {'final_date': fallback, 'fresh_date': fallback}

    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=10)

        request_body = {
            'startDate': start_date.strftime('%Y-%m-%d'),
            'endDate': end_date.strftime('%Y-%m-%d'),
            'dimensions': ['date'],
            'dataState': 'all',  # so the response carries freshness metadata
            'rowLimit': 25
        }

        response = service.searchanalytics().query(siteUrl=property_url, body=request_body).execute()

        dates = sorted(row['keys'][0] for row in response.get('rows') or [])
        if dates:
            freshness['fresh_date'] = dates[-1]
            # Nothing in the window is still being collected unless the
            # metadata below says so, in which case every row is already final.
            freshness['final_date'] = dates[-1]

        first_incomplete = (response.get('metadata') or {}).get('firstIncompleteDate')
        if first_incomplete:
            try:
                incomplete = datetime.strptime(first_incomplete, '%Y-%m-%d')
                freshness['final_date'] = (incomplete - timedelta(days=1)).strftime('%Y-%m-%d')
            except ValueError:
                logger.warning(
                    "Unparseable firstIncompleteDate %r for %s",
                    first_incomplete, property_url)

    except Exception as e:
        logger.error(
            f"Error fetching data freshness for {property_url}: {e}", exc_info=True)

    return freshness


def get_latest_available_date(service, property_url):
    """Latest date with final (non-preliminary) data for this property."""
    return get_data_freshness(service, property_url)['final_date']


# GSC advances the latest available date roughly once a day, so querying it on
# every page render spends a round trip on a value that has not moved.
LATEST_DATE_CACHE_TTL = timedelta(hours=6)


def get_cached_freshness(property_url, service=None):
    """Data freshness for a property, cached per property in the session.

    Falls back to a live query on a miss. `service` is reused when the caller
    already has one, so a miss costs no extra discovery build.
    """
    cache = session.get('latest_date_cache')
    if cache and cache.get('property') == property_url and cache.get('date'):
        try:
            fetched_at = datetime.fromisoformat(cache['fetched_at'])
        except (KeyError, TypeError, ValueError):
            fetched_at = None
        if fetched_at and datetime.now() - fetched_at < LATEST_DATE_CACHE_TTL:
            return {
                'final_date': cache['date'],
                # Sessions written before fresh_date existed only carry one date.
                'fresh_date': cache.get('fresh_date', cache['date']),
            }

    if service is None:
        service = build_gsc_service()

    freshness = get_data_freshness(service, property_url)
    session['latest_date_cache'] = {
        'property': property_url,
        'date': freshness['final_date'],
        'fresh_date': freshness['fresh_date'],
        'fetched_at': datetime.now().isoformat(),
    }
    return freshness


def peek_cached_freshness(property_url):
    """Freshness from the session cache only -- never makes an API call.

    For render paths (the property card on every page) that want to show the
    dates but must not spend a round trip to do it.
    """
    cache = session.get('latest_date_cache')
    if cache and cache.get('property') == property_url and cache.get('date'):
        return {
            'final_date': cache['date'],
            'fresh_date': cache.get('fresh_date', cache['date']),
        }
    return None


def get_cached_latest_date(property_url, service=None):
    """Latest date with final data, cached per property in the session."""
    return get_cached_freshness(property_url, service)['final_date']


def report_errors(view):
    """Turn an unhandled failure in a report into a message, not a 500.

    Report POSTs return HTML fragments that HTMX swaps into the page, so an
    exception gives the user a spinner that stops and nothing else -- the
    traceback goes to the log and the page just sits there. Search Console
    fails for ordinary reasons (rate limits, a permission that changed, a
    regex it will not accept), so those need to reach the person who can act
    on them.

    Reauthorization is deliberately not caught here: GSCReauthRequired has its
    own handler that redirects into the OAuth flow.
    """
    from functools import wraps

    @wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except GSCReauthRequired:
            raise
        except Exception as exc:
            logger.error("Report %s failed: %s", view.__name__, exc, exc_info=True)
            message = str(exc)
            if 'quota' in message.lower() or 'rate limit' in message.lower():
                hint = ("Search Console is rate-limiting this property. "
                        "Wait a minute and try a shorter date range.")
            elif 'filter' in message.lower() or 'expression' in message.lower():
                hint = ("Search Console rejected a filter. If you applied a "
                        "segment, check its pattern on the Segments page.")
            else:
                hint = "Try a shorter date range, or reload the page."
            return render_template('/partials/report-error.html',
                                   message=message, hint=hint)

    return wrapper
