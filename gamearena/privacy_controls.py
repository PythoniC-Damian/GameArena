"""Age declarations and optional first-party analytics choices."""
from datetime import date, datetime, timedelta, timezone
import time
import click
from flask import Blueprint, current_app, request, session, redirect, url_for, render_template, jsonify, flash
from flask_login import current_user, login_required
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import delete
from gamearena.extensions import db

privacy_controls = Blueprint('privacy_controls', __name__)
POLICY = '2026-10-27'
COOKIE = 'ga_privacy'
MAX_AGE = 180 * 24 * 3600

def age_error(value):
    try:
        born = date.fromisoformat(value or '')
    except (ValueError, TypeError):
        return 'Enter your date of birth to confirm you are at least 18.'
    today = datetime.now(timezone(timedelta(hours=1))).date()
    age = today.year-born.year-((today.month,today.day)<(born.month,born.day))
    if age < 18 or age > 120:
        return 'GameArena is for adults aged 18 and over. Contact support about an existing account or balance.'

def signup_declaration():
    marker = session.get('adult_signup_at')
    return isinstance(marker,(float,int)) and 0 <= time.time()-marker <= 600

def record_adult(user):
    user.adult_confirmed_at = datetime.utcnow()
    user.adult_policy_version = POLICY

def adult_access_allowed(user=None):
    if not current_app.config.get('ADULT_ACCESS_REQUIRED', True): return True
    user = user or current_user
    return bool(user.is_authenticated and user.adult_confirmed_at and user.adult_policy_version == POLICY)

def serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='privacy-choices-v1')

def choices():
    try:
        value = serializer().loads(request.cookies.get(COOKIE,''), max_age=MAX_AGE)
        if value.get('version') == POLICY and type(value.get('analytics')) is bool:
            return {'decided':True, 'analytics':value['analytics']}
    except (BadSignature, SignatureExpired, AttributeError, TypeError): pass
    return {'decided':False, 'analytics':False}

def analytics_allowed():
    return choices()['analytics']

@privacy_controls.route('/privacy/choices', methods=['GET','POST'])
def preferences():
    if request.method == 'GET': return render_template('privacy_choices.html', privacy_choice=choices())
    data = request.get_json(silent=True) if request.is_json else request.form
    choice = (data or {}).get('choice')
    if choice not in {'accept','reject'}: return jsonify(error='Choose accept or reject.'),400
    enabled = choice == 'accept'
    # Withdrawal also clears this signed-in player's optional usage records.
    if not enabled and current_user.is_authenticated:
        from gamearena.models import UserActivityDay, TournamentVisit
        db.session.execute(delete(UserActivityDay).where(UserActivityDay.user_id==current_user.id))
        db.session.execute(delete(TournamentVisit).where(TournamentVisit.user_id==current_user.id))
        db.session.commit()
        session.pop('_activity_day',None)
    response = jsonify(analytics=enabled) if request.is_json else redirect(url_for('.preferences'))
    response.set_cookie(COOKIE,serializer().dumps({'version':POLICY,'analytics':enabled}),
        max_age=MAX_AGE, secure=request.is_secure, httponly=True, samesite='Lax', path='/')
    return response

@privacy_controls.route('/account/eligibility',methods=['GET','POST'])
@login_required
def eligibility():
    error = None
    if request.method == 'POST':
        error = age_error(request.form.get('date_of_birth'))
        if not error and request.form.get('adult_confirm') != 'yes': error = 'Confirm that the information is accurate.'
        if not error:
            record_adult(current_user);db.session.commit()
            flash('Your adult eligibility declaration has been recorded.','success')
            return redirect(url_for('dashboard'))
    return render_template('adult_eligibility.html',error=error)

def age_guard():
    endpoint = request.endpoint or ''
    if endpoint in {'static','health','service_worker','android_asset_links','logout','login','register','login_google','signup_google','google_callback','supabase_callback','verify_email','support'}: return
    if endpoint.startswith(('privacy_controls.','legal.','support_center.','security.')): return
    if any(word in endpoint for word in ('callback','webhook','verify_payment')): return
    if endpoint=='settings' and request.view_args.get('section')=='data': return
    if current_user.is_authenticated and not adult_access_allowed():
        if request.is_json or request.path.startswith(('/api/','/socket.io/')):
            return jsonify(error='Adult eligibility confirmation required.',url=url_for('privacy_controls.eligibility')),403
        return redirect(url_for('privacy_controls.eligibility'))

def purge_usage(before=None):
    from gamearena.models import UserActivityDay,TournamentVisit
    cutoff=before or datetime.utcnow()-timedelta(days=90)
    # Never remove payments, messages, entries or dispute evidence here.
    with db.engine.begin() as connection:
        connection.execute(delete(UserActivityDay).where(UserActivityDay.activity_date<cutoff.date()))
        connection.execute(delete(TournamentVisit).where(TournamentVisit.viewed_at<cutoff))

_last_cleanup=-86400

def cleanup_usage(response):
    global _last_cleanup
    if request.endpoint in {'static','health','service_worker'} or current_app.testing: return response
    now=time.monotonic()
    if now-_last_cleanup<86400: return response
    _last_cleanup=now
    try: purge_usage()
    except Exception:
        _last_cleanup=now-82800
        current_app.logger.warning('Optional usage retention cleanup needs attention.')
    return response

def init_privacy(app):
    app.config.setdefault('ADULT_ACCESS_REQUIRED',True)
    app.register_blueprint(privacy_controls)
    app.before_request(age_guard)
    app.after_request(cleanup_usage)
    app.context_processor(lambda: {'privacy_choice':choices()})
    @app.cli.command('purge-usage-data')
    def purge_command():
        """Delete optional visit/activity records older than 90 days."""
        purge_usage();click.echo('Optional usage retention cleanup completed.')
