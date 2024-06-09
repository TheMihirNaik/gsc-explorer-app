from flask import request, render_template, session, redirect, url_for, jsonify, flash
from app import app, client, VALUESERP_API_KEY
import requests

def scrape_serps(api_key, keyword, location, country, language):
  
  print(api_key)
  # set up the request parameters
  params = {
  'api_key': api_key,
  'q': keyword,
  'location': location,
  'gl': country,
  'hl': language,
  'num' : 11
  }

  # make the http GET request to VALUE SERP
  serp_result = requests.get('https://api.valueserp.com/search', params).json()

  return serp_result

@app.route('/valueserp-api/', methods=['POST', 'GET'])
def valueserp_api():
    # POST request
    if request.method == 'POST':
        keyword = request.form.get('keyword')
        location = request.form.get('location')
        country = request.form.get('country')
        language = request.form.get('language')

        serp_data = scrape_serps(VALUESERP_API_KEY, keyword, location, country, language)

        serp_data_json = jsonify(serp_data)

        return render_template('/integrations/valueserp-api/valueserp-api-response-fragment.html', serp_data_json=serp_data_json, serp_data=serp_data)
    
    # GET request
    if 'email' in session:
      #user is logged in
      return render_template('/integrations/valueserp-api/valueserp-api-example.html')
   
    # if email is not in session
    flash('Please Sign In.')
    return redirect(url_for('signin'))
