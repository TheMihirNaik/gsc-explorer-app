import flask
import requests
from flask import render_template, request, url_for, redirect, flash, session
from app import app

# google auth related
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
import google.auth.transport.requests

import pandas as pd
import os

# This variable specifies the name of a file that contains the OAuth 2.0
# information for this application, including its client_id and client_secret.
CLIENT_SECRETS_FILE = "client_secrets.json"

# This OAuth 2.0 access scope allows for full read/write access to the
# authenticated user's account and requires requests to use an SSL connection.
SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly', 'https://www.googleapis.com/auth/webmasters']
API_SERVICE_NAME = 'searchconsole'
API_VERSION = 'v1'


@app.route('/gsc_test')
def test_api_request():
  if 'credentials' not in flask.session:
    return flask.redirect('gsc_authorize')

  # Load credentials from the session.
  credentials = google.oauth2.credentials.Credentials(
      **flask.session['credentials'])

  # Retrieve list of properties in account
  search_console_service = googleapiclient.discovery.build(
      API_SERVICE_NAME, API_VERSION, credentials=credentials)
  
  site_list = search_console_service.sites().list().execute()

  # Filter for verified URL-prefix websites.
  verified_sites_urls = [s['siteUrl'] for s in site_list['siteEntry']
                        if s['permissionLevel'] != 'siteUnverifiedUser'
                        and s['siteUrl'].startswith('http')]

  # Print the sitemaps for all websites that you can access.
  results = '<!DOCTYPE html><html><body><table><tr><th>Verified site</th><th>Sitemaps</th></tr>'
  for site_url in verified_sites_urls:

    # Retrieve list of sitemaps submitted
    sitemaps = search_console_service.sitemaps().list(siteUrl=site_url).execute()
    results += '<tr><td>%s</td>' % (site_url)

    # Add a row with the site and the list of sitemaps
    if 'sitemap' in sitemaps:
      sitemap_list = "<br />".join([s['path'] for s in sitemaps['sitemap']])
    else:
      sitemap_list = "<i>None</i>"
    results += '<td>%s</td></tr>' % (sitemap_list)

  results += '</table></body></html>'

  # Save credentials back to session in case access token was refreshed.
  # ACTION ITEM: In a production app, you likely want to save these
  #              credentials in a persistent database instead.
  flask.session['credentials'] = credentials_to_dict(credentials)

  return results

@app.route('/gsc_authorize')
def gsc_authorize():
  try:
    # Verify client_secrets.json exists
    if not os.path.exists(CLIENT_SECRETS_FILE):
      app.logger.error(f"OAuth authorization error: Client secrets file not found at {CLIENT_SECRETS_FILE}")
      flash("Authentication failed. Server configuration error. Please contact support.")
      return flask.redirect(url_for('home'))
      
    # Create flow instance to manage the OAuth 2.0 Authorization Grant Flow steps.
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES)

    # Get the current URL scheme and host
    scheme = request.headers.get('X-Forwarded-Proto', 'https')
    host = request.headers.get('X-Forwarded-Host', request.host)
    
    # Log the redirect URI being used
    redirect_uri = f"{scheme}://{host}{url_for('gsc_oauth2callback')}"
    app.logger.info(f"Using redirect URI: {redirect_uri}")
    
    # Set the redirect URI
    flow.redirect_uri = redirect_uri

    authorization_url, state = flow.authorization_url(
        # Enable offline access so that you can refresh an access token without
        # re-prompting the user for permission. Recommended for web server apps.
        access_type='offline',
        # Add prompt to ensure we always get a refresh token
        prompt='consent')

    # Store the state so the callback can verify the auth server response.
    flask.session['state'] = state
    app.logger.info(f"Stored state in session: {state}")
    
    # Make the session permanent to avoid early expiration
    session.permanent = True
    
    return flask.redirect(authorization_url)
  except Exception as e:
    app.logger.error(f"OAuth authorization error: {str(e)}", exc_info=True)
    flash(f"Authentication failed. Please try again. (Error: {str(e)})")
    return flask.redirect(url_for('home'))

@app.route('/gsc_oauth2callback')
def gsc_oauth2callback():
  # Specify the state when creating the flow in the callback so that it can
  # verified in the authorization server response.
  """
  Handles the OAuth 2.0 callback from Google Search Console.

  The state parameter from the session is used to create the flow instance
  so that the authorization server response can be verified.

  The authorization server's response is used to fetch the OAuth 2.0 tokens.

  The credentials are stored in the session.

  Redirects to the gsc property selection page.
  """
  try:
    # Check if state exists in session
    if 'state' not in flask.session:
      app.logger.error("OAuth callback error: 'state' not in session")
      flash("Authentication failed. Please try again. (Error: Session state missing)")
      return flask.redirect(url_for('home'))
      
    state = flask.session['state']
    
    # Check if the state parameter in the request matches the one in the session
    if request.args.get('state', '') != state:
      app.logger.error(f"OAuth callback error: State mismatch. Session: {state}, Request: {request.args.get('state', '')}")
      flash("Authentication failed. Please try again. (Error: State mismatch)")
      return flask.redirect(url_for('home'))

    # Verify client_secrets.json exists
    if not os.path.exists(CLIENT_SECRETS_FILE):
      app.logger.error(f"OAuth callback error: Client secrets file not found at {CLIENT_SECRETS_FILE}")
      flash("Authentication failed. Server configuration error. Please contact support.")
      return flask.redirect(url_for('home'))

    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
    
    # Get the current URL scheme and host
    scheme = request.headers.get('X-Forwarded-Proto', 'https')
    host = request.headers.get('X-Forwarded-Host', request.host)
    
    # Log the redirect URI being used
    redirect_uri = f"{scheme}://{host}{url_for('gsc_oauth2callback')}"
    app.logger.info(f"Using redirect URI: {redirect_uri}")
    
    # Set the redirect URI
    flow.redirect_uri = redirect_uri

    # Use the authorization server's response to fetch the OAuth 2.0 tokens.
    authorization_response = flask.request.url
    if scheme == 'https' and authorization_response.startswith('http:'):
      # Fix the scheme if needed
      authorization_response = 'https:' + authorization_response[5:]
      app.logger.info(f"Modified authorization response to use HTTPS: {authorization_response}")
    
    flow.fetch_token(authorization_response=authorization_response)

    # Store credentials in the session.
    # ACTION ITEM: In a production app, you likely want to save these
    #              credentials in a persistent database instead.
    credentials = flow.credentials
    flask.session['credentials'] = credentials_to_dict(credentials)
    app.logger.info("Successfully stored credentials in session")

    return flask.redirect(url_for('gsc_property_selection'))
  except Exception as e:
    # Log the exception
    app.logger.error(f"OAuth callback error: {str(e)}", exc_info=True)
    
    # Clear any partial session data
    if 'state' in flask.session:
      del flask.session['state']
    if 'credentials' in flask.session:
      del flask.session['credentials']
    
    flash(f"Authentication failed. Please try again. (Error: {str(e)})")
    return flask.redirect(url_for('home'))

@app.route('/gsc_revoke')
def revoke():
  if 'credentials' not in flask.session:
    return redirect(url_for('home'))

  credentials = google.oauth2.credentials.Credentials(
    **flask.session['credentials'])

  revoke = requests.post('https://oauth2.googleapis.com/revoke',
      params={'token': credentials.token},
      headers = {'content-type': 'application/x-www-form-urlencoded'})

  status_code = getattr(revoke, 'status_code')

  if status_code == 200:
    flash('Your GSC credentials are revoked.')
    return redirect(url_for('dashboard'))
  else:
    return redirect(url_for('home'))

@app.route('/gsc_clear')
def clear_credentials():
  if 'credentials' in flask.session:
    del flask.session['credentials']
  flash('Your Session Cookies are cleared.')
  return redirect(url_for('home'))

@app.route('/revoke-gsc-clear-session')
def revoke_gsc_clear_session():
  if 'credentials' not in flask.session:
    return redirect(url_for('home'))
  
  credentials = google.oauth2.credentials.Credentials(
    **flask.session['credentials'])

  revoke = requests.post('https://oauth2.googleapis.com/revoke',
      params={'token': credentials.token},
      headers = {'content-type': 'application/x-www-form-urlencoded'})

  status_code = getattr(revoke, 'status_code')

  if status_code == 200:
    del flask.session['credentials']
    session.clear()
    flash('Your GSC Access has been revoked, and your Session Cookies are cleared.')
    return redirect(url_for('home'))
  else:
    del flask.session['credentials']
    session.clear()
    return redirect(url_for('home'))

  
def credentials_to_dict(credentials):
  return {'token': credentials.token,
          'refresh_token': credentials.refresh_token,
          'token_uri': credentials.token_uri,
          'client_id': credentials.client_id,
          'client_secret': credentials.client_secret,
          'scopes': credentials.scopes}

def check_and_refresh_credentials():
  """
  Helper function to check if credentials are valid and refresh them if needed.
  Returns:
    - (credentials, None) if credentials are valid
    - (None, redirect_response) if there's an issue and user should be redirected
  """
  if 'credentials' not in flask.session:
    return None, redirect(url_for('gsc_authorize'))
  
  try:
    credentials = google.oauth2.credentials.Credentials(
      **flask.session['credentials'])
    
    # Check if the token is expired and refresh it if needed
    if not credentials.valid and credentials.expired and credentials.refresh_token:
      try:
        credentials.refresh(google.auth.transport.requests.Request())
        # Save updated credentials back to session
        flask.session['credentials'] = credentials_to_dict(credentials)
      except Exception as e:
        # If refresh fails, clear session and redirect to auth
        if 'credentials' in flask.session:
          del flask.session['credentials']
        flash("Your session has expired. Please log in again.")
        return None, redirect(url_for('gsc_authorize'))
    
    # Test the credentials with a simple API call
    search_console_service = googleapiclient.discovery.build(
      API_SERVICE_NAME, API_VERSION, credentials=credentials)
    # Simple API call to verify credentials work
    search_console_service.sites().list().execute()
    
    return credentials, None
  
  except Exception as e:
    # If any error occurs with credentials, clear session and redirect to auth
    if 'credentials' in flask.session:
      del flask.session['credentials']
    flash("There was an issue with your authentication. Please log in again.")
    return None, redirect(url_for('gsc_authorize'))

def print_index_table():
  return ('<table>' +
          '<tr><td><a href="/gsc_test">Test an API request</a></td>' +
          '<td>Submit an API request and see a formatted JSON response. ' +
          '    Go through the authorization flow if there are no stored ' +
          '    credentials for the user.</td></tr>' +
          '<tr><td><a href="/gsc_authorize">Test the auth flow directly</a></td>' +
          '<td>Go directly to the authorization flow. If there are stored ' +
          '    credentials, you still might not be prompted to reauthorize ' +
          '    the application.</td></tr>' +
          '<tr><td><a href="/gsc_revoke">Revoke current credentials</a></td>' +
          '<td>Revoke the access token associated with the current user ' +
          '    session. After revoking credentials, if you go to the test ' +
          '    page, you should see an <code>invalid_grant</code> error.' +
          '</td></tr>' +
          '<tr><td><a href="/gsc_clear">Clear Flask session credentials</a></td>' +
          '<td>Clear the access token currently stored in the user session. ' +
          '    After clearing the token, if you <a href="/test">test the ' +
          '    API request</a> again, you should go back to the auth flow.' +
          '</td></tr></table>')

def build_gsc_service():
  # Load credentials from the session
  credentials = google.oauth2.credentials.Credentials(
      **flask.session['credentials'])
  
  print(flask.session['credentials'])

  # Check if the token is expired and refresh it if needed
  if not credentials.valid and credentials.expired and credentials.refresh_token:
      try:
          credentials.refresh(google.auth.transport.requests.Request())
      except Exception as e:
          flash("Failed to refresh access token. Please reauthorize.")
          return flask.redirect(url_for('gsc_authorize'))

      # Save updated credentials back to session
      flask.session['credentials'] = credentials_to_dict(credentials)

  # Build the Google Search Console API service
  search_console_service = googleapiclient.discovery.build(
      API_SERVICE_NAME, API_VERSION, credentials=credentials)
  
  return search_console_service

def fetch_search_console_data(webmasters_service, website_url, start_date, end_date, dimensions, dimensionFilterGroups):
    # Initialize an empty list to store the rows from the response
    all_responses = []
    
    # Initialize the start row to 0
    start_row = 0
    
    # Loop until all rows have been retrieved
    while True:
        # Build the request body for the API call
        request_body = {
            "type" : "web",
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "dimensionFilterGroups": dimensionFilterGroups,
            "rowLimit": 25000,
            "dataState": "final",
            'startRow': start_row,
            #'aggregationType': 'byPage',
        }
       
        # Call the API with the request body
        response_data = webmasters_service.searchanalytics().query(siteUrl=website_url, body=request_body).execute()

        #print("Response Data")
        #print(response_data)

        # Check if 'rows' is in the response data
        if 'rows' not in response_data:
            break

        # Append the rows from the response to the all_responses list
        for row in response_data['rows']:
            # Create a temporary list to hold the values for the row
            temp = []
            # Extract the values for the keys (dimensions)
            for key in row['keys']:
                temp.append(key)
            # Extract the values for clicks, impressions, CTR, and position
            temp.append(row['clicks'])
            temp.append(row['impressions'])
            temp.append(row['ctr'])
            temp.append(row['position'])
            # Append the row to the all_responses list
            all_responses.append(temp)
            #print(all_responses)
        
        # Update the start row to reflect the number of rows retrieved
        start_row += len(response_data['rows'])
        
        # Print a progress message
        print("fetched up to " + str(start_row) + " rows of data")

        # Check if the number of rows retrieved is less than the row limit
        if len(response_data['rows']) < 25000:
            break

    # Create a DataFrame from the all_responses list, with columns corresponding to the requested dimensions and metrics
    df = pd.DataFrame(all_responses, columns=dimensions + ['clicks', 'impressions', 'ctr', 'position'])
    
    # Return the DataFrame
    return df
