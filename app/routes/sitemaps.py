"""Sitemap health -- what Google has, when it last read it, and what broke.

Wraps the sitemaps.list endpoint, which the app already called once inside a
debug page nobody linked to. Nothing here writes: submitting and deleting
sitemaps are destructive and belong behind an explicit action, not a report.
"""

from datetime import datetime

from flask import render_template, redirect, url_for, flash, session

from app import app
from app.routes.gsc_api_auth import build_gsc_service
from app.routes.gsc_routes import get_cached_latest_date


def _parse_timestamp(value):
    """RFC 3339 timestamp to datetime, or None. Google sends 'Z' for UTC."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def _summarise_sitemap(entry):
    """One sitemap as the template wants it, with a state to sort and style by."""
    errors = int(entry.get('errors') or 0)
    warnings = int(entry.get('warnings') or 0)
    is_pending = bool(entry.get('isPending'))

    # The per-content-type `indexed` count is marked deprecated in the API
    # schema, so only `submitted` is reported here.
    submitted = 0
    content_types = []
    for content in entry.get('contents') or []:
        submitted += int(content.get('submitted') or 0)
        if content.get('type'):
            content_types.append(str(content['type']))

    if errors:
        state, state_label = 'error', 'Errors'
    elif is_pending:
        state, state_label = 'pending', 'Not read yet'
    elif warnings:
        state, state_label = 'warning', 'Warnings'
    else:
        state, state_label = 'ok', 'OK'

    last_downloaded = _parse_timestamp(entry.get('lastDownloaded'))
    stale_days = None
    if last_downloaded:
        stale_days = (datetime.now(last_downloaded.tzinfo) - last_downloaded).days

    return {
        'path': entry.get('path', ''),
        'type': entry.get('type') or '—',
        'is_index': bool(entry.get('isSitemapsIndex')),
        'is_pending': is_pending,
        'errors': errors,
        'warnings': warnings,
        'submitted': submitted,
        'content_types': ', '.join(content_types) or '—',
        'last_downloaded': last_downloaded,
        'last_submitted': _parse_timestamp(entry.get('lastSubmitted')),
        'stale_days': stale_days,
        'state': state,
        'state_label': state_label,
    }


@app.route('/reports/sitemaps/', methods=['GET'])
def sitemaps_report():
    if 'credentials' not in session:
        return redirect(url_for('gsc_authorize'))

    selected_property = session.get(
        "selected_property", "You haven't selected a GSC Property yet")

    if selected_property == "You haven't selected a GSC Property yet":
        flash('Please Select your GSC Property.')
        return redirect(url_for('gsc_property_selection'))

    sitemaps = []
    fetch_error = None

    try:
        service = build_gsc_service()
        response = service.sitemaps().list(siteUrl=selected_property).execute()
        sitemaps = [_summarise_sitemap(entry)
                    for entry in response.get('sitemap', [])]
    except Exception as exc:
        app.logger.warning(f"Could not list sitemaps for {selected_property}: {exc}")
        fetch_error = str(exc)

    # Problems first, then never-read, then everything else by size.
    state_order = {'error': 0, 'pending': 1, 'warning': 2, 'ok': 3}
    sitemaps.sort(key=lambda s: (state_order.get(s['state'], 9), -s['submitted']))

    totals = {
        'count': len(sitemaps),
        'submitted': sum(s['submitted'] for s in sitemaps),
        'errors': sum(s['errors'] for s in sitemaps),
        'warnings': sum(s['warnings'] for s in sitemaps),
        'pending': sum(1 for s in sitemaps if s['is_pending']),
    }

    latest_date = ''
    try:
        latest_date = get_cached_latest_date(selected_property)
    except Exception as e:
        app.logger.warning(f"Error fetching latest date for sitemaps: {e}")

    return render_template('/sitemaps/main.html',
                           selected_property=selected_property,
                           sitemaps=sitemaps,
                           totals=totals,
                           fetch_error=fetch_error,
                           latest_date=latest_date)
