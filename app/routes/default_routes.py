from flask import render_template, request, url_for, redirect, flash, session, jsonify
from app import app
import bcrypt
from datetime import datetime, timedelta, date
from app.routes.gsc_api_auth import * 
from app.routes.gsc_routes import *
import plotly.express as px

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
    if 'credentials' not in session:
        # GSC is not logged in.
        return redirect(url_for('gsc_authorize'))
    
    selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")
    
    return render_template('/default/dashboard.html', 
                           selected_property=selected_property,
                           brand_keywords=brand_keywords)

@app.route('/gsc-property-selection/', methods=['GET', 'POST'])
def gsc_property_selection():
    if request.method == 'POST':
        #save the selected website and country in session
        selected_property = request.form.get('selected_property')
        brand_keywords_list_input = request.form.get('brand_keywords')
        brand_keywords = brand_keywords_list_input.split(",")

        session['selected_property'] = selected_property
        session['brand_keywords'] = brand_keywords

        return redirect(url_for('dashboard'))
    
    if 'credentials' not in session:
        # GSC is not logged in.
        return redirect(url_for('gsc_authorize'))
    
    #get a list of GSC properties
    # Load credentials from the session.
    credentials = google.oauth2.credentials.Credentials(
        **flask.session['credentials'])

    # Retrieve list of properties in account
    search_console_service = googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials=credentials)
    
    site_list = search_console_service.sites().list().execute()
    
    site_list = site_list['siteEntry']

    site_list_sorted = []

    for each in site_list:
        site_list_sorted.append(each['siteUrl'])

    site_list_sorted = sorted(site_list_sorted)

    selected_property = session.get("selected_property", "Please Select your GSC Property.")
    
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
        dimensionFilterGroups = [{"filters": [
            #{"dimension": "COUNTRY", "expression": country, "operator": "equals"},
        ]}]
        
        gsc_data = fetch_search_console_data(webmasters_service, selected_property, start_date_formatted, end_date_formatted, dimensions, dimensionFilterGroups)

        #total numbers
        total_clicks = gsc_data['clicks'].sum()
        total_impressions = gsc_data['impressions'].sum()
        total_ctr = total_clicks / total_impressions * 100
        total_position = gsc_data['position'].mean()

        total_data = [total_clicks, total_impressions, total_ctr, total_position]

        #total numbers make GSC API Call
        q_dimensions = ['date', 'query'] 
        query_df = fetch_search_console_data(webmasters_service, selected_property, start_date_formatted, end_date_formatted, q_dimensions, dimensionFilterGroups)

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
        brand_query_count = plot_df['count_queries'][0]

        brand_numbers = [brand_clicks, brand_impressions, brand_ctr, brand_position, brand_query_count]


        non_brand_query_df = query_df[query_df['Query Type'] == 'Non Branded']

        non_brand_clicks = non_brand_query_df['clicks'].sum()
        non_brand_impressions = non_brand_query_df['impressions'].sum()
        non_brand_ctr = non_brand_clicks / non_brand_impressions * 100
        non_brand_position = non_brand_query_df['position'].mean()

        try:
            non_brand_query_count = plot_df['count_queries'][1]
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
                                    non_brand_position_bucket_graph=non_brand_position_bucket_graph
                                    )

        return send_html

    #get request
    selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")
    
    return render_template('/sitewide-analysis/mainpage.html', 
                           selected_property=selected_property,
                           brand_keywords=brand_keywords)

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


        merge_df[('Current Period', 'Clicks')] = merge_df[('Current Period', 'Clicks')].astype(int)
        merge_df[('Current Period', 'Impressions')] = merge_df[('Current Period', 'Impressions')].astype(int)

        merge_df[('Previous Period', 'Clicks')] = merge_df[('Previous Period', 'Clicks')].astype(int)
        merge_df[('Previous Period', 'Impressions')] = merge_df[('Previous Period', 'Impressions')].astype(int)

        merge_df[('Previous Year', 'Clicks')] = merge_df[('Previous Year', 'Clicks')].astype(int)
        merge_df[('Previous Year', 'Impressions')] = merge_df[('Previous Year', 'Impressions')].astype(int)
    

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


        merge_df_by_device[('Current Period', 'Clicks')] = merge_df_by_device[('Current Period', 'Clicks')].astype(int)
        merge_df_by_device[('Current Period', 'Impressions')] = merge_df_by_device[('Current Period', 'Impressions')].astype(int)

        merge_df_by_device[('Previous Period', 'Clicks')] = merge_df_by_device[('Previous Period', 'Clicks')].astype(int)
        merge_df_by_device[('Previous Period', 'Impressions')] = merge_df_by_device[('Previous Period', 'Impressions')].astype(int)

        merge_df_by_device[('Previous Year', 'Clicks')] = merge_df_by_device[('Previous Year', 'Clicks')].astype(int)
        merge_df_by_device[('Previous Year', 'Impressions')] = merge_df_by_device[('Previous Year', 'Impressions')].astype(int)
    

        #print(new_df['(Previous Period, Clicks)'][0])

        merge_df_html_by_device = merge_df_by_device.to_html(classes='table table-striped', table_id="byDevice", index=False)



        send_html = render_template('/sitewide-report/partial.html', 
                                    #dates
                                    current_start_date=current_start_date,
                                    current_end_date=current_end_date,
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

        current_start_date, current_end_date, previous_period_start_date, previous_period_end_date, previous_year_start_date, previous_year_end_date = process_dates(start_date_str, end_date_str)

        #total numbers make GSC API Call
        country = []
        dimensions = ['QUERY']
        dimensionFilterGroups = [{"filters": [
            #{"dimension": "COUNTRY", "expression": country, "operator": "equals"},
        ]}]
        
        current_period_df = fetch_search_console_data(webmasters_service, selected_property, current_start_date, current_end_date, dimensions, dimensionFilterGroups)

        previous_period_df = fetch_search_console_data(webmasters_service, selected_property, previous_period_start_date, previous_period_end_date, dimensions, dimensionFilterGroups)

        previous_year_df = fetch_search_console_data(webmasters_service, selected_property, previous_year_start_date, previous_year_end_date, dimensions, dimensionFilterGroups)
        

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


        data_json = merge_df.to_json(orient='split')


        return render_template('/query-aggregate-report/partial.html', 
                               current_period_df=current_period_df,
                               data_json=data_json
                               #current_period_df_html=current_period_df_html
                               )
    
    # GET request
    selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")

    return render_template('/query-aggregate-report/main.html',
                        selected_property=selected_property,
                        brand_keywords=brand_keywords)


