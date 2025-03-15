from flask import render_template, request, url_for, redirect, flash, session, jsonify
from app import app
import bcrypt
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
from app.routes.gsc_api_auth import * 
from app.routes.gsc_routes import *
#from app.routes.openai import *
import plotly.express as px
from app.tasks.celery_tasks import *
from app.tasks.task_status import task_status
from bs4 import BeautifulSoup
from collections import Counter
from nltk.corpus import stopwords
import nltk
nltk.download('stopwords')
from openai import OpenAI
import google.auth.transport.requests
import pandas as pd
import flask
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask template filters
@app.template_filter('format_number')
def format_number(value):
    # Assuming value is a number or can be converted to a number
    return '{:,.0f}'.format(float(value))

# Homepage
@app.route('/')
def home():
    return render_template('/default/homepage.html')

#Dashboard
@app.route('/dashboard/')
def dashboard():
    # Check and refresh credentials
    credentials, redirect_response = check_and_refresh_credentials()
    if redirect_response:
        return redirect_response
    
    selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

    # if GSC property is not selected then send user to GSC property selection page
    if selected_property == "You haven't selected a GSC Property yet":
        # show a message
        flash('Please Select your GSC Property.')
        return redirect(url_for('gsc_property_selection'))
    
    return render_template('/default/dashboard.html', 
                           selected_property=selected_property,
                           brand_keywords=brand_keywords)

@app.route('/gsc-property-selection/', methods=['GET', 'POST'])
def gsc_property_selection():
    if request.method == 'POST':
        #save the selected website and country in session
        selected_property = request.form.get('selected_property')
        brand_keywords_list_input = request.form.get('brand_keywords')
        # Trim whitespace and remove any trailing commas
        brand_keywords = [kw.strip() for kw in brand_keywords_list_input.split(",") if kw.strip()]

        session['selected_property'] = selected_property
        session['brand_keywords'] = brand_keywords

        return redirect(url_for('dashboard'))
    
    # Check and refresh credentials
    credentials, redirect_response = check_and_refresh_credentials()
    if redirect_response:
        return redirect_response
    
    try:
        # Retrieve list of properties in account
        search_console_service = googleapiclient.discovery.build(
            API_SERVICE_NAME, API_VERSION, credentials=credentials)
        
        site_list = search_console_service.sites().list().execute()
        
        site_list = site_list['siteEntry']

        # exlude sites that are not verified
        site_list = [s for s in site_list if s['permissionLevel'] != 'siteUnverifiedUser']

        site_list_sorted = []

        for each in site_list:
            site_list_sorted.append(each['siteUrl'])

        site_list_sorted = sorted(site_list_sorted)

        selected_property = session.get("selected_property", "Please Select your GSC Property.")
        
    except Exception as e:
        # If any error occurs with credentials, clear session and redirect to auth
        if 'credentials' in session:
            del session['credentials']
        flash("There was an issue with your authentication. Please log in again.")
        return redirect(url_for('gsc_authorize'))

    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

    brand_keywords_string = ''

    if len(brand_keywords) == 1:
        brand_keywords_string = brand_keywords[0]
    elif brand_keywords == "You haven't selected Brand Keywords.":
        brand_keywords_string = ""
    else:
        for each in brand_keywords:
            brand_keywords_string = brand_keywords_string + each + ','

    return render_template('/gsc-property-selection.html', 
                           site_list=site_list_sorted,
                           selected_property=selected_property,
                           brand_keywords_string=brand_keywords_string)

@app.route('/suggest-brand-keywords/', methods=['POST'])
def suggest_brand_keywords():
    if 'credentials' not in session:
        return jsonify({'error': 'Not authenticated with Google Search Console'}), 401
    
    selected_property = request.json.get('selected_property')
    if not selected_property:
        return jsonify({'error': 'No property selected'}), 400
    
    # Load credentials from the session
    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    
    # Check if the token is expired and refresh it if needed
    if not credentials.valid and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(google.auth.transport.requests.Request())
            # Save updated credentials back to session
            session['credentials'] = credentials_to_dict(credentials)
        except Exception as e:
            return jsonify({'error': 'Failed to refresh access token'}), 401
    
    # Build the Search Console service
    search_console_service = googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials=credentials)
    
    # Get the last 90 days of data
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    
    try:
        # Fetch search query data
        query_data = fetch_search_console_data(
            search_console_service, 
            selected_property, 
            start_date, 
            end_date, 
            ['query'], 
            []
        )
        
        # Process the data to identify potential brand keywords
        if query_data.empty:
            return jsonify({'suggested_keywords': []}), 200
        
        # Filter for queries with significant data
        # Require at least 10 impressions to be considered
        filtered_data = query_data[query_data['impressions'] >= 10]
        
        if filtered_data.empty:
            return jsonify({'suggested_keywords': []}), 200
        
        # Sort by CTR (descending) as brand terms typically have higher CTR
        sorted_data = filtered_data.sort_values(by='ctr', ascending=False)
        
        # Take the top 10 queries by CTR
        top_queries = sorted_data.head(10)
        
        # Extract domain name from the property URL to use as a baseline brand term
        domain = selected_property.replace('sc-domain:', '').replace('https://', '').replace('http://', '').split('/')[0]
        domain_parts = domain.split('.')
        if len(domain_parts) > 1:
            base_domain = domain_parts[-2]  # Get the main part of the domain (e.g., 'example' from 'example.com')
            
            # Add the base domain to our suggested keywords if it's not already in the top queries
            if not any(base_domain.lower() in query.lower() for query in top_queries['query'].tolist()):
                suggested_keywords = [base_domain] + top_queries['query'].tolist()
            else:
                suggested_keywords = top_queries['query'].tolist()
        else:
            suggested_keywords = top_queries['query'].tolist()
        
        return jsonify({'suggested_keywords': suggested_keywords}), 200
    
    except Exception as e:
        logger.error(f"Error suggesting brand keywords: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Charts Routes
@app.route('/charts/sitewide-brand-vs-non-brand/', methods=['GET', 'POST'])
def sitewide_analysis():
    if 'credentials' not in session:
        # GSC is not logged in.
        return redirect(url_for('gsc_authorize'))
    
    if request.method == 'POST':
        selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
        brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

        webmasters_service = build_gsc_service()

        # Get today's date
        today = datetime.now().date()

        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')

        start_date_formatted, end_date_formatted = format_dates(start_date_str, end_date_str)

        #total numbers make GSC API Call
        country = []
        dimensions = ['DATE']
        dimensionFilterGroups = [
            #{"filters": [
            #{"dimension": "COUNTRY", "expression": country, "operator": "equals"},
        #]}
        ]
        
        gsc_data = fetch_search_console_data(webmasters_service, selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups)
        
        # get earliest and latest date from gsc_data
        earliest_date = gsc_data['DATE'].min()
        latest_date = gsc_data['DATE'].max()

        #total numbers
        total_clicks = gsc_data['clicks'].sum()
        total_impressions = gsc_data['impressions'].sum()
        total_ctr = total_clicks / total_impressions * 100
        total_position = gsc_data['position'].mean()

        total_data = [total_clicks, total_impressions, total_ctr, total_position]

        #total numbers make GSC API Call
        q_dimensions = ['date', 'query'] 

        query_df = fetch_search_console_data(
            webmasters_service, selected_property, start_date_formatted, end_date_formatted, q_dimensions, dimensionFilterGroups)

        #print(query_df)

        # Applying the function to the DataFrame
        query_df['Query Type'] = query_df['query'].apply(lambda x: keyword_type(x, brand_keywords))

        #prepare a dataframe to plot a chart - groupby

        plot_df = query_df.groupby(['Query Type']).agg(
            clicks = ('clicks', 'sum'),
            impressions = ('impressions', 'sum'),
            ctr = ('ctr', 'mean'),
            position = ('position', 'mean'),
            count_queries = ('query', 'count'),
        ).reset_index()

        date_plot_df = query_df.groupby(['date', 'Query Type']).agg(
            clicks = ('clicks', 'sum'),
            impressions = ('impressions', 'sum'),
            ctr = ('ctr', 'mean'),
            position = ('position', 'mean'),
            count_queries = ('query', 'count'),
        ).reset_index()

        #print(date_plot_df)




        clicks_fig = px.line(date_plot_df, x="date", y='clicks', color='Query Type')

        # Customize the layout
        clicks_fig.update_layout(
            plot_bgcolor='#F1F1F1',  # Set the background color of the plot area
            paper_bgcolor='#F1F1F1',     # Set the background color of the entire figure
            #title='Customized Background Chart',  # Set the chart title
            #xaxis_title='Sepal Length',            # Set the x-axis title
            #yaxis_title='Sepal Width'              # Set the y-axis title
        )


        clicks_graph = clicks_fig.to_html()

        impressions_fig = px.line(date_plot_df, x="date", y='impressions', color='Query Type')
        # Customize the layout
        impressions_fig.update_layout(
            plot_bgcolor='#F1F1F1',  # Set the background color of the plot area
            paper_bgcolor='#F1F1F1',     # Set the background color of the entire figure
            #title='Customized Background Chart',  # Set the chart title
            #xaxis_title='Sepal Length',            # Set the x-axis title
            #yaxis_title='Sepal Width'              # Set the y-axis title
        )
        impressions_graph = impressions_fig.to_html()

        ctr_fig = px.line(date_plot_df, x="date", y='ctr', color='Query Type')

        # Customize the layout
        ctr_fig.update_layout(
            plot_bgcolor='#F1F1F1',  # Set the background color of the plot area
            paper_bgcolor='#F1F1F1',     # Set the background color of the entire figure
            #title='Customized Background Chart',  # Set the chart title
            #xaxis_title='Sepal Length',            # Set the x-axis title
            #yaxis_title='Sepal Width'              # Set the y-axis title
        )


        ctr_fig_graph = ctr_fig.to_html()


        position_fig = px.line(date_plot_df, x="date", y='position', color='Query Type')

        # Customize the layout
        position_fig.update_layout(
            plot_bgcolor='#F1F1F1',  # Set the background color of the plot area
            paper_bgcolor='#F1F1F1',     # Set the background color of the entire figure
            #title='Customized Background Chart',  # Set the chart title
            #xaxis_title='Sepal Length',            # Set the x-axis title
            #yaxis_title='Sepal Width'              # Set the y-axis title
        )


        position_fig_graph = position_fig.to_html()



        # Query Count : For Brand Queries

        brand_query_count_df = date_plot_df[date_plot_df['Query Type'] == 'Branded']

        brand_query_count_fig = px.bar(brand_query_count_df, x="date", y='count_queries', color='Query Type')
        
        # Customize the layout
        brand_query_count_fig.update_layout(
            plot_bgcolor='#F1F1F1',  # Set the background color of the plot area
            paper_bgcolor='#F1F1F1',     # Set the background color of the entire figure
            #title='Customized Background Chart',  # Set the chart title
            #xaxis_title='Sepal Length',            # Set the x-axis title
            #yaxis_title='Sepal Width'              # Set the y-axis title
        )
        brand_query_count_graph = brand_query_count_fig.to_html()

        # Query Count : For Non Brand Queries

        non_brand_query_count_df = date_plot_df[date_plot_df['Query Type'] == 'Non Branded']

        non_brand_query_count_fig = px.bar(non_brand_query_count_df, x="date", y='count_queries', color='Query Type')
        
        # Customize the layout
        non_brand_query_count_fig.update_layout(
            plot_bgcolor='#F1F1F1',  # Set the background color of the plot area
            paper_bgcolor='#F1F1F1',     # Set the background color of the entire figure
            #title='Customized Background Chart',  # Set the chart title
            #xaxis_title='Sepal Length',            # Set the x-axis title
            #yaxis_title='Sepal Width'              # Set the y-axis title
        )
        non_brand_query_count_graph = non_brand_query_count_fig.to_html()


        # query count by position buckets

        # Define a function to categorize the positions
        def categorize_position(position):
            if position < 3:
                return "1-3"
            elif 3 <= position < 5:
                return "3-5"
            elif 5 <= position < 10:
                return "5-10"
            else:
                return "10+"

        # Apply the function to the 'position' column and create a new column 'Position Buckets'
        query_df['Position Buckets'] = query_df['position'].apply(categorize_position)

        #group position buckets
        position_bucket_df = query_df.groupby(['date', 'Position Buckets', 'Query Type']).agg(
            clicks = ('clicks', 'sum'),
            impressions = ('impressions', 'sum'),
            ctr = ('ctr', 'mean'),
            position = ('position', 'mean'),
            count_queries = ('clicks', 'count')
        ).reset_index()

        # Convert the 'Position Buckets' column to a categorical type with the desired order
        position_order = ["1-3", "3-5", "5-10", "10+"]
        position_bucket_df['Position Buckets'] = pd.Categorical(position_bucket_df['Position Buckets'], categories=position_order, ordered=True)


        brand_position_bucket_fig = px.bar(position_bucket_df[position_bucket_df['Query Type'] == 'Branded'], 
                                     x="date", y='count_queries',
                                     category_orders={"Position Buckets": position_order},
                                     color='Position Buckets')
        

        # Customize the layout
        brand_position_bucket_fig.update_layout(
            plot_bgcolor='#F1F1F1',  # Set the background color of the plot area
            paper_bgcolor='#F1F1F1',     # Set the background color of the entire figure
            #title='Customized Background Chart',  # Set the chart title
            #xaxis_title='Sepal Length',            # Set the x-axis title
            #yaxis_title='Sepal Width'              # Set the y-axis title
        )

        brand_position_bucket_graph = brand_position_bucket_fig.to_html()

        non_brand_position_bucket_fig = px.bar(position_bucket_df[position_bucket_df['Query Type'] == 'Non Branded'], 
                                     x="date", y='count_queries',
                                     category_orders={"Position Buckets": position_order},
                                     color='Position Buckets')
        
                # Customize the layout
        non_brand_position_bucket_fig.update_layout(
            plot_bgcolor='#F1F1F1',  # Set the background color of the plot area
            paper_bgcolor='#F1F1F1',     # Set the background color of the entire figure
            #title='Customized Background Chart',  # Set the chart title
            #xaxis_title='Sepal Length',            # Set the x-axis title
            #yaxis_title='Sepal Width'              # Set the y-axis title
        )

        non_brand_position_bucket_graph = non_brand_position_bucket_fig.to_html()

 

        brand_query_df = query_df[query_df['Query Type'] == 'Branded']

        brand_clicks = brand_query_df['clicks'].sum()
        brand_impressions = brand_query_df['impressions'].sum()
        brand_ctr = brand_clicks / brand_impressions * 100
        brand_position = brand_query_df['position'].mean()

        brand_query_count = brand_query_df['query'].nunique()

        brand_numbers = [brand_clicks, brand_impressions, brand_ctr, brand_position, brand_query_count]


        non_brand_query_df = query_df[query_df['Query Type'] == 'Non Branded']

        non_brand_clicks = non_brand_query_df['clicks'].sum()
        non_brand_impressions = non_brand_query_df['impressions'].sum()
        non_brand_ctr = non_brand_clicks / non_brand_impressions * 100
        non_brand_position = non_brand_query_df['position'].mean()

        try:
            non_brand_query_count = non_brand_query_df['query'].nunique()

        except KeyError:
            non_brand_query_count = 0  # or any default value you prefer

        non_brand_numbers = [non_brand_clicks, non_brand_impressions, non_brand_ctr, non_brand_position, non_brand_query_count]

        send_html = render_template('/sitewide-analysis/partial-gsc-data.html', 
                                    total_data=total_data, 
                                    brand_numbers=brand_numbers,
                                    non_brand_numbers=non_brand_numbers, 
                                    clicks_graph=clicks_graph,
                                    impressions_graph=impressions_graph,
                                    ctr_fig_graph=ctr_fig_graph,
                                    position_fig_graph=position_fig_graph,
                                    brand_query_count_graph=brand_query_count_graph,
                                    non_brand_query_count_graph=non_brand_query_count_graph,
                                    brand_position_bucket_graph=brand_position_bucket_graph,
                                    non_brand_position_bucket_graph=non_brand_position_bucket_graph,
                                    earliest_date=earliest_date,
                                    latest_date=latest_date
                                    )

        return send_html

    #get request
    selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

    # if GSC property is not selected then send user to GSC property selection page
    if selected_property == "You haven't selected a GSC Property yet":
        # show a message
        flash('Please Select your GSC Property.')
        return redirect(url_for('gsc_property_selection'))
    
    return render_template('/sitewide-analysis/mainpage.html', 
                           selected_property=selected_property,
                           brand_keywords=brand_keywords)


@app.route('/charts/organic-ctr/', methods=['GET', 'POST'])
def organic_ctr():
    if 'credentials' not in session:
        return redirect(url_for('gsc_authorize'))
    
    
    if request.method == 'POST':
        selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
        brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

        webmasters_service = build_gsc_service()

        start_date_str = request.form.get('start_date')
        #print(start_date_str)
        end_date_str = request.form.get('end_date')
        #print(end_date_str)
        country = request.form.get('country')
        #print(country)

        start_date_formatted, end_date_formatted = format_dates(start_date_str, end_date_str)

        #print(start_date_formatted)
        #print(end_date_formatted)

        dimensions = ['QUERY']
        
        dimensionFilterGroups = []
       
        if country != "All":
                    dimensionFilterGroups = [
            {"filters": [
            {"dimension": "COUNTRY", "expression": str(country), "operator": "equals"},
        ]}
        ]
                    
        #print(dimensionFilterGroups)
        
        query_df = fetch_search_console_data(webmasters_service, selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups)
        
        #print(query_df)

        # Calculate CTR
        #query_df['CTR'] = query_df['clicks'] / query_df['impressions'] * 100

        # Label queries
        query_df['Query Type'] = query_df['QUERY'].apply(lambda x: keyword_type(x, brand_keywords))

        # round the position number
        query_df['round_position'] = round(query_df['position'], 0)

        #print(query_df)

        brand_query_df = query_df[query_df['Query Type'] == 'Branded']
        #print(brand_query_df)
        non_brand_query_df = query_df[query_df['Query Type'] == 'Non Branded']

        # Ensure there is always a row for round_position between 1 to 10
        all_positions = pd.DataFrame({'round_position': range(1, 11)})

        # Grouping the data by position
        brand_ctr_df = brand_query_df.groupby(['round_position']).agg(
            clicks=('clicks', 'sum'),
            impressions=('impressions', 'sum')
        ).reset_index().merge(all_positions, on='round_position', how='right').fillna(0)

        # Grouping data by position for non_brand
        non_brand_ctr_df = non_brand_query_df.groupby(['round_position']).agg(
            clicks=('clicks', 'sum'),
            impressions=('impressions', 'sum')
        ).reset_index().merge(all_positions, on='round_position', how='right').fillna(0)

        # Calculate CTR
        brand_ctr_df['CTR'] = round(brand_ctr_df['clicks'] / brand_ctr_df['impressions'] * 100, 2)
        non_brand_ctr_df['CTR'] = round(non_brand_ctr_df['clicks'] / non_brand_ctr_df['impressions'] * 100, 2)

        # Only Top 10 Positions
        brand_ctr_df = brand_ctr_df[brand_ctr_df['round_position'] <= 10]
        non_brand_ctr_df = non_brand_ctr_df[non_brand_ctr_df['round_position'] <= 10]

        # Create a bar chart
        brand_ctr_fig = px.bar(brand_ctr_df, x='round_position', y='CTR',
                    #title='Google Organic CTR Breakdown By Position',
                    labels={'Position': 'Position', 'CTR': 'Click Through Rate (%)'},
                    text='CTR')

        # Update layout for better styling
        brand_ctr_fig.update_traces(texttemplate='%{text}%', textposition='outside')
        brand_ctr_fig.update_layout(yaxis_title='Click Through Rate (%)',
                        xaxis_title='Position',
                        uniformtext_minsize=8, uniformtext_mode='hide')
        
        brand_ctr_fig_html = brand_ctr_fig.to_html()

        # Create a bar chart
        non_brand_ctr_fig = px.bar(non_brand_ctr_df, x='round_position', y='CTR',
                    #title='Google Organic CTR Breakdown By Position',
                    labels={'Position': 'Position', 'CTR': 'Click Through Rate (%)'},
                    text='CTR')

        # Update layout for better styling
        non_brand_ctr_fig.update_traces(texttemplate='%{text}%', textposition='outside')
        non_brand_ctr_fig.update_layout(yaxis_title='Click Through Rate (%)',
                        xaxis_title='Position',
                        uniformtext_minsize=8, uniformtext_mode='hide')
        
        non_brand_ctr_fig_html = non_brand_ctr_fig.to_html()



        brand_ctr_df = brand_ctr_df.rename(columns={'round_position': 'Position'})
        non_brand_ctr_df = non_brand_ctr_df.rename(columns={'round_position': 'Position'})

        brand_ctr_html = brand_ctr_df.to_html(index=False, classes='table', border=1, justify='left')
        non_brand_ctr_html = non_brand_ctr_df.to_html(index=False, classes='table', border=1, justify='left')
        
        return render_template('/organic-ctr/partials.html', brand_ctr_df=brand_ctr_df, non_brand_ctr_df=non_brand_ctr_df,
                               brand_ctr_fig_html=brand_ctr_fig_html,non_brand_ctr_fig_html=non_brand_ctr_fig_html,
                               brand_ctr_html=brand_ctr_html, non_brand_ctr_html=non_brand_ctr_html )

    # GET request
    selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

    # if GSC property is not selected then send user to GSC property selection page
    if selected_property == "You haven't selected a GSC Property yet":
        # show a message
        flash('Please Select your GSC Property before clicking on Organic CTR Tab.')
        return redirect(url_for('gsc_property_selection'))

    webmasters_service = build_gsc_service()
    
    # Calculate end_date
    end_date = datetime.today()

    # Calculate start_date (15 months before today)
    start_date = end_date - relativedelta(months=15)

    # Format the dates as YYYY-MM-DD
    end_date_str = end_date.strftime('%Y-%m-%d')
    start_date_str = start_date.strftime('%Y-%m-%d')

    print("Start Date:", start_date_str)
    print("End Date:", end_date_str)
    
    dimensions = ['COUNTRY']
    
    dimensionFilterGroups = [{"filters": [
        #{"dimension": "COUNTRY", "expression": country, "operator": "equals"},
    ]}]

    country_df = fetch_search_console_data(webmasters_service, selected_property, start_date_str, end_date_str, dimensions, dimensionFilterGroups)
    
    print(country_df)

    countries = [country.upper() for country in country_df['COUNTRY'].to_list()]
    
    # read country-codes.csv file, and pass the data to create select form
    #countries = pd.read_csv(os.path.join(os.path.dirname(__file__), '..', 'static', 'country-codes.csv'))

    #countries = countries.to_dict('records')
    
    return render_template('/organic-ctr/main.html', selected_property=selected_property, 
                           brand_keywords=brand_keywords, countries=countries)


# Reports Routes
@app.route('/reports/sitewide-overview/', methods=['GET', 'POST'])
def sitewide_report():
    if 'credentials' not in session:
        # GSC is not logged in.
        return redirect(url_for('gsc_authorize'))

    if request.method == 'POST':
        #get request
        selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
        brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

        webmasters_service = build_gsc_service()

        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')

        current_start_date, current_end_date, previous_period_start_date, previous_period_end_date, previous_year_start_date, previous_year_end_date = process_dates(start_date_str, end_date_str)

        #total numbers make GSC API Call
        country = []
        dimensions = ['DATE', 'COUNTRY', 'DEVICE']
        dimensionFilterGroups = [{"filters": [
            #{"dimension": "COUNTRY", "expression": country, "operator": "equals"},
        ]}]
        
        current_period_df = fetch_search_console_data(webmasters_service, selected_property, current_start_date, current_end_date, dimensions, dimensionFilterGroups)

        previous_period_df = fetch_search_console_data(webmasters_service, selected_property, previous_period_start_date, previous_period_end_date, dimensions, dimensionFilterGroups)

        previous_year_df = fetch_search_console_data(webmasters_service, selected_property, previous_year_start_date, previous_year_end_date, dimensions, dimensionFilterGroups)


        # get earliest and latest date from gsc_data
        cp_earliest_date = current_period_df['DATE'].min()
        cp_latest_date = current_period_df['DATE'].max()

        # get earliest and latest date from gsc_data
        pp_earliest_date = previous_period_df['DATE'].min()
        pp_latest_date = previous_period_df['DATE'].max()

        # get earliest and latest date from gsc_data
        py_earliest_date = previous_year_df['DATE'].min()
        py_latest_date = previous_year_df['DATE'].max()

        #preparing data by country
        current_period_by_country = current_period_df.groupby('COUNTRY').agg(
            clicks = ('clicks', 'sum'),
            impressions = ('impressions', 'sum'),
            #ctr = ('ctr', 'mean'),
            position = ('position', 'mean')).reset_index()
        
        current_period_by_country['ctr'] = round(current_period_by_country['clicks'] / current_period_by_country['impressions'] * 100, 2)
        current_period_by_country['position'] = round(current_period_by_country['position'], 2)
        
        previous_period_by_country = previous_period_df.groupby('COUNTRY').agg(
            clicks = ('clicks', 'sum'),
            impressions = ('impressions', 'sum'),
            #ctr = ('ctr', 'mean'),
            position = ('position', 'mean')).reset_index()
        
        previous_period_by_country['ctr'] = round(previous_period_by_country['clicks'] / previous_period_by_country['impressions'] * 100, 2)
        previous_period_by_country['position'] = round(previous_period_by_country['position'], 2)   
        
        previous_year_by_country = previous_year_df.groupby('COUNTRY').agg(
            clicks = ('clicks', 'sum'),
            impressions = ('impressions', 'sum'),
            #ctr = ('ctr', 'mean'),
            position = ('position', 'mean')).reset_index()
        
        previous_year_by_country['ctr'] = round(previous_year_by_country['clicks'] / previous_year_by_country['impressions'] * 100, 2)
        previous_year_by_country['position'] = round(previous_year_by_country['position'], 2)

        merge_df = previous_period_by_country.merge(previous_year_by_country, on='COUNTRY', suffixes=('_prev_p', '_prev_y'), how='outer')
        merge_df = merge_df.merge(current_period_by_country, on='COUNTRY', how='outer')

        #print(merge_df.info())

        merge_df['clicks_pop'] = round((merge_df['clicks'] - merge_df['clicks_prev_p'])/merge_df['clicks_prev_p'] * 100,2)
        merge_df['impressions_pop'] = round((merge_df['impressions'] - merge_df['impressions_prev_p'])/merge_df['impressions_prev_p'] * 100,2)
        merge_df['ctr_pop'] = round((merge_df['ctr'] - merge_df['ctr_prev_p'])/merge_df['ctr_prev_p'] * 100,2)
        merge_df['position_pop'] = round((merge_df['position_prev_p'] - merge_df['position'])/merge_df['position_prev_p'] * 100,2)

        merge_df['clicks_yoy'] = round((merge_df['clicks'] - merge_df['clicks_prev_y'])/merge_df['clicks_prev_y'] * 100,2)
        merge_df['impressions_yoy'] = round((merge_df['impressions'] - merge_df['impressions_prev_y'])/merge_df['impressions_prev_y'] * 100,2)
        merge_df['ctr_yoy'] = round((merge_df['ctr'] - merge_df['ctr_prev_y'])/merge_df['ctr_prev_y'] * 100,2)
        merge_df['position_yoy'] = round((merge_df['position_prev_y'] - merge_df['position'])/merge_df['position_prev_y'] * 100,2)


        # Create a MultiIndex for the header
        header = [
        ('COUNTRY', 'COUNTRY'),
        ('Previous Period', 'Clicks'),
        ('Previous Period', 'Impressions'),
        ('Previous Period', 'Position'),
        ('Previous Period', 'CTR'),
        ('Previous Year', 'Clicks'),
        ('Previous Year', 'Impressions'),
        ('Previous Year', 'Position'),
        ('Previous Year', 'CTR'),
        ('Current Period', 'Clicks'),
        ('Current Period', 'Impressions'),
        ('Current Period', 'Position'),
        ('Current Period', 'CTR'),
        ('Period over Period (in %)', 'Clicks'),
        ('Period over Period (in %)', 'Impressions'),
        ('Period over Period (in %)', 'Position'),
        ('Period over Period (in %)', 'CTR'),
        ('Year over Year (in %)', 'Clicks'),
        ('Year over Year (in %)', 'Impressions'),
        ('Year over Year (in %)', 'Position'),
        ('Year over Year (in %)', 'CTR'),
        ]

        merge_df.columns = pd.MultiIndex.from_tuples(header)

        # Fill NaN values with 0
        merge_df.fillna(0, inplace=True)

        #print(merge_df.info())


        # Assuming your DataFrame is named df
        columns_order = [
            ('COUNTRY', 'COUNTRY'),
            ('Current Period', 'Clicks'),
            ('Current Period', 'Impressions'),
            ('Current Period', 'Position'),
            ('Current Period', 'CTR'),
            ('Period over Period (in %)', 'Clicks'),
            ('Period over Period (in %)', 'Impressions'),
            ('Period over Period (in %)', 'Position'),
            ('Period over Period (in %)', 'CTR'),
            ('Previous Period', 'Clicks'),
            ('Previous Period', 'Impressions'),
            ('Previous Period', 'Position'),
            ('Previous Period', 'CTR'),
            ('Year over Year (in %)', 'Clicks'),
            ('Year over Year (in %)', 'Impressions'),
            ('Year over Year (in %)', 'Position'),
            ('Year over Year (in %)', 'CTR'),
            ('Previous Year', 'Clicks'),
            ('Previous Year', 'Impressions'),
            ('Previous Year', 'Position'),
            ('Previous Year', 'CTR')
        ]

        merge_df = merge_df.reindex(columns=columns_order)


        merge_df[('Current Period', 'Clicks')] = merge_df[('Current Period', 'Clicks')].astype(int).map('{:,.0f}'.format)
        merge_df[('Current Period', 'Impressions')] = merge_df[('Current Period', 'Impressions')].astype(int).map('{:,.0f}'.format)

        merge_df[('Previous Period', 'Clicks')] = merge_df[('Previous Period', 'Clicks')].astype(int).map('{:,.0f}'.format)
        merge_df[('Previous Period', 'Impressions')] = merge_df[('Previous Period', 'Impressions')].astype(int).map('{:,.0f}'.format)

        merge_df[('Previous Year', 'Clicks')] = merge_df[('Previous Year', 'Clicks')].astype(int).map('{:,.0f}'.format)
        merge_df[('Previous Year', 'Impressions')] = merge_df[('Previous Year', 'Impressions')].astype(int).map('{:,.0f}'.format)
    

        #print(new_df['(Previous Period, Clicks)'][0])

        merge_df_html = merge_df.to_html(classes='table table-striped', table_id="byCountry", index=False)



        #preparing data by DEVICE
        current_period_by_device = current_period_df.groupby('DEVICE').agg(
            clicks = ('clicks', 'sum'),
            impressions = ('impressions', 'sum'),
            #ctr = ('ctr', 'mean'),
            position = ('position', 'mean')).reset_index()
        
        current_period_by_device['ctr'] = round(current_period_by_device['clicks'] / current_period_by_device['impressions'] * 100, 2)
        current_period_by_device['position'] = round(current_period_by_device['position'], 2)
        
        previous_period_by_device = previous_period_df.groupby('DEVICE').agg(
            clicks = ('clicks', 'sum'),
            impressions = ('impressions', 'sum'),
            #ctr = ('ctr', 'mean'),
            position = ('position', 'mean')).reset_index()
        
        previous_period_by_device['ctr'] = round(previous_period_by_device['clicks'] / previous_period_by_device['impressions'] * 100, 2)
        previous_period_by_device['position'] = round(previous_period_by_device['position'], 2)   
        
        previous_year_by_device = previous_year_df.groupby('DEVICE').agg(
            clicks = ('clicks', 'sum'),
            impressions = ('impressions', 'sum'),
            #ctr = ('ctr', 'mean'),
            position = ('position', 'mean')).reset_index()
        
        previous_year_by_device['ctr'] = round(previous_year_by_device['clicks'] / previous_year_by_device['impressions'] * 100, 2)
        previous_year_by_device['position'] = round(previous_year_by_device['position'], 2)

        merge_df_by_device = previous_period_by_device.merge(previous_year_by_device, on='DEVICE', suffixes=('_prev_p', '_prev_y'), how='outer')
        merge_df_by_device = merge_df_by_device.merge(current_period_by_device, on='DEVICE', how='outer')

        #print(merge_df_by_device.info())
        #print('-----')

        merge_df_by_device['clicks_pop'] = round((merge_df_by_device['clicks'] - merge_df_by_device['clicks_prev_p'])/merge_df_by_device['clicks_prev_p'] * 100,2)
        merge_df_by_device['impressions_pop'] = round((merge_df_by_device['impressions'] - merge_df_by_device['impressions_prev_p'])/merge_df_by_device['impressions_prev_p'] * 100,2)
        merge_df_by_device['ctr_pop'] = round((merge_df_by_device['ctr'] - merge_df_by_device['ctr_prev_p'])/merge_df_by_device['ctr_prev_p'] * 100,2)
        merge_df_by_device['position_pop'] = round((merge_df_by_device['position_prev_p'] - merge_df_by_device['position'])/merge_df_by_device['position_prev_p'] * 100,2)

        merge_df_by_device['clicks_yoy'] = round((merge_df_by_device['clicks'] - merge_df_by_device['clicks_prev_y'])/merge_df_by_device['clicks_prev_y'] * 100,2)
        merge_df_by_device['impressions_yoy'] = round((merge_df_by_device['impressions'] - merge_df_by_device['impressions_prev_y'])/merge_df_by_device['impressions_prev_y'] * 100,2)
        merge_df_by_device['ctr_yoy'] = round((merge_df_by_device['ctr'] - merge_df_by_device['ctr_prev_y'])/merge_df_by_device['ctr_prev_y'] * 100,2)
        merge_df_by_device['position_yoy'] = round((merge_df_by_device['position_prev_y'] - merge_df_by_device['position'])/merge_df_by_device['position_prev_y'] * 100,2)


        # Create a MultiIndex for the header
        header = [
        ('DEVICE', 'DEVICE'),
        ('Previous Period', 'Clicks'),
        ('Previous Period', 'Impressions'),
        ('Previous Period', 'Position'),
        ('Previous Period', 'CTR'),
        ('Previous Year', 'Clicks'),
        ('Previous Year', 'Impressions'),
        ('Previous Year', 'Position'),
        ('Previous Year', 'CTR'),
        ('Current Period', 'Clicks'),
        ('Current Period', 'Impressions'),
        ('Current Period', 'Position'),
        ('Current Period', 'CTR'),
        ('Period over Period (in %)', 'Clicks'),
        ('Period over Period (in %)', 'Impressions'),
        ('Period over Period (in %)', 'Position'),
        ('Period over Period (in %)', 'CTR'),
        ('Year over Year (in %)', 'Clicks'),
        ('Year over Year (in %)', 'Impressions'),
        ('Year over Year (in %)', 'Position'),
        ('Year over Year (in %)', 'CTR'),
        ]

        merge_df_by_device.columns = pd.MultiIndex.from_tuples(header)

        # Fill NaN values with 0
        merge_df_by_device.fillna(0, inplace=True)

        #print(merge_df_by_device.info())


        # Assuming your DataFrame is named df
        columns_order = [
            ('DEVICE', 'DEVICE'),
            ('Current Period', 'Clicks'),
            ('Current Period', 'Impressions'),
            ('Current Period', 'Position'),
            ('Current Period', 'CTR'),
            ('Period over Period (in %)', 'Clicks'),
            ('Period over Period (in %)', 'Impressions'),
            ('Period over Period (in %)', 'Position'),
            ('Period over Period (in %)', 'CTR'),
            ('Previous Period', 'Clicks'),
            ('Previous Period', 'Impressions'),
            ('Previous Period', 'Position'),
            ('Previous Period', 'CTR'),
            ('Year over Year (in %)', 'Clicks'),
            ('Year over Year (in %)', 'Impressions'),
            ('Year over Year (in %)', 'Position'),
            ('Year over Year (in %)', 'CTR'),
            ('Previous Year', 'Clicks'),
            ('Previous Year', 'Impressions'),
            ('Previous Year', 'Position'),
            ('Previous Year', 'CTR')
        ]

        merge_df_by_device = merge_df_by_device.reindex(columns=columns_order)


        merge_df_by_device[('Current Period', 'Clicks')] = merge_df_by_device[('Current Period', 'Clicks')].astype(int).map('{:,}'.format)
        merge_df_by_device[('Current Period', 'Impressions')] = merge_df_by_device[('Current Period', 'Impressions')].astype(int).map('{:,}'.format)

        merge_df_by_device[('Previous Period', 'Clicks')] = merge_df_by_device[('Previous Period', 'Clicks')].astype(int).map('{:,}'.format)
        merge_df_by_device[('Previous Period', 'Impressions')] = merge_df_by_device[('Previous Period', 'Impressions')].astype(int).map('{:,}'.format)

        merge_df_by_device[('Previous Year', 'Clicks')] = merge_df_by_device[('Previous Year', 'Clicks')].astype(int).map('{:,}'.format)
        merge_df_by_device[('Previous Year', 'Impressions')] = merge_df_by_device[('Previous Year', 'Impressions')].astype(int).map('{:,}'.format)
    

        #print(new_df['(Previous Period, Clicks)'][0])

        merge_df_html_by_device = merge_df_by_device.to_html(classes='table table-striped', table_id="byDevice", index=False)



        send_html = render_template('/sitewide-report/partial.html', 
                                    #dates
                                    current_start_date=current_start_date,
                                    current_end_date=current_end_date,

                                    #data available dates
                                    cp_earliest_date=cp_earliest_date,
                                    cp_latest_date=cp_latest_date,
                                    pp_earliest_date=pp_earliest_date,
                                    pp_latest_date=pp_latest_date,
                                    py_earliest_date=py_earliest_date,
                                    py_latest_date=py_latest_date,



                                    previous_period_start_date=previous_period_start_date,
                                    previous_period_end_date=previous_period_end_date,
                                    previous_year_start_date=previous_year_start_date,
                                    previous_year_end_date=previous_year_end_date,

                                    #dataframes
                                    current_period_df=current_period_df,
                                    previous_period_df=previous_period_df,
                                    previous_year_df=previous_year_df,

                                    #df htmls
                                    merge_df_html=merge_df_html,
                                    merge_df_html_by_device=merge_df_html_by_device
                                    )
        #print('send_html successful')

        return send_html

    # GET request
    selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

    # if GSC property is not selected then send user to GSC property selection page
    if selected_property == "You haven't selected a GSC Property yet":
        # show a message
        flash('Please Select your GSC Property.')
        return redirect(url_for('gsc_property_selection'))

    return render_template('/sitewide-report/main.html',
                           selected_property=selected_property,
                           brand_keywords=brand_keywords)

@app.route('/reports/sitewide-queries/', methods=['GET', 'POST'])
def query_aggregate_report():
    if 'credentials' not in session:
        # GSC is not logged in.
        return redirect(url_for('gsc_authorize'))
     
    if request.method == 'POST':
        #get request
        selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
        brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

        webmasters_service = build_gsc_service()

        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')

        #check available dates
        date_checher_start_date = "2020-01-01" 
        date_checker_end_date = "2050-01-01"

        date_checker_dimensions = ['DATE']
        date_checker_dimensionFilterGroups = [{"filters": [
            #{"dimension": "DATE", "operator": "between", "expressions": [date_checher_start_date, date_checker_end_date]}
        ]}]

        date_checker_df = fetch_search_console_data(webmasters_service, selected_property, date_checher_start_date, date_checker_end_date, date_checker_dimensions, date_checker_dimensionFilterGroups)
        
        date_checker_earliest_date = date_checker_df['DATE'].min()
        date_checker_latest_date = date_checker_df['DATE'].max()

        current_start_date, current_end_date, previous_period_start_date, previous_period_end_date, previous_year_start_date, previous_year_end_date = process_dates(start_date_str, end_date_str)

        all_dates = [current_start_date, current_end_date, previous_period_start_date, previous_period_end_date, previous_year_start_date, previous_year_end_date]
       
        #total numbers make GSC API Call
        country = []
        dimensions = ['QUERY']
        dimensionFilterGroups = [{"filters": [
            #{"dimension": "COUNTRY", "expression": country, "operator": "equals"},
        ]}]
        
        current_period_df = fetch_search_console_data(webmasters_service, selected_property, current_start_date, current_end_date, dimensions, dimensionFilterGroups)
        #print(current_period_df)
        previous_period_df = fetch_search_console_data(webmasters_service, selected_property, previous_period_start_date, previous_period_end_date, dimensions, dimensionFilterGroups)

        previous_year_df = fetch_search_console_data(webmasters_service, selected_property, previous_year_start_date, previous_year_end_date, dimensions, dimensionFilterGroups)
        

        """ get earliest and latest date from gsc_data
        cp_earliest_date = current_period_df['DATE'].min()
        cp_latest_date = current_period_df['DATE'].max()

        # get earliest and latest date from gsc_data
        pp_earliest_date = previous_period_df['DATE'].min()
        pp_latest_date = previous_period_df['DATE'].max()

        # get earliest and latest date from gsc_data
        py_earliest_date = previous_year_df['DATE'].min()
        py_latest_date = previous_year_df['DATE'].max() """

        merge_df = previous_period_df.merge(previous_year_df, on='QUERY', suffixes=('_prev_p', '_prev_y'), how='outer')
        merge_df = merge_df.merge(current_period_df, on='QUERY', how='outer')

        merge_df['Query Type'] = merge_df['QUERY'].apply(lambda x: keyword_type(x, brand_keywords))
 
        merge_df.fillna(0, inplace=True)

        #print(merge_df)

        merge_df['clicks_pop'] = ((merge_df['clicks'] - merge_df['clicks_prev_p']) / merge_df['clicks_prev_p'] * 100).round(2)
        merge_df['impressions_pop'] = ((merge_df['impressions'] - merge_df['impressions_prev_p']) / merge_df['impressions_prev_p'] * 100).round(2)
        merge_df['ctr_pop'] = ((merge_df['ctr'] - merge_df['ctr_prev_p']) / merge_df['ctr_prev_p'] * 100).round(2)
        merge_df['position_pop'] = ((merge_df['position'] - merge_df['position_prev_p']) / merge_df['position_prev_p'] * 100).round(2)

        merge_df['clicks_yoy'] = ((merge_df['clicks_prev_p'] - merge_df['clicks_prev_y']) / merge_df['clicks_prev_y'] * 100).round(2)
        merge_df['impressions_yoy'] = ((merge_df['impressions_prev_p'] - merge_df['impressions_prev_y']) / merge_df['impressions_prev_y'] * 100).round(2)
        merge_df['ctr_yoy'] = ((merge_df['ctr_prev_p'] - merge_df['ctr_prev_y']) / merge_df['ctr_prev_y'] * 100).round(2)
        merge_df['position_yoy'] = ((merge_df['position_prev_p'] - merge_df['position_prev_y']) / merge_df['position_prev_y'] * 100).round(2)


        merge_df = merge_df.rename(columns={
            'QUERY': 'QUERY',
            'Query Type' : 'Query Type', 
            'clicks_prev_p': 'Clicks (PP)',
            'impressions_prev_p': 'Impressions (PP)',
            'position_prev_p': 'Position (PP)',
            'ctr_prev_p': 'CTR (PP)',
            'clicks_prev_y': 'Clicks (PY)',
            'impressions_prev_y': 'Impressions (PY)',
            'position_prev_y': 'Position (PY)',
            'ctr_prev_y': 'CTR (PY)',
            'clicks': 'Clicks (CP)',
            'impressions': 'Impressions (CP)',
            'position': 'Position (CP)',
            'ctr': 'CTR (CP)',
            })
        
        # Assuming your DataFrame is named df
        columns_order = [
            ('QUERY'),
            ('Query Type'),
            ('Clicks (CP)'),
            ('Impressions (CP)'),
            ('CTR (CP)'),
            ('Position (CP)'),
            ('Clicks (PP)'),
            ('Impressions (PP)'),
            ('CTR (PP)'),
            ('Position (PP)'),
            ('Clicks (PY)'),
            ('Impressions (PY)'),
            ('CTR (PY)'),
            ('Position (PY)')
        ]

        #print(merge_df.info())

        merge_df = merge_df.reindex(columns=columns_order)

        merge_df['Position (CP)'] = merge_df['Position (CP)'].apply(lambda x: f"{x:.2f}")
        merge_df['CTR (CP)'] = (merge_df['CTR (CP)'] * 100).apply(lambda x: f"{x:.2f}")

        merge_df['Position (PP)'] = merge_df['Position (PP)'].apply(lambda x: f"{x:.2f}")
        merge_df['CTR (PP)'] = (merge_df['CTR (PP)'] * 100).apply(lambda x: f"{x:.2f}")

        merge_df['Position (PY)'] = merge_df['Position (PY)'].apply(lambda x: f"{x:.2f}")
        merge_df['CTR (PY)'] = (merge_df['CTR (PY)'] * 100).apply(lambda x: f"{x:.2f}")

        # remove rows containing # from merge_df
        #merge_df = merge_df[~merge_df['PAGE'].str.contains('#')]


        data_json = merge_df.to_json(orient='split')


        return render_template('/query-aggregate-report/partial.html', 
                               current_period_df=current_period_df,
                               data_json=data_json,
                               date_checker_earliest_date=date_checker_earliest_date,
                               date_checker_latest_date=date_checker_latest_date,
                               all_dates=all_dates
                               #current_period_df_html=current_period_df_html
                               )
    
    # GET request
    selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

    # if GSC property is not selected then send user to GSC property selection page
    if selected_property == "You haven't selected a GSC Property yet":
        # show a message
        flash('Please Select your GSC Property.')
        return redirect(url_for('gsc_property_selection'))

    return render_template('/query-aggregate-report/main.html',
                        selected_property=selected_property,
                        brand_keywords=brand_keywords)

@app.route('/reports/sitewide-pages/', methods=['GET', 'POST'])
def sitewide_pages():
    if 'credentials' not in session:
        return redirect(url_for('gsc_authorize'))
    
    if request.method == 'POST':

        #get request
        selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
        brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

        webmasters_service = build_gsc_service()


        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')

        #check available dates
        date_checher_start_date = "2020-01-01" 
        date_checker_end_date = "2050-01-01"

        date_checker_dimensions = ['DATE']
        date_checker_dimensionFilterGroups = [{"filters": [
            #{"dimension": "DATE", "operator": "between", "expressions": [date_checher_start_date, date_checker_end_date]}
        ]}]

        date_checker_df = fetch_search_console_data(webmasters_service, selected_property, date_checher_start_date, date_checker_end_date, date_checker_dimensions, date_checker_dimensionFilterGroups)
        
        date_checker_earliest_date = date_checker_df['DATE'].min()
        date_checker_latest_date = date_checker_df['DATE'].max()

        current_start_date, current_end_date, previous_period_start_date, previous_period_end_date, previous_year_start_date, previous_year_end_date = process_dates(start_date_str, end_date_str)

        
        #total numbers make GSC API Call
        country = []
        dimensions = ['PAGE']
        dimensionFilterGroups = [{"filters": [
            #{"dimension": "COUNTRY", "expression": country, "operator": "equals"},
        ]}]
        
        print('Scraping current_period_df')
        current_period_df = fetch_search_console_data(webmasters_service, selected_property, current_start_date, current_end_date, dimensions, dimensionFilterGroups)

        print('Scraping previous_period_df')
        previous_period_df = fetch_search_console_data(webmasters_service, selected_property, previous_period_start_date, previous_period_end_date, dimensions, dimensionFilterGroups)

        print('Scraping previous_year_df')
        previous_year_df = fetch_search_console_data(webmasters_service, selected_property, previous_year_start_date, previous_year_end_date, dimensions, dimensionFilterGroups)
        
        #merge database
        merge_df = previous_period_df.merge(previous_year_df, on='PAGE', suffixes=('_prev_p', '_prev_y'), how='outer')
        merge_df = merge_df.merge(current_period_df, on='PAGE', how='outer')

        #merge_df['Query Type'] = merge_df['PAGE'].apply(lambda x: keyword_type(x, brand_keywords))
 
        merge_df.fillna(0, inplace=True)

        merge_df['clicks_pop'] = ((merge_df['clicks'] - merge_df['clicks_prev_p']) / merge_df['clicks_prev_p'] * 100).round(2)
        merge_df['impressions_pop'] = ((merge_df['impressions'] - merge_df['impressions_prev_p']) / merge_df['impressions_prev_p'] * 100).round(2)
        merge_df['ctr_pop'] = ((merge_df['ctr'] - merge_df['ctr_prev_p']) / merge_df['ctr_prev_p'] * 100).round(2)
        merge_df['position_pop'] = ((merge_df['position'] - merge_df['position_prev_p']) / merge_df['position_prev_p'] * 100).round(2)

        merge_df['clicks_yoy'] = ((merge_df['clicks_prev_p'] - merge_df['clicks_prev_y']) / merge_df['clicks_prev_y'] * 100).round(2)
        merge_df['impressions_yoy'] = ((merge_df['impressions_prev_p'] - merge_df['impressions_prev_y']) / merge_df['impressions_prev_y'] * 100).round(2)
        merge_df['ctr_yoy'] = ((merge_df['ctr_prev_p'] - merge_df['ctr_prev_y']) / merge_df['ctr_prev_y'] * 100).round(2)
        merge_df['position_yoy'] = ((merge_df['position_prev_p'] - merge_df['position_prev_y']) / merge_df['position_prev_y'] * 100).round(2)


        # add one column named "Actions" to merge_df and add links to the "Optimize CTR" and "Another Action" in the column
        merge_df['Actions'] = merge_df['PAGE'].apply(
            lambda x: (
                f"""
                    
                        <a href='/actionable-insights/optimize-ctr?page={x}' target='_blank' class='badge badge-primary'>
                            <i class='fa-solid fa-wand-magic-sparkles'></i>  CTR
                        </a>
                        <!-- 
                        <div class="flex space-x-2" hidden>
                        <a href='/actionable-insights/optimize-page-content?page={x}' target='_blank' class='badge badge-secondary'>
                            <i class='fa-solid fa-file-pen'></i> Content 
                        </a>
                        </div> -->
                """
            )
        )

        # remove selected_property from merge_df['PAGE'] and add ahref link to it using original merge_df['PAGE']
        #merge_df['PAGE'] = merge_df['PAGE'].str.replace(selected_property, '/')


        merge_df = merge_df.rename(columns={
            'PAGE': 'PAGE',
            #'Query Type' : 'Query Type', 
            'clicks_prev_p': 'Clicks (PP)',
            'impressions_prev_p': 'Impressions (PP)',
            'position_prev_p': 'Position (PP)',
            'ctr_prev_p': 'CTR (PP)',
            'clicks_prev_y': 'Clicks (PY)',
            'impressions_prev_y': 'Impressions (PY)',
            'position_prev_y': 'Position (PY)',
            'ctr_prev_y': 'CTR (PY)',
            'clicks': 'Clicks (CP)',
            'impressions': 'Impressions (CP)',
            'position': 'Position (CP)',
            'ctr': 'CTR (CP)',
            'clicks_pop': 'Clicks PoP %',
            'impressions_pop': 'Impressions PoP %',
            'position_pop': 'Position PoP %',
            'ctr_pop': 'CTR PoP %',
            'clicks_yoy': 'Clicks YoY %',
            'impressions_yoy': 'Impressions YoY %',
            'position_yoy': 'Position YoY %',
            'ctr_yoy': 'CTR YoY %'
            })
        
        # Assuming your DataFrame is named df
        columns_order = [
            ('PAGE'),
            
            #('Query Type'),
            ('Actions'),
            ('Clicks (CP)'),
            ('Impressions (CP)'),
            ('CTR (CP)'),
            ('Position (CP)'),
            ('Clicks PoP %'),
            ('Impressions PoP %'),
            ('Position PoP %'),
            ('CTR PoP %'),
            ('Clicks (PP)'),
            ('Impressions (PP)'),
            ('CTR (PP)'),
            ('Position (PP)'),
            ('Clicks YoY %'),
            ('Impressions YoY %'),
            ('Position YoY %'),
            ('CTR YoY %'),
            ('Clicks (PY)'),
            ('Impressions (PY)'),
            ('CTR (PY)'),
            ('Position (PY)')
        ]

        merge_df = merge_df.reindex(columns=columns_order)

        merge_df['Position (CP)'] = merge_df['Position (CP)'].apply(lambda x: f"{x:.2f}")
        merge_df['CTR (CP)'] = (merge_df['CTR (CP)'] * 100).apply(lambda x: f"{x:.2f}")

        merge_df['Position (PP)'] = merge_df['Position (PP)'].apply(lambda x: f"{x:.2f}")
        merge_df['CTR (PP)'] = (merge_df['CTR (PP)'] * 100).apply(lambda x: f"{x:.2f}")

        merge_df['Position (PY)'] = merge_df['Position (PY)'].apply(lambda x: f"{x:.2f}")
        merge_df['CTR (PY)'] = (merge_df['CTR (PY)'] * 100).apply(lambda x: f"{x:.2f}")

        # remove # from PAGE
        merge_df = merge_df[~merge_df['PAGE'].str.contains('#')]


        data_json = merge_df.to_json(orient='split')

        return render_template('/sitewide-pages/partial.html', 
                               date_checker_earliest_date=date_checker_earliest_date,
                               date_checker_latest_date=date_checker_latest_date,
                               data_json=data_json
                               )
    
    # GET request
    selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

    # if GSC property is not selected then send user to GSC property selection page
    if selected_property == "You haven't selected a GSC Property yet":
        # show a message
        flash('Please Select your GSC Property.')
        return redirect(url_for('gsc_property_selection'))

    return render_template('/sitewide-pages/main.html',
                        selected_property=selected_property,
                        brand_keywords=brand_keywords)


@app.route('/gsc-celery-test/', methods=['GET', 'POST'])
def gsc_celery_test():
    if 'credentials' not in session:
        return redirect(url_for('gsc_authorize'))

    if request.method == 'POST':
        credentials_data = flask.session['credentials']
        selected_property = session.get("selected_property", "default_value")
        
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')

        start_date_formatted, end_date_formatted = format_dates(start_date_str, end_date_str)

        dimensions = ['DATE', 'QUERY', 'PAGE']
        dimensionFilterGroups = [{"filters": []}]
        
        # Start Celery task
        result = celery_test_gsc_data.delay(credentials_data, selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups)
        
        # Track task status
        task_status[result.id] = {'status': 'pending'}

        return jsonify({'task_id': result.id})

    #get request
    selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

    return render_template('gsc-celery-test.html', 
                           selected_property=selected_property,
                           brand_keywords=brand_keywords)


@app.route('/actionable-insights/optimize-ctr', methods=['GET', 'POST'])
def optimize_ctr():
    if 'credentials' not in session:
        return redirect(url_for('gsc_authorize'))
    
    if request.method == 'POST':

        selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
        brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

        #build gsc service
        webmasters_service = build_gsc_service()

        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        page = request.form.get('page')

        start_date_formatted, end_date_formatted = format_dates(start_date_str, end_date_str)

        #total numbers make GSC API Call
        dimensions = ['DATE', 'QUERY']
        dimensionFilterGroups = [{"filters": [
            {"dimension": "PAGE", "expression": page, "operator": "equals"},
        ]}]

        #get gsc data
        date_query_df = fetch_search_console_data(webmasters_service, selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups)

        # only rows where position is less than 11
        date_query_df = date_query_df.loc[date_query_df['position'] < 10]

        # filter rows where impressions is greater than date_query_df['impressions'].mean(), but also include rows where click is greater than 0 irrepesctive of impressions
        date_query_df = date_query_df.loc[(date_query_df['impressions'] > date_query_df['impressions'].mean()) | (date_query_df['clicks'] > 0)]

        # calculate mean, mode, median for date_query_df['impressions']
        mean_impressions = date_query_df['impressions'].mean()
        print(mean_impressions)

        # aggreate the dataframe by query
        query_df = date_query_df.groupby('QUERY').agg({'clicks': 'sum', 'impressions': 'sum'}).reset_index()

        # calculate CTR
        query_df['CTR'] = round(query_df['clicks'] / query_df['impressions'] * 100, 2)

        # Applying the function to the DataFrame
        query_df['Query Type'] = query_df['QUERY'].apply(lambda x: keyword_type(x, brand_keywords))

        # create a query_df where query_df['Query Type'] is "Non Branded"
        query_df = query_df[query_df['Query Type'] == 'Non Branded']

        # prepare data for DataTable
        data_json = query_df.to_json(orient='split')

        # scrape current title & meta description of the URL using bs4
        url = page

        # Define headers with a real User-Agent
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        # Send a GET request to the URL
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            try:
                # Parse the content using BeautifulSoup
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Get the title
                title_tag = soup.title
                title = title_tag.string if title_tag else 'No title found'
                
                # Get the meta description
                meta_desc = 'No description found'
                try:
                    meta_tag = soup.find('meta', attrs={'name': 'description'})
                    if meta_tag and 'content' in meta_tag.attrs:
                        meta_desc = meta_tag['content']
                except Exception:
                    pass  # Ensure no errors are raised during meta description extraction

                # Get H1 from the page
                h1 = 'No H1 found'
                try:
                    h1_tag = soup.find('h1')
                    if h1_tag:
                        h1 = h1_tag.string.strip() if h1_tag.string else 'No H1 text found'
                except Exception:
                    pass  # Ensure no errors are raised during H1 extraction

                # Scrape body text
                body_text = ''
                try:
                    body_text = soup.get_text().strip() if soup else 'No body content found'
                except Exception:
                    pass  # Ensure no errors are raised during body text extraction

            except Exception as e:
                # Log the error if needed, but do not interrupt the app flow
                logger.error(f"Error during HTML parsing: {e}")
                title = 'No title found'
                meta_desc = 'No description found'
                h1 = 'No H1 found'
                body_text = 'No body content found'
        else:
            # Default fallback for non-200 responses
            title = 'No title found'
            meta_desc = 'No description found'
            h1 = 'No H1 found'
            body_text = 'No body content found'



        # tokenize title and meta description - split with space
        title_tokens = title.split()

        # remove special characters from title_tokens
        title_tokens = [re.sub(r'[^\w\s]', '', token) for token in title_tokens if re.sub(r'[^\w\s]', '', token)]

        # convert all title_tokens to lowercase
        title_tokens = [token.lower() for token in title_tokens]

        # remove stop words
        title_tokens = [token for token in title_tokens if token not in stopwords.words('english')]

        
        meta_desc_tokens = meta_desc.split()

        # remove special characters from meta_desc_tokens
        meta_desc_tokens = [re.sub(r'[^\w\s]', '', token) for token in meta_desc_tokens if re.sub(r'[^\w\s]', '', token)]

        # convert all meta_desc_tokens to lowercase
        meta_desc_tokens = [token.lower() for token in meta_desc_tokens]

        # remove stop words from meta_desc_tokens
        meta_desc_tokens = [token for token in meta_desc_tokens if token not in stopwords.words('english')]

        
        
        
        # sort query_df by clicks
        query_df = query_df.sort_values(by='clicks', ascending=False)

        # create a list of query_df['QUERY']
        query_list = query_df['QUERY'].tolist()

        # tokenize each item in query_list
        query_tokens = [item.split(' ') for item in query_list]

        query_tokens_flat = []
        # flatten query_tokens
        for each in query_tokens:
            query_tokens_flat.extend(each)

        # remove special characters from query_tokens_flat
        query_tokens_flat = [re.sub(r'[^\w\s]', '', token) for token in query_tokens_flat if re.sub(r'[^\w\s]', '', token)]

        # convert all query_tokens_flat to lowercase
        query_tokens_flat = [token.lower() for token in query_tokens_flat]

        # remove stop words from query_tokens_flat
        query_tokens_flat = [token for token in query_tokens_flat if token not in stopwords.words('english')]

        # count the frequency of each token
        query_tokens_count = Counter(query_tokens_flat)

        # sort query_tokens_count by frequency
        query_tokens_count = sorted(query_tokens_count.items(), key=lambda x: x[1], reverse=True)

        # get first 20 items
        query_tokens_count = query_tokens_count[:20]



        # classify each token in query_tokens_count if it exist in title_tokens and keep the count numbers as well
        title_query_tokens_count = []

        for token, count in query_tokens_count:
            if token in title_tokens:
                title_query_tokens_count.append((token, count, True))
            else:
                title_query_tokens_count.append((token, count, False))

        # for each token in title_query_tokens_count, get top 5 queries from query_df
        title_query_tokens_count = [(token, count, exist, query_df[query_df['QUERY'].str.contains(token)]['QUERY'].tolist()[:5]) for token, count, exist in title_query_tokens_count]
        

        # classify each token in query_tokens_count if it exist in meta_desc_tokens and keep the count numbers as well
        meta_desc_query_tokens_count = []

        for token, count in query_tokens_count:
            if token in meta_desc_tokens:
                meta_desc_query_tokens_count.append((token, count, True))
            else:
                meta_desc_query_tokens_count.append((token, count, False))
        
        # for each token in meta_desc_query_tokens_count, get top 5 queries from query_df
        meta_desc_query_tokens_count = [(token, count, exist, query_df[query_df['QUERY'].str.contains(token)]['QUERY'].tolist()[:5]) for token, count, exist in meta_desc_query_tokens_count]


        #get gsc metrics
        return  render_template('/actionable-insights/optimize-ctr/partial.html', 
                                data_json=data_json, title=title, meta_desc=meta_desc,
                                title_tokens=title_tokens, meta_desc_tokens=meta_desc_tokens,
                                query_tokens=query_tokens_count, 
                                #missing_title_tokens=missing_title_tokens,
                                #missing_meta_desc_tokens=missing_meta_desc_tokens,
                                #query_list=query_list,
                                title_query_tokens_count=title_query_tokens_count,
                                meta_desc_query_tokens_count=meta_desc_query_tokens_count,
                                h1=h1
                                )
    
    #get request
    selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

    #capture variable <page> from url path
    page = request.args.get('page', default='')


    return render_template('/actionable-insights/optimize-ctr/main.html', 
                           page=page,
                           selected_property=selected_property,
                           brand_keywords=brand_keywords)


@app.route('/optimize-ctr/generate-ai-title/', methods=['POST', 'GET'])
def generate_ai_title():
    if 'credentials' not in session:
        return redirect(url_for('gsc_authorize'))
    else:
        # POST request
        if request.method == 'POST':
            
            # Capture the incoming JSON data from the request
            data = request.get_json()

            # Extract the data from the JSON
            existing_title = data.get('existing_title')
            page = data.get('page')
            title_query_tokens_count = data.get('titleQueryTokensCount')
            h1 = data.get('h1')
            openai_api_key = data.get('openai_api_key')
            print(openai_api_key)

            # Print or log the captured data for debugging
            logger.info('Existing Title:', existing_title)
            logger.info('Page:', page)
            #print('Title Query Tokens Count:', title_query_tokens_count)

            print(type(title_query_tokens_count))

            # Format the information for the prompt
            formatted_tokens = ""
            for term, count, exists_in_title, examples in title_query_tokens_count:
                formatted_tokens += f"Term: {term}\n"
                formatted_tokens += f"Used {count} times in search queries.\n"
                formatted_tokens += f"Exists in the current title: {'Yes' if exists_in_title else 'No'}\n"
                formatted_tokens += f"Top 5 search queries: {', '.join(examples)}\n"
                formatted_tokens += "\n"  # Adding a line break between entries

            logger.info(formatted_tokens)

            # Here you can perform any operations, such as generating the AI title

            client = OpenAI(api_key=openai_api_key)

            system_prompt = """ 
            You are a highly skilled AI assistant specialized in search engine optimization (SEO) and natural language processing. 
            You assist users in analyzing and optimizing their webpage titles based on data provided from Google Search Console (GSC). 
            Your responses are precise, actionable, and based on best practices in SEO. 

            Ensure recommendations align with the following principles:
            - Write a new Title that's actionable. When user will see this in SERP, they should have a clear idea of next Action.
            - Improve click-through rates (CTR).
            - Highlight the most relevant and high-performing keywords.
            - Maintain relevance to the webpage's content and intent.
            - Ensure clarity, readability, and compelling value propositions in titles.
            - If data is incomplete or unclear, suggest an alternative approach or prompt the user for clarification. 
            Your tone is professional, concise, and helpful.
                            """

            task_prompt = f"""

                I've uploaded data from Google Search Console (GSC) to you.

                Web Page URL: "{page}".
                Current Title Tag: "{existing_title}".
                Current H1 Tag: "{h1}"

                Analyze the following GSC information to help generate the new title. 
                You don't have to use everything provided. This is for information and analysis purposes.


                Here is the format of the provided data for your analysis:

                Term: <term> used in Search Query
                Used <X> times in search queries.
                Exists in the current title: <Yes/No>
                Top 5 search queries: <Query 1>, <Query 2>, <Query 3>, <Query 4>, <Query 5>

                The following details include terms, their frequency in search queries, whether they exist in the current title, and the top 5 associated search queries.
                The idea is, if you include the most recurrent terms in the title, it will be more likely to have higher CTR because it will be more relevant for user queries..
                {formatted_tokens}

                Based on this data, optimize the Title Tag for better SEO performance. 
                Provide a new Title Tag and don't generate anything other than title.
                Ensure it's within the character limit and includes high-value keywords from the associated queries.
                When you write Titles, make it Actionable. Always keep this in mind.
                
                To handle edge cases:
                - If sufficient data is not available, suggest an alternative generic approach to crafting an optimized Title Tag.

                """
            
            completion = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": task_prompt},
                    ]
                    )
            
            ai_generated_title = completion.choices[0].message.content

            ai_generated_title_html = f"""
            <div class="p-5 bg-primary-content rounded-box">
                <p class="text-s accent-content">
                {ai_generated_title}
                </p>

            </div>
            """
            return ai_generated_title_html

        # GET request
        return redirect(url_for('dashboard'))
    

@app.route('/optimize-ctr/generate-ai-meta-description/', methods=['POST', 'GET'])
def generate_ai_meta_description():
    if 'credentials' not in session:
        return redirect(url_for('gsc_authorize'))
    else:
        # POST request
        if request.method == 'POST':

            
            # Capture the incoming JSON data from the request
            data = request.get_json()


            # Extract the data from the JSON
            existing_title = data.get('existing_title')
            existing_meta_description = data.get('existingMetaDescriptionElement')
            page = data.get('page')
            metaDescQueryTokensCount = data.get('metaDescQueryTokensCount')
            h1 = data.get('h1')
            openai_api_key = data.get('openai_api_key')

            # Print or log the captured data for debugging
            logger.info('Existing Title:', existing_title)
            logger.info('Page:', page)
            #print('Title Query Tokens Count:', title_query_tokens_count)

            print(type(metaDescQueryTokensCount))

            # Format the information for the prompt
            formatted_tokens = ""
            for term, count, exists_in_title, examples in metaDescQueryTokensCount:
                formatted_tokens += f"Term: {term}\n"
                formatted_tokens += f"Used {count} times in search queries.\n"
                formatted_tokens += f"Exists in the current Meta Description: {'Yes' if exists_in_title else 'No'}\n"
                formatted_tokens += f"Top 5 search queries: {', '.join(examples)}\n"
                formatted_tokens += "\n"  # Adding a line break between entries

            logger.info(formatted_tokens)

            # Here you can perform any operations, such as generating the AI title

            client = OpenAI(
                api_key=openai_api_key
                )


            system_prompt = """ 
                You are an expert copywriter and SEO specialist who crafts highly compelling and optimized Meta Descriptions to improve click-through rates (CTR). 
                Your task is to generate a new SEO Meta Description for a webpage using data provided from Google Search Console (GSC). 
                Your responses are precise, actionable, and based on best practices in SEO. 

                Ensure recommendations align with the following principles:
                - Write Meta Descriptions that are actionable and enticing, encouraging users to click.
                - Incorporate high-performing and relevant keywords that reflect the webpage's content.
                - Maintain readability and make the Meta Description engaging while adhering to the character limit (120-160 characters).
                - Use terms not included in the Title Tag to provide additional context or value to the user.
                - If data is incomplete or unclear, suggest a generic alternative or prompt for clarification.
                Your tone is professional, concise, and helpful.
                """

            task_prompt = f"""

                Here is the Page URL: "{page}".
                Here is the Existing Title of the Page: "{existing_title}".
                Here is the Existing Meta Description of the Page: "{existing_meta_description}".
                Here is the Existing H1 of the Page: "{h1}".

                Use the following data for analysis:

                Here is the format of the provided data for your analysis:

                Term: <term> used in Search Query
                Used <X> times in search queries.
                Exists in the current title: <Yes/No>
                Top 5 search queries: <Query 1>, <Query 2>, <Query 3>, <Query 4>, <Query 5>

                The following details include terms, their frequency in search queries, whether they exist in the current title, and the top 5 associated search queries:
                {formatted_tokens}

                Important instructions:
                1) The new Meta Description should be in the same language as the existing title.
                2) Focus on terms not present in the existing title, but relevant to the page content, to differentiate the Meta Description and provide added value.
                3) Adhere to the Meta Description character limit of 120-160 characters.
                4) Provide only the new Meta Description and nothing else.
                5) If sufficient data is unavailable, suggest a generic yet engaging Meta Description.
                """

            
            completion = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": task_prompt},
                    ]
                    )
            ai_generated_meta_description = completion.choices[0].message.content

            ai_generated_meta_description_html = f"""

            <div class="p-5 bg-primary-content rounded-box">
                <p class="text-s accent-content">
                {ai_generated_meta_description}
                </p>

            </div>
            """
            return ai_generated_meta_description_html

        
        # GET request
        return redirect(url_for('dashboard'))
    

@app.route('/actionable-insights/optimize-page-content', methods=['GET', 'POST'])
def optimize_page_content():
    if 'credentials' not in session:
        return redirect(url_for('gsc_authorize'))
    
    if request.method == 'POST':

        selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
        brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

        #capture variable <page> from url path
        page = request.form.get('page')

        # scrape current title & meta description of the URL using bs4
        url = page

        # Define headers with a real User-Agent
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        # Send a GET request to the URL
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            try:
                # Parse the content using BeautifulSoup
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Get the title
                title_tag = soup.title
                title = title_tag.string if title_tag else 'No title found'
                
                # Get the meta description
                meta_desc = 'No description found'
                try:
                    meta_tag = soup.find('meta', attrs={'name': 'description'})
                    if meta_tag and 'content' in meta_tag.attrs:
                        meta_desc = meta_tag['content']
                except Exception:
                    pass  # Ensure no errors are raised during meta description extraction

                # Get all content from the page
                content_html = ''
                for tag in soup.find_all(['h1', 'h2', 'h3', 'p', 'table']):
                    content_html += str(tag)

            except Exception as e:
                # Log the error if needed, but do not interrupt the app flow
                logger.error(f"Error during HTML parsing: {e}")
                title = 'No title found'
                meta_desc = 'No description found'
                content_html = 'No body content found'
        else:
            # Default fallback for non-200 responses
            title = 'No title found'
            meta_desc = 'No description found'
            content_html = 'No body content found'


        #build gsc service
        webmasters_service = build_gsc_service()

        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')

        start_date_formatted, end_date_formatted = format_dates(start_date_str, end_date_str)

        #total numbers make GSC API Calls
        dimensions = ['QUERY']
        dimensionFilterGroups = [{"filters": [
            {"dimension": "PAGE", "expression": page, "operator": "equals"},
        ]}]

        #get gsc data
        query_df = fetch_search_console_data(webmasters_service, selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups)

        # remove brand queries from query_df
        query_df = query_df[~query_df['QUERY'].str.contains('|'.join(brand_keywords), case=False)]

        # create a list of queries from query_df
        queries = query_df['QUERY'].tolist()

        # tokenize queries
        tokenized_queries = [query.split() for query in queries]

        # remove stop words from tokenized_queries
        stop_words = set(stopwords.words('english'))
        tokenized_queries = [[word for word in query if word.lower() not in stop_words] for query in tokenized_queries]

        # create a dictionary to store query tokens and their counts and examples
        query_tokens_count = {}

        # count the occurrences of each token in the tokenized queries
        for query in tokenized_queries:
            for token in query:
                if token not in query_tokens_count:
                    query_tokens_count[token] = {'count': 0, 'examples': []}
                query_tokens_count[token]['count'] += 1
                # Store top 5 examples for each token
                query_rows = query_df[query_df['QUERY'] == ' '.join(query)]
                if not query_rows.empty:
                    example = query_rows.sort_values(by=['impressions'], ascending=False).head(1)['QUERY'].iloc[0]
                    if len(query_tokens_count[token]['examples']) < 5:
                        query_tokens_count[token]['examples'].append(example)

        # sort the query tokens by count in descending order
        sorted_query_tokens_count = sorted(query_tokens_count.items(), key=lambda x: x[1]['count'], reverse=True)

        print(type(sorted_query_tokens_count))

        return render_template('/actionable-insights/optimize-page-content/partial.html', 
                               title=title, meta_desc=meta_desc, content_html=content_html,
                               query_tokens=sorted_query_tokens_count
                               )
    
    #get request
    selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

    #capture variable <page> from url path
    page = request.args.get('page', default='')

    return render_template('/actionable-insights/optimize-page-content/main.html', 
                           page=page,
                           selected_property=selected_property,
                           brand_keywords=brand_keywords)

