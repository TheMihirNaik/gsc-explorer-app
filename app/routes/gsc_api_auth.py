import flask
import requests
from flask import render_template, request, url_for, redirect, flash, session
from app import app

# google auth related
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery

import pandas as pd

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
  # Create flow instance to manage the OAuth 2.0 Authorization Grant Flow steps.
  flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
      CLIENT_SECRETS_FILE, scopes=SCOPES)

  # The URI created here must exactly match one of the authorized redirect URIs
  # for the OAuth 2.0 client, which you configured in the API Console. If this
  # value doesn't match an authorized URI, you will get a 'redirect_uri_mismatch'
  # error.
  flow.redirect_uri = flask.url_for('gsc_oauth2callback', _external=True, _scheme='https')

  authorization_url, state = flow.authorization_url(
      # Enable offline access so that you can refresh an access token without
      # re-prompting the user for permission. Recommended for web server apps.
      access_type='offline',
      # Enable incremental authorization. Recommended as a best practice.
      include_granted_scopes='true')

  # Store the state so the callback can verify the auth server response.
  flask.session['state'] = state

  return flask.redirect(authorization_url)

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
  state = flask.session['state']

  flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
      CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
  
  flow.redirect_uri = flask.url_for('gsc_oauth2callback', _external=True, _scheme='https')

  # Use the authorization server's response to fetch the OAuth 2.0 tokens.
  authorization_response = flask.request.url
  flow.fetch_token(authorization_response=authorization_response)

  # Store credentials in the session.
  # ACTION ITEM: In a production app, you likely want to save these
  #              credentials in a persistent database instead.
  credentials = flow.credentials
  flask.session['credentials'] = credentials_to_dict(credentials)

  return flask.redirect(url_for('gsc_property_selection'))

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
  # Load credentials from the session.
  credentials = google.oauth2.credentials.Credentials(
      **flask.session['credentials'])

  # Retrieve list of properties in account
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
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "dimensionFilterGroups": dimensionFilterGroups,
            "rowLimit": 25000,
            "dataState": "final",
            'startRow': start_row,
            'aggregationType': 'byPage',
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
