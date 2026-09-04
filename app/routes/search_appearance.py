"""Search Appearance report -- performance split by SERP feature.

Search Console can group results by SEARCH_APPEARANCE: the rich-result types a
page qualified for when it was shown. It answers a question no other report
here can: you know your markup is valid, but does it earn anything?

The API will not combine SEARCH_APPEARANCE with other dimensions in one call,
so the trend line is a second request filtered to one appearance type.
"""

from datetime import datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, session

from app import app
from app.routes.gsc_api_auth import build_gsc_service, fetch_search_console_data
from app.routes.gsc_routes import (format_dates, get_cached_latest_date,
                                   process_dates, report_errors)
from app.routes.segments import active_segment, apply_segment, segment_summary

# Google returns machine names; these are what Search Console calls them.
APPEARANCE_LABELS = {
    'AMP_BLUE_LINK': 'AMP article',
    'AMP_STORY': 'Web Story',
    'AMP_TOP_STORIES': 'AMP in Top stories',
    'PRODUCT_SNIPPETS': 'Product snippet',
    'MERCHANT_LISTINGS': 'Merchant listing',
    'ORGANIC_SHOPPING': 'Organic shopping',
    'REVIEW_SNIPPET': 'Review snippet',
    'RECIPE_FEATURE': 'Recipe',
    'RECIPE_RICH_SNIPPET': 'Recipe rich result',
    'JOB_LISTING': 'Job posting',
    'EVENT_DETAILS': 'Event',
    'EVENT_RICH_SNIPPET': 'Event rich result',
    'FAQ_RICH_SNIPPET': 'FAQ',
    'HOW_TO_RICH_SNIPPET': 'How-to',
    'VIDEO': 'Video',
    'TRANSLATED_RESULT': 'Translated result',
    'PRACTICE_PROBLEMS': 'Practice problem',
    'MATH_SOLVERS': 'Math solver',
    'EDU_Q_AND_A': 'Q&A',
    'SUBSCRIBED_CONTENT': 'Subscribed content',
    'DATASET': 'Dataset',
    'COURSE': 'Course',
    'AI_OVERVIEW': 'AI Overview',
}


def appearance_label(raw):
    """Human name for an appearance type, falling back to a tidied machine name."""
    if raw in APPEARANCE_LABELS:
        return APPEARANCE_LABELS[raw]
    return str(raw).replace('_', ' ').title()


def _summarise(df):
    """Totals per appearance type, with CTR derived rather than averaged."""
    if df.empty or 'SEARCH_APPEARANCE' not in df.columns:
        return []

    grouped = df.groupby('SEARCH_APPEARANCE').agg(
        clicks=('clicks', 'sum'),
        impressions=('impressions', 'sum'),
        position_weight=('position_weight', 'sum'),
    ).reset_index()

    rows = []
    for _, row in grouped.iterrows():
        impressions = int(row['impressions'])
        clicks = int(row['clicks'])
        rows.append({
            'type': row['SEARCH_APPEARANCE'],
            'label': appearance_label(row['SEARCH_APPEARANCE']),
            'clicks': clicks,
            'impressions': impressions,
            'ctr': round(clicks / impressions * 100, 2) if impressions else 0.0,
            'position': round(row['position_weight'] / impressions, 1) if impressions else 0.0,
        })

    rows.sort(key=lambda r: r['clicks'], reverse=True)
    return rows


def _fetch(service, property_url, start, end, filter_groups):
    df = fetch_search_console_data(
        service, property_url, start, end, ['SEARCH_APPEARANCE'], filter_groups)
    if not df.empty:
        # Position is impression-weighted, so keep the component to sum.
        df['position_weight'] = df['position'] * df['impressions']
    return df


@app.route('/reports/search-appearance/', methods=['GET', 'POST'])
@report_errors
def search_appearance_report():
    if 'credentials' not in session:
        return redirect(url_for('gsc_authorize'))

    selected_property = session.get(
        "selected_property", "You haven't selected a GSC Property yet")

    if selected_property == "You haven't selected a GSC Property yet":
        flash('Please Select your GSC Property.')
        return redirect(url_for('gsc_property_selection'))

    if request.method == 'POST':
        webmasters_service = build_gsc_service()

        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')

        (current_start, current_end, previous_start, previous_end,
         _py_start, _py_end) = process_dates(start_date_str, end_date_str)

        if current_start is None:
            return ("<div class='alert alert-warning'>Could not read that date "
                    "range. Pick the dates again.</div>")

        segment = active_segment()
        filter_groups = apply_segment([], segment)

        current_rows = _summarise(
            _fetch(webmasters_service, selected_property,
                   current_start, current_end, filter_groups))

        previous_rows = _summarise(
            _fetch(webmasters_service, selected_property,
                   previous_start, previous_end, filter_groups))

        if not current_rows:
            return ("<div class='alert alert-warning'>No search appearance data "
                    "for this range. Most sites only have appearance types once "
                    "they earn rich results, so an empty report here usually "
                    "means no rich results were shown &mdash; not an error.</div>")

        previous_by_type = {row['type']: row for row in previous_rows}
        total_clicks = sum(row['clicks'] for row in current_rows) or 1

        for row in current_rows:
            row['share'] = round(row['clicks'] / total_clicks * 100, 1)
            prior = previous_by_type.get(row['type'])
            if prior and prior['clicks']:
                row['clicks_change'] = round(
                    (row['clicks'] - prior['clicks']) / prior['clicks'] * 100, 1)
            elif prior:
                row['clicks_change'] = None       # was zero, no meaningful %
            else:
                row['clicks_change'] = 'new'

        return render_template(
            '/search-appearance/partial.html',
            rows=current_rows,
            current_start=current_start, current_end=current_end,
            previous_start=previous_start, previous_end=previous_end,
            segment_summary=segment_summary(segment),
            max_clicks=max(row['clicks'] for row in current_rows))

    # GET
    latest_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    try:
        latest_date = get_cached_latest_date(selected_property)
    except Exception as e:
        app.logger.warning(f"Error fetching latest date for search appearance: {e}")

    return render_template('/search-appearance/main.html',
                           selected_property=selected_property,
                           brand_keywords=session.get("brand_keywords", ""),
                           latest_date=latest_date)
