"""Route guards: is there a signed-in Google account, and a chosen property.

Both questions used to be asked inline in every view, the second by comparing
against the literal string "You haven't selected a GSC Property yet" -- which
was simultaneously the stored default, the "unset" sentinel, and the text shown
to the user. One typo in one of the forty-one copies silently disabled a guard,
and improving the wording would have broken the logic.

Here the sentinel is gone: `selected_property()` returns None when nothing is
chosen, and the decorators below answer both questions once.
"""

from functools import wraps

import flask
from flask import flash, redirect, request, session, url_for

# Kept only so sessions written before this change still read as "unset".
LEGACY_PROPERTY_SENTINEL = "You haven't selected a GSC Property yet"
LEGACY_BRAND_SENTINEL = "You haven't selected Brand Keywords."


def is_signed_in():
    """True when this session has a usable Google Search Console connection."""
    return 'credentials' in session or bool(session.get('connection_id'))


def selected_property():
    """The chosen property's site URL, or None when nothing is chosen."""
    value = session.get('selected_property')
    if not value or value == LEGACY_PROPERTY_SENTINEL:
        return None
    return value


def brand_keywords():
    """Brand terms for the chosen property, always a list (possibly empty)."""
    value = session.get('brand_keywords')
    if not value or value == LEGACY_BRAND_SENTINEL:
        return []
    if isinstance(value, str):
        return [term.strip() for term in value.split(',') if term.strip()]
    return list(value)


def _redirect_to(endpoint, message=None):
    """Redirect that also works when HTMX is doing the asking.

    HTMX swaps a redirect's *body* into the target element, so a plain 302 from
    a report POST would inline the sign-in page into a results panel. HX-Redirect
    tells it to navigate instead.
    """
    if message:
        flash(message)
    target = url_for(endpoint)

    if request.headers.get('HX-Request'):
        response = flask.make_response(
            f"<div class='alert alert-warning'>{message or 'Redirecting'}&hellip;</div>")
        response.headers['HX-Redirect'] = target
        return response

    return redirect(target)


def requires_gsc(view):
    """The route needs a connected Search Console account."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_signed_in():
            return _redirect_to('gsc_authorize',
                                "Connect your Google Search Console account to continue.")
        return view(*args, **kwargs)
    return wrapper


def requires_property(view):
    """The route needs a connected account *and* a chosen property.

    The view is called with no extra arguments -- read the property with
    selected_property() -- so adding the decorator never changes a signature.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_signed_in():
            return _redirect_to('gsc_authorize',
                                "Connect your Google Search Console account to continue.")
        if selected_property() is None:
            return _redirect_to('gsc_property_selection',
                                "Choose a Search Console property first.")
        return view(*args, **kwargs)
    return wrapper
