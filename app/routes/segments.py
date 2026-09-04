"""Saved segments -- reusable page/query filters applied to any report.

Search Console can filter a query by page or query string with regex, contains
and equality operators, but the app only ever sent `equals`. A segment is a
named, reusable filter ("Blog only", "Question queries", "Everything except
brand") that any report can be run through, which turns each existing report
into as many reports as the user has segments.

Segments live in the session. That means they last as long as the sign-in and
are not shared between devices -- the honest limitation until the app has a
database. Everything here goes through get_segments()/save_segments(), so
moving to a table later is a change in two functions.
"""

import re
import uuid

from flask import (render_template, request, redirect, url_for, flash, session,
                   jsonify)

from app import app

# Operators the Search Console API accepts for a dimension filter, mapped to
# what they mean for someone building a segment.
SEGMENT_OPERATORS = {
    'includingRegex': 'matches regex',
    'excludingRegex': 'does not match regex',
    'contains': 'contains',
    'notContains': 'does not contain',
    'equals': 'is exactly',
    'notEquals': 'is not',
}

SEGMENT_DIMENSIONS = {
    'PAGE': 'Page URL',
    'QUERY': 'Search query',
}

MAX_SEGMENTS = 25
MAX_EXPRESSION_LENGTH = 4000


def get_segments():
    """Every saved segment for this session, oldest first."""
    segments = session.get('segments')
    return list(segments) if isinstance(segments, list) else []


def save_segments(segments):
    session['segments'] = segments


def get_segment(segment_id):
    """One segment by id, or None."""
    if not segment_id:
        return None
    for segment in get_segments():
        if segment.get('id') == segment_id:
            return segment
    return None


def validate_segment(name, dimension, operator, expression):
    """Return an error string, or None when the segment is usable.

    The regex check is a smoke test: Google evaluates RE2 and Python evaluates
    its own flavour, so this catches typos and unbalanced brackets rather than
    guaranteeing acceptance. A pattern that passes here and is still rejected
    comes back as a readable API error rather than a 500.
    """
    if not name or not name.strip():
        return "Give the segment a name."
    if dimension not in SEGMENT_DIMENSIONS:
        return "Choose whether the segment filters on page or query."
    if operator not in SEGMENT_OPERATORS:
        return "Choose how the segment should match."
    if not expression or not expression.strip():
        return "Enter what the segment should match."
    if len(expression) > MAX_EXPRESSION_LENGTH:
        return f"That pattern is too long (limit {MAX_EXPRESSION_LENGTH} characters)."

    if operator in ('includingRegex', 'excludingRegex'):
        try:
            re.compile(expression)
        except re.error as exc:
            return f"That isn't a valid regular expression: {exc}"

    return None


def segment_filter(segment):
    """The API dimension filter for a segment."""
    return {
        "dimension": segment['dimension'],
        "operator": segment['operator'],
        "expression": segment['expression'],
    }


def apply_segment(dimension_filter_groups, segment):
    """Add a segment's filter to an existing dimensionFilterGroups list.

    The API ANDs filter groups together, so the segment goes in its own group
    and narrows whatever the report already asked for rather than replacing it.
    Returns a new list; the caller's is left alone.
    """
    groups = list(dimension_filter_groups or [])
    if segment:
        groups.append({"filters": [segment_filter(segment)]})
    return groups


def active_segment():
    """The segment named by the current request, if any.

    Reads `segment_id` from the form on a POST and the query string on a GET,
    so a report only has to pass its filter groups through apply_segment().
    """
    segment_id = request.form.get('segment_id') or request.args.get('segment_id')
    return get_segment(segment_id)


def segment_summary(segment):
    """One-line description, for report headers and the picker."""
    if not segment:
        return None
    return (f"{SEGMENT_DIMENSIONS.get(segment['dimension'], segment['dimension'])} "
            f"{SEGMENT_OPERATORS.get(segment['operator'], segment['operator'])} "
            f"“{segment['expression']}”")


@app.context_processor
def inject_segments():
    """Make the segment list available to every report template."""
    return {
        'segments': get_segments(),
        'active_segment_id': (request.form.get('segment_id')
                              or request.args.get('segment_id') or ''),
    }


@app.route('/segments/', methods=['GET'])
def segments_page():
    if 'credentials' not in session:
        return redirect(url_for('gsc_authorize'))

    selected_property = session.get(
        "selected_property", "You haven't selected a GSC Property yet")

    return render_template('/segments/main.html',
                           selected_property=selected_property,
                           saved_segments=get_segments(),
                           dimensions=SEGMENT_DIMENSIONS,
                           operators=SEGMENT_OPERATORS,
                           latest_date=session.get(
                               'latest_date_cache', {}).get('date', ''))


@app.route('/segments/create', methods=['POST'])
def create_segment():
    if 'credentials' not in session:
        return redirect(url_for('gsc_authorize'))

    name = (request.form.get('name') or '').strip()
    dimension = request.form.get('dimension') or ''
    operator = request.form.get('operator') or ''
    expression = (request.form.get('expression') or '').strip()

    error = validate_segment(name, dimension, operator, expression)
    if error:
        flash(error)
        return redirect(url_for('segments_page'))

    segments = get_segments()
    if len(segments) >= MAX_SEGMENTS:
        flash(f"You can save up to {MAX_SEGMENTS} segments. Delete one first.")
        return redirect(url_for('segments_page'))

    segments.append({
        'id': f"seg_{uuid.uuid4().hex[:12]}",
        'name': name[:60],
        'dimension': dimension,
        'operator': operator,
        'expression': expression,
    })
    save_segments(segments)
    flash(f"Segment “{name}” saved.")
    return redirect(url_for('segments_page'))


@app.route('/segments/<segment_id>/delete', methods=['POST'])
def delete_segment(segment_id):
    if 'credentials' not in session:
        return redirect(url_for('gsc_authorize'))

    segments = get_segments()
    remaining = [s for s in segments if s.get('id') != segment_id]

    if len(remaining) == len(segments):
        flash("That segment no longer exists.")
    else:
        save_segments(remaining)
        flash("Segment deleted.")

    return redirect(url_for('segments_page'))


@app.route('/segments/preview', methods=['POST'])
def preview_segment():
    """Count what a segment would match, before saving it.

    Answers the question that stops people trusting a regex: does this actually
    select the pages I think it does?
    """
    if 'credentials' not in session:
        return jsonify({'error': 'Not signed in to Search Console'}), 401

    dimension = request.form.get('dimension') or ''
    operator = request.form.get('operator') or ''
    expression = (request.form.get('expression') or '').strip()

    error = validate_segment('preview', dimension, operator, expression)
    if error:
        return render_template('/segments/partial-preview.html', error=error)

    selected_property = session.get("selected_property")
    if not selected_property or selected_property.startswith("You haven't"):
        return render_template('/segments/partial-preview.html',
                               error="Select a Search Console property first.")

    # Imported here rather than at module scope: default_routes imports this
    # module's helpers, and importing it back at load time would be circular.
    from datetime import datetime, timedelta
    from app.routes.gsc_api_auth import build_gsc_service, fetch_search_console_data

    end_date = datetime.now() - timedelta(days=3)
    start_date = end_date - timedelta(days=27)

    try:
        service = build_gsc_service()
        df = fetch_search_console_data(
            service, selected_property,
            start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'),
            [dimension],
            [{"filters": [{"dimension": dimension,
                           "operator": operator,
                           "expression": expression}]}])
    except Exception as exc:
        app.logger.warning(f"Segment preview failed: {exc}")
        return render_template(
            '/segments/partial-preview.html',
            error=f"Search Console rejected that filter: {exc}")

    if df.empty:
        return render_template('/segments/partial-preview.html', matched=0,
                               dimension=SEGMENT_DIMENSIONS[dimension])

    examples = df.sort_values(by='impressions', ascending=False)[dimension].head(5).tolist()
    return render_template('/segments/partial-preview.html',
                           matched=len(df),
                           clicks=int(df['clicks'].sum()),
                           impressions=int(df['impressions'].sum()),
                           examples=examples,
                           dimension=SEGMENT_DIMENSIONS[dimension])
