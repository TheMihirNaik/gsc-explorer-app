"""
Query Clustering Routes for Content Gap Analysis

This module provides functionality to cluster search queries using HDBSCAN algorithm
and OpenAI embeddings to identify content opportunities.
"""

from flask import render_template, request, session, redirect, url_for, jsonify
from app import app
from app.routes.gsc_api_auth import build_gsc_service, fetch_search_console_data
from app.routes.gsc_routes import format_dates, keyword_type, get_latest_available_date
import logging
import pandas as pd
import numpy as np
from openai import OpenAI
import os
import gc
from dotenv import load_dotenv

# Configure logging
logger = logging.getLogger(__name__)

# Machine learning imports
try:
    import hdbscan
    from sklearn.metrics.pairwise import cosine_similarity
    import umap
except ImportError as e:
    logger.error(f"Required ML libraries not installed: {e}")
    hdbscan = None
    cosine_similarity = None
    umap = None


@app.route('/tools/query-clustering/', methods=['GET'])
def query_clustering():
    """
    Main page for Query Clustering tool with country impression data
    """
    logger.info("Query Clustering page accessed")
    
    if 'credentials' not in session:
        logger.warning("No credentials in session, redirecting to GSC authorize")
        return redirect(url_for('gsc_authorize'))
    
    selected_property = session.get("selected_property", "You haven't selected a GSC Property yet")
    brand_keywords = session.get("brand_keywords", "You haven't selected Brand Keywords.")
    
    # Fetch country data with impressions for the dropdown
    countries_with_impressions = []
    try:
        from datetime import datetime, timedelta
        from app.routes.gsc_api_auth import build_gsc_service, fetch_search_console_data
        from app.routes.gsc_routes import format_dates
        
        # Get last 30 days data for country impressions
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        webmasters_service = build_gsc_service()
        
        # Fetch data grouped by country
        df = fetch_search_console_data(
            webmasters_service,
            selected_property,
            start_date,
            end_date,
            dimensions=['COUNTRY'],
            dimensionFilterGroups=[]
        )
        
        if not df.empty:
            # Group by country and sum impressions
            country_data = df.groupby('COUNTRY')['impressions'].sum().sort_values(ascending=False)
            
            # Map country codes to names
            country_names = {
                'usa': 'United States',
                'gbr': 'United Kingdom',
                'can': 'Canada',
                'aus': 'Australia',
                'ind': 'India',
                'deu': 'Germany',
                'fra': 'France',
                'jpn': 'Japan',
                'esp': 'Spain',
                'ita': 'Italy',
                'bra': 'Brazil',
                'mex': 'Mexico'
            }
            
            countries_with_impressions = [
                {
                    'code': country.lower(),
                    'name': country_names.get(country.lower(), country.upper()),
                    'impressions': int(impr)
                }
                for country, impr in country_data.head(20).items()
            ]
            
            logger.info(f"Fetched {len(countries_with_impressions)} countries with impression data")
    except Exception as e:
        logger.warning(f"Could not fetch country data: {e}")
        # Fallback to default list
        countries_with_impressions = []

    # Fetch latest available date
    latest_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    try:
        # Re-use webmasters_service if available, else build it
        if 'webmasters_service' not in locals():
            webmasters_service = build_gsc_service()
        latest_date = get_latest_available_date(webmasters_service, selected_property)
    except Exception as e:
        logger.warning(f"Error fetching latest date: {e}")
    
    return render_template(
        '/query-clustering/mainpage.html',
        selected_property=selected_property,
        brand_keywords=brand_keywords,
        countries_with_impressions=countries_with_impressions,
        latest_date=latest_date
    )


@app.route('/tools/query-clustering/analyze', methods=['POST'])
def query_clustering_analyze():
    """
    HTMX endpoint that performs query clustering analysis
    """
    logger.info("Starting query clustering analysis")
    
    if 'credentials' not in session:
        logger.warning("No credentials in session")
        return render_template(
            '/query-clustering/partial-error.html',
            error_message="Please authenticate with Google Search Console first."
        ), 401
    
    # Check if required libraries are available
    if not all([hdbscan, cosine_similarity, umap]):
        logger.error("Required ML libraries not available")
        return render_template(
            '/query-clustering/partial-error.html',
            error_message="Required machine learning libraries are not installed. Please contact administrator."
        ), 500
    
    try:
        # Get user inputs
        selected_property = session.get("selected_property", "")
        brand_keywords = session.get("brand_keywords", "")
        
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        countries = request.form.getlist('countries')  # Multi-select
        brand_filter = request.form.get('brand_filter')  # 'brand', 'non-brand', or 'both'
        # Get OpenAI API key from form (injected from localStorage by JavaScript)
        openai_api_key = request.form.get('openai_api_key', '').strip()
        if not openai_api_key:
            logger.warning("No OpenAI API key provided")
            return render_template(
                '/query-clustering/partial-error.html',
                error_message="Please set your OpenAI API Key in the sidebar settings first."
            ), 400
        
        logger.info(f"Parameters: dates={start_date_str} to {end_date_str}, countries={countries}, brand_filter={brand_filter}")
        
        # Format dates
        start_date_formatted, end_date_formatted = format_dates(start_date_str, end_date_str)
        
        # Build GSC service
        webmasters_service = build_gsc_service()
        
        # Fetch granular GSC data
        logger.info("Fetching granular GSC data with DATE, QUERY, PAGE, COUNTRY dimensions")
        df = fetch_granular_gsc_data(
            webmasters_service,
            selected_property,
            start_date_formatted,
            end_date_formatted,
            countries,
            brand_keywords,
            brand_filter
        )
        
        if df.empty:
            logger.warning("No data returned from GSC")
            return render_template(
                '/query-clustering/partial-error.html',
                error_message="No data found for the selected criteria. Try adjusting your filters."
            )
        
        logger.info(f"Fetched {len(df)} rows of GSC data")
        
        # Generate embeddings for unique queries
        logger.info("Generating OpenAI embeddings for queries")
        unique_queries = df['QUERY'].unique().tolist()
        logger.info(f"Found {len(unique_queries)} unique queries")
        
        embeddings_dict = generate_query_embeddings(unique_queries, openai_api_key)
        
        # Map embeddings back to dataframe
        df['embedding'] = df['QUERY'].map(embeddings_dict)
        
        # Perform HDBSCAN clustering
        logger.info("Performing HDBSCAN clustering")
        # Ensure strict alignment between queries and embeddings array
        embeddings_array = np.array([embeddings_dict[q] for q in unique_queries])
        cluster_labels = perform_hdbscan_clustering(embeddings_array)
        
        # Create mapping from query to cluster
        query_to_cluster = dict(zip(unique_queries, cluster_labels))
        df['cluster'] = df['QUERY'].map(query_to_cluster)
        
        # Remove noise points (cluster = -1)
        df_clustered = df[df['cluster'] != -1].copy()
        logger.info(f"Clustered into {df_clustered['cluster'].nunique()} clusters (excluding noise)")
        
        if df_clustered.empty:
            logger.warning("All queries classified as noise")
            return render_template(
                '/query-clustering/partial-error.html',
                error_message="Unable to form meaningful clusters. Try increasing the date range or adjusting filters."
            )
        
        # Aggregate cluster metrics
        logger.info("Aggregating cluster metrics")
        cluster_results = aggregate_cluster_metrics(df_clustered, embeddings_dict)
        
        # Filter out low-volume clusters (minimum 15 impressions)
        MIN_CLUSTER_IMPRESSIONS = 15
        cluster_results_filtered = [c for c in cluster_results if c['total_impressions'] >= MIN_CLUSTER_IMPRESSIONS]
        logger.info(f"Filtered to {len(cluster_results_filtered)} clusters with >= {MIN_CLUSTER_IMPRESSIONS} impressions (from {len(cluster_results)} total)")
        
        if not cluster_results_filtered:
            logger.warning("No clusters meet minimum impression threshold")
            return render_template(
                '/query-clustering/partial-error.html',
                error_message=f"No clusters with sufficient volume (minimum {MIN_CLUSTER_IMPRESSIONS} impressions). Try adjusting your date range."
            )
        

        # Calculate semantic distances and apply decision criteria
        logger.info("Calculating semantic distances and applying decision criteria (Tournament Logic)")
        cluster_results_final = calculate_semantic_distance_and_decide(
            cluster_results_filtered,
            df,  # Pass FULL dataframe (including noise) for accurate Page Identity
            webmasters_service,
            selected_property,
            start_date_formatted,
            end_date_formatted,
            embeddings_dict,
            openai_api_key
        )

        # Cleanup large objects that are no longer needed
        del embeddings_dict
        gc.collect()
        
        # Generate UMAP 2D projection for visualization
        logger.info("Generating UMAP 2D projection for scatter plot")
        umap_coords = generate_umap_projection(embeddings_array, cluster_labels)
        
        # Cleanup embeddings array as it's no longer needed
        del embeddings_array
        gc.collect()
        
        # Create scatter plot data with impression data
        scatter_data = create_scatter_plot_data(unique_queries, cluster_labels, umap_coords, df)
        
        # Cleanup UMAP coords and full DataFrame
        del umap_coords
        del df
        gc.collect()
        
        # Filter scatter_data to only include queries from filtered clusters
        # This prevents showing "Cluster X" for filtered-out clusters
        valid_cluster_ids = set(c['cluster_id'] for c in cluster_results_filtered)
        scatter_data_filtered = [
            point for point in scatter_data
            if point['cluster'] == 'Noise' or point['cluster'] in valid_cluster_ids
        ]
        logger.info(f"Filtered scatter data from {len(scatter_data)} to {len(scatter_data_filtered)} points")
        
        # Remove numpy arrays from cluster_results for JSON serialization
        cluster_results_clean = []
        for result in cluster_results_final:
            clean_result = {k: v for k, v in result.items() if k != 'cluster_centroid' and k != 'all_queries'}
            cluster_results_clean.append(clean_result)
        
        # Cleanup intermediate results
        del cluster_results_final
        gc.collect()
        
        # Calculate summary stats (granular)
        recommendation_counts = {
            'optimize_existing': 0,
            'redirect_focus': 0,
            'optimize_rankings': 0,
            'optimize_secondary': 0,
            'new_mismatch': 0,
            'new_gap': 0
        }
        for c in cluster_results_clean:
            slug = c.get('recommendation_slug')
            if slug in recommendation_counts:
                recommendation_counts[slug] += 1

        total_optimize = sum(1 for c in cluster_results_clean if c['recommendation_type'] == 'optimize')
        total_create = sum(1 for c in cluster_results_clean if c['recommendation_type'] == 'create_new')
        avg_distance = sum(c['semantic_distance'] for c in cluster_results_clean) / len(cluster_results_clean) if cluster_results_clean else 0
        
        # Aggregate by pages for page-focused view
        logger.info("Aggregating clusters by page")
        page_summary, create_new_recommendations = aggregate_clusters_by_page(cluster_results_clean)
        logger.info(f"Aggregated into {len(page_summary)} pages with {len(create_new_recommendations)} create-new recommendations")
        
        logger.info("Rendering results partial")
        return render_template(
            '/query-clustering/partial-results.html',
            cluster_results=cluster_results_clean,
            scatter_data=scatter_data_filtered,
            total_queries=len(unique_queries),
            total_clusters=len(cluster_results_clean),
            total_optimize=total_optimize,
            total_create=total_create,
            recommendation_counts=recommendation_counts,
            avg_distance=round(avg_distance, 3),
            page_summary=page_summary,
            create_new_recommendations=create_new_recommendations,
            date_range=f"{start_date_str} to {end_date_str}"
        )
        
    except Exception as e:
        logger.error(f"Error in query clustering analysis: {e}", exc_info=True)
        return render_template(
            '/query-clustering/partial-error.html',
            error_message=f"An error occurred during analysis: {str(e)}"
        ), 500


def fetch_granular_gsc_data(webmasters_service, property_url, start_date, end_date, 
                             countries, brand_keywords, brand_filter):
    """
    Fetch daily granular GSC data with DATE, QUERY, PAGE dimensions (aggregated across countries)
    """
    dimensions = ['DATE', 'QUERY', 'PAGE']
    
    # Build dimension filters
    dimensionFilterGroups = []
    
    # Add country filters if specified
    if countries and 'all' not in [c.lower() for c in countries]:
        country_filters = []
        for country in countries:
            country_filters.append({
                "dimension": "COUNTRY",
                "expression": country,
                "operator": "equals"
            })
        dimensionFilterGroups.append({"filters": country_filters})
    
    # Fetch data
    df = fetch_search_console_data(
        webmasters_service,
        property_url,
        start_date,
        end_date,
        dimensions,
        dimensionFilterGroups
    )
    
    
    # Normalize PAGE column: remove fragment identifiers (e.g., #slug)
    if 'PAGE' in df.columns:
        # Filter out potential image URLs that might sneak into Web results
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico', '.tiff', '.pdf')
        initial_count = len(df)
        df = df[~df['PAGE'].str.lower().str.endswith(image_extensions)]
        if len(df) < initial_count:
            logger.info(f"Filtered out {initial_count - len(df)} image/file URLs")

        logger.info("Normalizing URLs by removing fragments")
        df['PAGE'] = df['PAGE'].str.split('#').str[0]
        
        # After normalization, we might have duplicate rows for the same {DATE, QUERY, PAGE, COUNTRY}
        # because those rows previously had different #fragments.
        # We need to aggregate these.
        
        # Define dimension columns
        dim_cols = [c for c in df.columns if c in ['DATE', 'QUERY', 'PAGE', 'COUNTRY', 'keyword_type']]
        
        # Group by dimensions and aggregate metrics
        logger.info(f"Aggregating GSC data rows (initially {len(df)} rows)")
        
        # Aggregation logic:
        # clicks: sum
        # impressions: sum
        # position: weighted average by impressions
        
        # Calculate weighted position component before grouping
        df['pos_val'] = df['position'] * df['impressions']
        
        df_agg = df.groupby(dim_cols).agg({
            'clicks': 'sum',
            'impressions': 'sum',
            'pos_val': 'sum'
        }).reset_index()
        
        # Recalculate position and CTR
        df_agg['position'] = df_agg['pos_val'] / df_agg['impressions']
        df_agg['ctr'] = df_agg['clicks'] / df_agg['impressions']
        
        # Drop temporary column
        df = df_agg.drop('pos_val', axis=1)
        
        logger.info(f"Aggregated GSC data to {len(df)} rows")

    # Apply brand filter
    if brand_filter != 'both':
        df['keyword_type'] = df['QUERY'].apply(lambda q: keyword_type(q, brand_keywords))
        
        if brand_filter == 'brand':
            df = df[df['keyword_type'] == 'Branded']
        elif brand_filter == 'non-brand':
            df = df[df['keyword_type'] == 'Non Branded']
        
        df = df.drop('keyword_type', axis=1)
    
    return df


def generate_query_embeddings(queries, api_key):
    """
    Generate OpenAI embeddings for a list of queries
    Returns a dictionary mapping query -> embedding vector
    """
    client = OpenAI(api_key=api_key)
    
    embeddings_dict = {}
    batch_size = 1000  # Process in batches (increased for better performance)
    
    for i in range(0, len(queries), batch_size):
        batch = queries[i:i+batch_size]
        logger.info(f"Processing embedding batch {i//batch_size + 1}/{(len(queries)-1)//batch_size + 1}")
        
        try:
            response = client.embeddings.create(
                model="text-embedding-3-large",
                input=batch
            )
            
            for j, embedding_obj in enumerate(response.data):
                query = batch[j]
                embeddings_dict[query] = embedding_obj.embedding
                
        except Exception as e:
            logger.error(f"Error generating embeddings for batch: {e}")
            raise
    
    logger.info(f"Generated embeddings for {len(embeddings_dict)} queries")
    return embeddings_dict


def perform_hdbscan_clustering(embeddings_array, min_cluster_size=3, min_samples=1):
    """
    Perform HDBSCAN clustering on embeddings
    Returns array of cluster labels
    
    Parameters optimized for SEO query clustering:
    - min_cluster_size=3: Allow smaller semantic groups
    - min_samples=1: Less conservative density requirement
    - Normalize embeddings + euclidean: Equivalent to cosine distance
    - cluster_selection_method='leaf': More granular clusters
    """
    from sklearn.preprocessing import normalize
    
    # Normalize embeddings (L2 normalization)
    # This makes euclidean distance equivalent to cosine distance
    normalized_embeddings = normalize(embeddings_array, norm='l2')
    
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric='euclidean',  # On normalized vectors, this = cosine distance
        cluster_selection_method='leaf'
    )
    
    cluster_labels = clusterer.fit_predict(normalized_embeddings)
    
    n_clusters = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
    n_noise = list(cluster_labels).count(-1)
    
    logger.info(f"HDBSCAN found {n_clusters} clusters and {n_noise} noise points")
    
    return cluster_labels


def aggregate_cluster_metrics(df, embeddings_dict):
    """
    Aggregate metrics for each cluster
    """
    cluster_groups = df.groupby('cluster')
    
    results = []
    
    for cluster_id, group in cluster_groups:
        # Get sample queries (top 5 by impressions)
        top_queries = group.groupby('QUERY')['impressions'].sum().nlargest(5)
        sample_queries = top_queries.index.tolist()
        
        # Cluster name: use the top query (most impressions)
        cluster_name = sample_queries[0] if sample_queries else f"Cluster {cluster_id}"
        
        # Calculate total metrics
        total_impressions = group['impressions'].sum()
        total_clicks = group['clicks'].sum()
        
        # Calculate weighted average position
        weighted_avg_position = (group['position'] * group['impressions']).sum() / total_impressions
        
        # Identify primary page (page with most impressions for this cluster)
        primary_page = group.groupby('PAGE')['impressions'].sum().idxmax()
        
        # Get all unique queries in cluster
        all_queries = group['QUERY'].unique().tolist()
        
        # Calculate cluster centroid
        cluster_embeddings = [embeddings_dict[q] for q in all_queries if q in embeddings_dict]
        cluster_centroid = np.mean(cluster_embeddings, axis=0)
        
        results.append({
            'cluster_id': int(cluster_id),
            'cluster_name': cluster_name,
            'sample_queries': sample_queries,
            'all_queries': all_queries,
            'query_count': len(all_queries),
            'total_impressions': int(total_impressions),
            'total_clicks': int(total_clicks),
            'weighted_avg_position': round(weighted_avg_position, 2),
            'primary_page': primary_page,
            'cluster_centroid': cluster_centroid
        })
    
    # Sort by total impressions descending
    results = sorted(results, key=lambda x: x['total_impressions'], reverse=True)
    
    # Calculate Trends for each cluster
    for res in results:
        try:
            # Get data for this cluster
            c_id = res['cluster_id']
            cluster_df = df[df['cluster'] == c_id].copy()
            
            # Group by Date
            daily = cluster_df.groupby('DATE')['impressions'].sum().reset_index()
            daily['DATE'] = pd.to_datetime(daily['DATE'])
            daily = daily.sort_values('DATE')
            
            if len(daily) > 1:
                # Calculate slope using ordinal dates
                x = daily['DATE'].map(pd.Timestamp.toordinal).values
                y = daily['impressions'].values
                
                # Fit linear regression (degree 1)
                slope, intercept = np.polyfit(x, y, 1)
                
                res['trend_slope'] = float(slope)
                
                # Determine status based on slope
                # Thresholds can be tuned. Assuming daily impressions.
                if slope > 0.5:
                    res['trend_status'] = 'Rising'
                elif slope < -0.5:
                    res['trend_status'] = 'Declining'
                else:
                    res['trend_status'] = 'Stable'
            else:
                res['trend_slope'] = 0.0
                res['trend_status'] = 'Stable'
                
        except Exception as e:
            logger.warning(f"Error calculating trend for cluster {res.get('cluster_id')}: {e}")
            res['trend_slope'] = 0.0
            res['trend_status'] = 'Unknown'

    return results


def calculate_semantic_distance_and_decide(cluster_results, df, webmasters_service,
                                            property_url, start_date, end_date,
                                            embeddings_dict, api_key):
    """
    Tournament Logic Recommendation Engine.
    
    For each cluster:
    1. Identify Candidate Pages (pages ranking for ANY query in cluster).
    2. Calculate "Page Identity" for each candidate:
       - Weighted Centroid of Top 50 GLOBAL queries for that page.
    3. Score Candidates (Cosine Similarity vs Cluster Centroid).
    4. Determine Winner & Recommendation.
    """
    client = OpenAI(api_key=api_key)
    
    logger.info("Starting Tournament Prediction Logic")
    
    # Pre-calculate Page Identities for all relevant pages
    # This avoids re-calculating for every cluster if pages overlap
    relevant_pages = set()
    for res in cluster_results:
        # Get all queries in this cluster
        cluster_queries = res['all_queries']
        # Find pages ranking for these queries in the FULL df
        cluster_pages = df[df['QUERY'].isin(cluster_queries)]['PAGE'].unique()
        relevant_pages.update(cluster_pages)
    
    logger.info(f"Calculating Page Identities for {len(relevant_pages)} unique pages")
    
    page_identities = {}
    
    for page in relevant_pages:
        try:
            # 1. Get Top 50 Global Queries for this page
            page_df = df[df['PAGE'] == page]
            top_queries_df = page_df.groupby('QUERY')['impressions'].sum().nlargest(50).reset_index()
            
            if top_queries_df.empty:
                continue
                
            # 2. Collect Embeddings and Weights
            vectors = []
            weights = []
            
            for _, row in top_queries_df.iterrows():
                q = row['QUERY']
                imp = row['impressions']
                
                if q in embeddings_dict:
                    vec = embeddings_dict[q]
                else:
                    # Generate missing embedding
                    try:
                        resp = client.embeddings.create(model="text-embedding-3-large", input=[q])
                        vec = resp.data[0].embedding
                        embeddings_dict[q] = vec # Cache it
                    except Exception:
                        continue
                
                vectors.append(vec)
                weights.append(imp)
            
            if not vectors:
                continue
                
            # 3. Calculate Weighted Centroid
            vectors_array = np.array(vectors)
            weights_array = np.array(weights).reshape(-1, 1)
            
            # Avoid division by zero
            total_weight = np.sum(weights_array)
            if total_weight > 0:
                weighted_centroid = np.sum(vectors_array * weights_array, axis=0) / total_weight
                # Normalize the centroid
                from sklearn.preprocessing import normalize
                weighted_centroid = normalize(weighted_centroid.reshape(1, -1))[0]
                
                page_identities[page] = weighted_centroid
                
        except Exception as e:
            logger.warning(f"Error calculating identity for page {page}: {e}")
            continue
            
    # Run Tournament for each cluster
    for result in cluster_results:
        cluster_centroid = result['cluster_centroid']
        cluster_queries = result['all_queries']
        cluster_centroid_reshaped = cluster_centroid.reshape(1, -1)
        
        # Identify Candidates
        # Pages that rank for queries in this cluster
        ranking_pages_df = df[df['QUERY'].isin(cluster_queries)].groupby('PAGE').agg({
            'impressions': 'sum',
            'position': 'mean' # Simple mean for now
        }).reset_index()
        
        # Sort by impressions to find "Traffic King"
        ranking_pages_df = ranking_pages_df.sort_values('impressions', ascending=False)
        
        if ranking_pages_df.empty:
            # No ranking pages? Logical edge case.
            result['recommendation_slug'] = 'new_gap'
            result['recommendation'] = "🆕 Create New Page (Content Gap)"
            result['recommendation_type'] = 'create_new'
            result['rationale'] = "No pages currently rank for this topic."
            result['semantic_distance'] = 1.0
            result['candidate_pages'] = []
            continue
            
        traffic_king_page = ranking_pages_df.iloc[0]['PAGE']
        traffic_king_impressions = ranking_pages_df.iloc[0]['impressions']
        
        # Score Candidates
        candidate_scores = []
        
        for _, row in ranking_pages_df.iterrows():
            page = row['PAGE']
            impressions = row['impressions']
            
            if page in page_identities:
                page_vec = page_identities[page].reshape(1, -1)
                similarity = cosine_similarity(cluster_centroid_reshaped, page_vec)[0][0]
                distance = 1 - similarity
            else:
                # Fallback if no identity
                distance = 1.0
                similarity = 0.0
            
            candidate_scores.append({
                'page': page,
                'similarity': similarity,
                'distance': distance,
                'impressions': impressions,
                'is_traffic_king': (page == traffic_king_page)
            })
        
        # Find Semantic Leader
        candidate_scores.sort(key=lambda x: x['similarity'], reverse=True)
        best_candidate = candidate_scores[0]
        semantic_leader_page = best_candidate['page']
        max_similarity = best_candidate['similarity']
        
        # Find Traffic King Score
        traffic_king_score = next((c for c in candidate_scores if c['is_traffic_king']), None)
        traffic_king_similarity = traffic_king_score['similarity'] if traffic_king_score else 0.0
        
        # Decision Logic (The Tournament Rules)
        
        # Thresholds
        MIN_SIMILARITY_THRESHOLD = 0.25 
        
        # Lowered from 0.75 to 0.60 to capture broader semantic matches
        # and prevent false "Create New" recommendations for existing content.
        SIMILARITY_THRESHOLD = 0.60 
        SIGNIFICANT_DIFF = 0.1
        
        rec_slug = ''
        rationale = ''
        recommendation_type = ''
        target_page = None
        
        if max_similarity < SIMILARITY_THRESHOLD:
            # Check for single-word broad terms
            is_single_word = len(result['cluster_name'].strip().split()) <= 1
            
            if is_single_word:
                # Override "New Gap" for broad terms
                rec_slug = 'optimize_existing' # Downgrade to optimize/monitor
                rationale = f"Topic '{result['cluster_name']}' is a broad single-word term. Strategy: Optimize Category/Homepage structure rather than creating a specific new page."
                recommendation_type = 'optimize'
                target_page = traffic_king_page if traffic_king_page else "N/A"
            else:
                # Scenario A: The Void
                rec_slug = 'new_gap'
                rationale = f"No existing page on your site serves this topic well. The best match we found was '{semantic_leader_page}' but it only has a {int(max_similarity*100)}% semantic match. Validates a Content Gap."
                recommendation_type = 'create_new'
                target_page = None
        
        elif semantic_leader_page != traffic_king_page and max_similarity > (traffic_king_similarity + SIGNIFICANT_DIFF):
            # Scenario B: The Misalignment
            rec_slug = 'redirect_focus'
            rationale = f"The page getting the most traffic ('{traffic_king_page}') is only a {int(traffic_king_similarity*100)}% match. You have a significantly better page ('{semantic_leader_page}') that is a {int(max_similarity*100)}% match. Shift focus to the stronger semantic match."
            recommendation_type = 'optimize' # It's an optimization action (switch focus)
            target_page = semantic_leader_page
            
        else:
            # Scenario C: The Alignment (or close enough)
            rec_slug = 'optimize_existing'
            target_page = traffic_king_page # Default to traffic king
            
            trend = result.get('trend_status', 'Stable')
            avg_pos = result.get('weighted_avg_position', 20.0)
            
            # Smart Rationales based on Position & Trend
            match_str = f"({int(max_similarity*100)}% Match)"
            
            if avg_pos <= 3.0:
                # Market Leader Strategy
                if trend == 'Declining':
                     rationale = f"⚠️ CRITICAL: You are the Market Leader (Pos {avg_pos}) but traffic is Declining 📉. Competitors may be stealing share. Update content immediately."
                else:
                     rationale = f"🏆 Dominant Position (Pos {avg_pos}). Content is performing well {match_str}. Monitor to maintain authority."
            
            elif 3.0 < avg_pos <= 20.0:
                # Striking Distance Strategy
                if trend == 'Rising':
                    rationale = f"🚀 Striking Distance! Ranking (Pos {avg_pos}) and Rising 📈. Minor optimizations could push this to Top 3."
                else:
                    rationale = f"🎯 Striking Distance (Pos {avg_pos}). You are on Page 1/2. Improve content depth to crack the Top 3 {match_str}."
            
            else:
                # Underperformer / Opportunity
                rationale = f"📈 Opportunity: High impression potential but low rank (Pos {avg_pos}). This page is relevant {match_str} but needs significant optimization to compete."

            recommendation_type = 'optimize'

        # Map to UI Strings
        REC_MAP = {
            'optimize_existing': "✅ Optimize Existing Page",
            'redirect_focus': "🔄 Redirect Focus/Canonicalize",
            'new_gap': "🆕 Create New Page (Content Gap)"
        }
        
        result['recommendation_slug'] = rec_slug
        result['recommendation'] = REC_MAP.get(rec_slug, rec_slug)
        result['recommendation_type'] = recommendation_type
        result['rationale'] = rationale
        result['target_page'] = target_page
        result['semantic_distance'] = 1 - max_similarity if target_page else 1.0
        result['candidate_pages'] = candidate_scores[:10]
        
    return cluster_results


def generate_umap_projection(embeddings_array, cluster_labels, n_neighbors=15, min_dist=0.1):
    """
    Generate UMAP 2D projection for visualization
    """
    reducer = umap.UMAP(
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        n_components=2,
        metric='cosine',
        random_state=42
    )
    
    umap_coords = reducer.fit_transform(embeddings_array)
    
    return umap_coords


def create_scatter_plot_data(queries, cluster_labels, umap_coords, df):
    """
    Create data structure for Plotly scatter plot with impression data
    """
    scatter_data = []
    
    # Pre-calculate impressions for all queries to avoid O(N) lookup inside loop
    query_imp_map = df.groupby('QUERY')['impressions'].sum().to_dict()
    
    for i, query in enumerate(queries):
        # Get impressions for this query
        query_impressions = query_imp_map.get(query, 0)
        
        scatter_data.append({
            'query': query,
            'x': float(umap_coords[i, 0]),
            'y': float(umap_coords[i, 1]),
            'cluster': int(cluster_labels[i]) if cluster_labels[i] != -1 else 'Noise',
            'impressions': int(query_impressions)
        })
    
    return scatter_data


def aggregate_clusters_by_page(cluster_results):
    """
    Aggregate clusters by their target page for page-focused view.
    
    Returns:
    - page_summary: List of pages with aggregated metrics and clusters
    - create_new_recommendations: Clusters that need new pages
    """
    from collections import defaultdict
    
    page_data = defaultdict(lambda: {
        'clusters': [],
        'total_impressions': 0,
        'total_queries': 0,
        'total_clicks': 0,
        'position_weighted_sum': 0
    })
    
    create_new_recommendations = []
    
    for cluster in cluster_results:
        if cluster.get('target_page'):
            # Has a target page - aggregate
            page = cluster['target_page']
            page_data[page]['clusters'].append(cluster)
            page_data[page]['total_impressions'] += cluster['total_impressions']
            page_data[page]['total_queries'] += cluster['query_count']
            page_data[page]['total_clicks'] += cluster['total_clicks']
            page_data[page]['position_weighted_sum'] += (
                cluster['weighted_avg_position'] * cluster['total_impressions']
            )
        else:
            # No target page - needs new page creation
            create_new_recommendations.append(cluster)
    
    # Convert to list and calculate final metrics
    page_summary = []
    for page_url, data in page_data.items():
        # Calculate weighted average position
        avg_position = (
            data['position_weighted_sum'] / data['total_impressions']
            if data['total_impressions'] > 0 else 0
        )
        
        # Separate by recommendation type
        optimize_clusters = [
            c for c in data['clusters']
            if c['recommendation_type'] == 'optimize'
        ]
        
        page_summary.append({
            'page_url': page_url,
            'total_impressions': data['total_impressions'],
            'total_queries': data['total_queries'],
            'total_clicks': data['total_clicks'],
            'avg_position': round(avg_position, 2),
            'cluster_count': len(data['clusters']),
            'optimize_clusters': optimize_clusters,
            'num_optimize': len(optimize_clusters)
        })
    
    # Sort by total impressions (descending)
    page_summary.sort(key=lambda x: x['total_impressions'], reverse=True)
    
    return page_summary, create_new_recommendations
