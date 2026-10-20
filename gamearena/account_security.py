"""Authenticator MFA, fresh authentication, origin validation and bounded security telemetry."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse
from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, logout_user, user_logged_in, user_logged_out
from werkzeug.wsgi import get_host
from werkzeug.exceptions import SecurityError
from werkzeug.wrappers import Response
from gamearena.extensions import db
from gamearena.models import AccountSecurity, SecurityAuditEvent, User

security = Blueprint('security', __name__)
FRESH_SECONDS = 600
_metrics = {}
_metrics_lock = threading.Lock()
_last_alert_email = 0


def cipher():
    key = current_app.config.get('SECURITY_ENCRYPTION_KEY')
    if not key:
        # Domain separated from session signatures; configure a separate key before
        # enrollment if independent key rotation is required. Never log either key.
        key = base64.urlsafe_b64encode(hmac.new(current_app.secret_key.encode(), b'gamearena-mfa-encryption-v1', hashlib.sha256).digest())
    return Fernet(key)


def recovery_hash(code):
    # Uniformly random 128-bit recovery tokens are not human passwords. A domain
    # separated digest avoids ten expensive password hashes on each enrollment.
    return hashlib.sha256(b'gamearena-recovery-v1:' + code.encode()).hexdigest()


def decrypt_factor(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError, UnicodeError):
        current_app.logger.error('security_alert kind=mfa_decryption_failed')
        abort(503, description='Account protection is temporarily unavailable. Contact support.')


def totp(secret, counter):
    key = base64.b32decode(secret + '='*((-len(secret)) % 8))
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = struct.unpack('>I', digest[offset:offset+4])[0] & 0x7fffffff
    return str(value % 1000000).zfill(6)


def matching_counter(secret, code, after=-1):
    if not re.fullmatch(r'[0-9]{6}', code): return None
    now = int(time.time()) // 30
    for counter in (now-1, now, now+1):
        if counter > after and counter >= 0 and hmac.compare_digest(totp(secret, counter), code):
            return counter
    return None


def consume_factor(row, code):
    """Caller holds user/security locks; a factor or recovery code is single use."""
    if not row or not row.enabled_at: return False
    secret = decrypt_factor(row.totp_secret)
    counter = matching_counter(secret, code.strip(), row.last_counter)
    if counter is not None:
        row.last_counter = counter
        return True
    recovery = code.strip().replace('-', '').lower()
    if not re.fullmatch(r'[0-9a-f]{32}', recovery): return False
    for index, hashed in enumerate(row.recovery_hashes or []):
        if hmac.compare_digest(hashed, recovery_hash(recovery)):
            row.recovery_hashes = row.recovery_hashes[:index] + row.recovery_hashes[index+1:]
            return True
    return False


def fresh_primary():
    stamp = session.get('security_primary_at', 0)
    return session.get('security_primary_uid') == current_user.id and 0 <= time.time()-stamp <= FRESH_SECONDS


def mfa_verified(row, age=12*3600):
    return bool(row and row.enabled_at and session.get('security_mfa_uid')==current_user.id
        and session.get('security_mfa_version')==row.version
        and 0 <= time.time()-session.get('security_mfa_at',0) <= age)


def mark_mfa(row):
    session['security_mfa_uid'] = row.user_id
    session['security_mfa_version'] = row.version
    session['security_mfa_at'] = time.time()


def primary_login(sender, user, **kwargs):
    for key in list(session):
        if key.startswith('security_'): session.pop(key, None)
    session['security_primary_at'] = time.time()
    session['security_primary_uid'] = user.id
    g.security_actor_id=user.id;g.security_actor_admin=user.is_admin
    g.security_events = getattr(g,'security_events',[]) + ['auth.login_success']


def primary_logout(sender,user,**kwargs):
    g.security_actor_id=user.id;g.security_actor_admin=user.is_admin
    note('auth.logout')


def locked_security(create=False):
    User.query.filter_by(id=current_user.id).with_for_update().populate_existing().one()
    row = AccountSecurity.query.filter_by(user_id=current_user.id).with_for_update().populate_existing().first()
    if not row and create:
        row = AccountSecurity(user_id=current_user.id)
        db.session.add(row); db.session.flush()
    return row


def limited():
    from app import consume_rate_limit
    if consume_rate_limit('security_challenge:'+str(current_user.id),5,60) is not None:
        abort(429, description='Too many authentication attempts. Try again in a minute.')


def note(event):
    g.security_events = getattr(g,'security_events',[]) + [event]


def metric(kind, threshold):
    """Bounded, per-worker alert counters; structured request logs support fleet aggregation."""
    minute = int(time.time()) // 60
    with _metrics_lock:
        for key in list(_metrics):
            if key[1] < minute-2: del _metrics[key]
        key = (kind, minute)
        _metrics[key] = _metrics.get(key,0)+1
        crossed = _metrics[key] == threshold
    if crossed:
        current_app.logger.warning('security_alert kind=%s window_seconds=60 threshold=%s scope=worker',kind,threshold)
        global _last_alert_email
        recipient=current_app.config.get('SECURITY_ALERT_EMAIL','')
        with _metrics_lock:
            send=bool(recipient and time.monotonic()-_last_alert_email>=300)
            if send:_last_alert_email=time.monotonic()
        if send:
            app=current_app._get_current_object()
            def deliver():
                with app.app_context():
                    from gamearena.services.email import send_email
                    accepted=send_email('GameArena security alert',recipient,
                        f'GameArena observed {kind}: threshold {threshold} within a 60-second worker window. Review your hosting security logs and administrator security events. No credentials or player details are included in this message.')
                    if not accepted:app.logger.warning('security_alert kind=alert_email_delivery_failed')
            from app import socketio
            socketio.start_background_task(deliver)


def deny_for_security(endpoint, code, message):
    next_page = '/wallet' if request.path.startswith('/wallet') else '/admin' if request.path.startswith('/admin') else '/organizers' if request.path.startswith('/organizers') else '/dashboard'
    target = url_for(endpoint, next=next_page)
    if request.is_json or request.accept_mimetypes.best == 'application/json':
        return jsonify({'status':'error','code':code,'message':message,'security_url':target}),403
    flash(message,'warning')
    return redirect(target)


def safe_next():
    value = request.values.get('next','/dashboard')
    if not value.startswith('/') or value.startswith('//') or '\\' in value or any(ord(c)<32 for c in value):
        return '/dashboard'
    parsed = urlparse(value)
    return parsed.path if not parsed.netloc and not parsed.scheme else '/dashboard'


def origin_guard():
    g.csp_nonce = secrets.token_urlsafe(24)


class OriginGate:
    """Outside Engine.IO as well as Flask, so direct socket handshakes are covered."""
    def __init__(self, app, wrapped): self.app,self.wrapped=app,wrapped

    def __call__(self,environ,start_response):
        try: get_host(environ,trusted_hosts=self.app.config['TRUSTED_HOSTS'])
        except SecurityError:
            return Response('Request not permitted.',status=400)(environ,start_response)
        enabled=self.app.config['ORIGIN_PROTECTION_ENABLED']
        health=environ.get('PATH_INFO')=='/health' and environ.get('REQUEST_METHOD') in ('GET','HEAD')
        if enabled and not health and not hmac.compare_digest(environ.get('HTTP_X_GAMEARENA_ORIGIN','').encode(),self.app.config['ORIGIN_SHARED_SECRET'].encode()):
            with self.app.app_context(): metric('origin_rejection',10)
            return Response('{"error":"Request not permitted."}',status=403,content_type='application/json')(environ,start_response)
        return self.wrapped(environ,start_response)


def socket_identity_allowed():
    if not current_user.is_authenticated or current_user.suspended: return False
    row=db.session.get(AccountSecurity,current_user.id)
    if row and row.enabled_at or current_user.is_admin and current_app.config['SECURITY_ENFORCE_ADMIN_MFA']:
        return mfa_verified(row)
    return True


def account_guard():
    if not current_user.is_authenticated or current_user.suspended: return
    g.security_actor_id=current_user.id;g.security_actor_admin=current_user.is_admin
    if request.endpoint and (request.endpoint.startswith('security.') and request.endpoint!='security.events' or request.endpoint in {'static','logout','health','login','login_google','google_callback','auth_callback','auth_google_callback'}): return
    row = db.session.get(AccountSecurity,current_user.id)
    if current_user.is_admin and current_app.config['SECURITY_ENFORCE_ADMIN_MFA']:
        if not row or not row.enabled_at:
            return deny_for_security('security.enroll','mfa_enrollment_required','Set up authenticator protection before using your administrator account.')
    if row and row.enabled_at and not mfa_verified(row):
        return deny_for_security('security.challenge','mfa_required','Verify your authenticator or a recovery code to continue.')
    sensitive = request.method in {'POST','PUT','PATCH','DELETE'} and (
        request.endpoint=='wallet_withdraw' or current_user.is_admin or request.endpoint=='organizers.settlement')
    if sensitive and current_app.config['SECURITY_REQUIRE_STEP_UP']:
        if not fresh_primary() or row and row.enabled_at and not mfa_verified(row,FRESH_SECONDS):
            return deny_for_security('security.reauthenticate','reauthentication_required','Confirm your sign-in again before this sensitive action. No action was submitted.')


def audit_response(response):
    endpoint = request.endpoint or 'unmatched'
    if endpoint not in {'static','health','service_worker'}:
        metric('traffic',current_app.config['SECURITY_TRAFFIC_THRESHOLD'])
        if response.status_code >= 500: metric('server_errors',5)
    events = list(getattr(g,'security_events',[]))
    actor = getattr(g,'security_actor_id',None) or (current_user.id if current_user.is_authenticated else None)
    if actor and request.method in {'POST','PUT','PATCH','DELETE'}:
        if getattr(g,'security_actor_admin',False) and not endpoint.startswith('security.'):
            events.append('admin.action')
        elif endpoint in {'wallet_withdraw','pay_tournament_gp','initialize_payment','wallet_initialize_deposit','organizers.settlement'}:
            events.append('finance.action')
    if response.status_code in (401,403,429) and actor: events.append('access.rejected')
    if response.status_code >= 400 and endpoint in {'wallet_withdraw','initialize_payment','pay_tournament_gp'}:
        metric('payment_failures',5)
    for event in set(events):
        if not re.fullmatch(r'[a-z_.]{1,64}',event): continue
        request_id = getattr(g,'request_id','')[:64]
        current_app.logger.info('security_event event=%s actor_id=%s endpoint=%s method=%s status=%s request_id=%s',event,actor,endpoint,request.method,response.status_code,request_id)
        # Anonymous floods stay in bounded counters/logs rather than filling the DB.
        if actor:
            try:
                with db.engine.begin() as connection:
                    connection.execute(SecurityAuditEvent.__table__.insert().values(actor_id=actor,event=event,
                        endpoint=endpoint[:120],method=request.method[:8],status=response.status_code,request_id=request_id))
            except Exception:
                current_app.logger.warning('security_alert kind=audit_storage_failure')
    return response


@security.route('/security')
@login_required
def overview():
    row = db.session.get(AccountSecurity,current_user.id)
    return render_template('account_security.html',row=row,mode='overview')


@security.route('/security/enroll',methods=['GET','POST'])
@login_required
def enroll():
    if not fresh_primary(): return redirect(url_for('.reauthenticate',next=url_for('.enroll')))
    row = locked_security(create=True)
    if row.enabled_at: return redirect(url_for('.overview'))
    if not row.pending_secret or not row.pending_at or row.pending_at < datetime.utcnow()-timedelta(minutes=10):
        secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
        row.pending_secret = cipher().encrypt(secret.encode()).decode()
        row.pending_at = datetime.utcnow()
        db.session.commit()
    secret = decrypt_factor(row.pending_secret)
    if request.method=='POST':
        limited(); row = locked_security()
        if not row.pending_secret or not row.pending_at or row.pending_at < datetime.utcnow()-timedelta(minutes=10):
            db.session.rollback();return redirect(url_for('.enroll'))
        secret = decrypt_factor(row.pending_secret)
        counter = matching_counter(secret,request.form.get('code','').strip())
        if counter is None:
            db.session.rollback();note('mfa.failure');metric('mfa_failures',3)
            flash('That authenticator code is invalid or expired.','error')
        else:
            codes = [secrets.token_hex(16) for _ in range(10)]
            row.totp_secret = row.pending_secret; row.pending_secret=None;row.pending_at=None
            row.enabled_at=datetime.utcnow();row.last_counter=counter;row.version+=1
            row.recovery_hashes=[recovery_hash(code) for code in codes]
            db.session.commit();mark_mfa(row);note('mfa.enabled')
            return render_template('account_security.html',row=row,mode='recovery',codes=codes)
    note('mfa.enrollment_viewed')
    # No external QR generator receives this secret; only the signed-in owner sees it.
    return render_template('account_security.html',row=row,mode='enroll',secret=secret)


@security.route('/security/challenge',methods=['GET','POST'])
@login_required
def challenge():
    row = db.session.get(AccountSecurity,current_user.id)
    if not row or not row.enabled_at: return redirect(url_for('.enroll'))
    if request.method=='POST':
        limited();row=locked_security()
        if consume_factor(row,request.form.get('code','')):
            db.session.commit();mark_mfa(row);note('mfa.verified')
            return redirect(safe_next())
        db.session.rollback();note('mfa.failure');metric('mfa_failures',3)
        flash('That authenticator or recovery code is invalid, expired or already used.','error')
    return render_template('account_security.html',row=row,mode='challenge')


@security.route('/security/reauthenticate',methods=['GET','POST'])
@login_required
def reauthenticate():
    row = db.session.get(AccountSecurity,current_user.id)
    if request.method=='POST':
        limited()
        from gamearena.services import auth as managed_auth
        valid = False
        password = request.form.get('password','')
        if len(password) <= 1024:
            if managed_auth.enabled():
                try:
                    identity=managed_auth.signin(current_user.email,password)
                    try:
                        account=identity.get('user') or identity
                        valid=bool(account.get('id') and account['id']==current_user.supabase_auth_id)
                    finally: managed_auth.close_session(identity)
                except managed_auth.AuthError: pass
            else:
                valid = current_user.check_password(password)
        if valid:
            row = locked_security()
            if row and row.enabled_at and not consume_factor(row,request.form.get('code','')): valid=False
        if valid:
            db.session.commit()
            session['security_primary_at']=time.time();session['security_primary_uid']=current_user.id
            if row and row.enabled_at: mark_mfa(row)
            note('auth.reauthenticated')
            return redirect(safe_next())
        db.session.rollback();note('auth.reauthentication_failed');metric('authentication_failures',5)
        flash('Sign-in confirmation failed. Check your password and authenticator code.','error')
    return render_template('account_security.html',row=row,mode='reauthenticate')


@security.route('/security/sign-in-again',methods=['POST'])
@login_required
def sign_in_again():
    target=safe_next();logout_user();session.clear()
    return redirect(url_for('login',next=target))


@security.route('/security/recovery-codes',methods=['POST'])
@login_required
def recovery_codes():
    row=db.session.get(AccountSecurity,current_user.id)
    if not fresh_primary() or not mfa_verified(row,FRESH_SECONDS):
        return redirect(url_for('.reauthenticate',next=url_for('.overview')))
    limited();row=locked_security()
    codes=[secrets.token_hex(16) for _ in range(10)]
    row.recovery_hashes=[recovery_hash(code) for code in codes]
    row.version+=1;db.session.commit();mark_mfa(row);note('mfa.recovery_regenerated')
    return render_template('account_security.html',row=row,mode='recovery',codes=codes)


@security.route('/admin/security-events')
@login_required
def events():
    if not current_user.is_admin or current_user.suspended: abort(403)
    page=SecurityAuditEvent.query.order_by(SecurityAuditEvent.id.desc()).paginate(
        page=max(1,request.args.get('page',1,type=int) or 1),per_page=50,error_out=False)
    return render_template('security_events.html',pagination=page)


def init_security(app):
    def enabled(name,default):
        value=os.environ.get(name)
        return default if value is None else value.lower() in ('1','true','yes')
    app.config.update(
        SECURITY_ENFORCE_ADMIN_MFA=enabled('SECURITY_ENFORCE_ADMIN_MFA',not app.testing),
        SECURITY_REQUIRE_STEP_UP=enabled('SECURITY_REQUIRE_STEP_UP',not app.testing),
        SECURITY_ENCRYPTION_KEY=os.environ.get('SECURITY_ENCRYPTION_KEY',''),
        ORIGIN_PROTECTION_ENABLED=enabled('ORIGIN_PROTECTION_ENABLED',False),
        ORIGIN_SHARED_SECRET=os.environ.get('ORIGIN_SHARED_SECRET',''),
        WITHDRAWALS_ENABLED=enabled('WITHDRAWALS_ENABLED',True),
        SECURITY_ALERT_EMAIL=os.environ.get('SECURITY_ALERT_EMAIL','').strip(),
        SECURITY_TRAFFIC_THRESHOLD=max(10,int(os.environ.get('SECURITY_TRAFFIC_THRESHOLD','300'))))
    if app.config['ORIGIN_PROTECTION_ENABLED'] and len(app.config['ORIGIN_SHARED_SECRET'])<32:
        raise RuntimeError('Configure a private origin secret of at least 32 characters before enabling origin protection.')
    if app.config['SECURITY_ENCRYPTION_KEY']: Fernet(app.config['SECURITY_ENCRYPTION_KEY'])
    if app.config['SECURITY_ALERT_EMAIL'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',app.config['SECURITY_ALERT_EMAIL']):
        raise RuntimeError('SECURITY_ALERT_EMAIL must be one valid owner-controlled address.')
    public=urlparse(app.config['PUBLIC_BASE_URL']).hostname
    hosts=[h for h in (public,os.environ.get('RENDER_EXTERNAL_HOSTNAME'),'localhost','127.0.0.1') if h]
    hosts.extend(h.strip() for h in os.environ.get('GAMEARENA_ALLOWED_HOSTS','').split(',') if h.strip())
    app.config['TRUSTED_HOSTS']=hosts
    app.wsgi_app=OriginGate(app,app.wsgi_app)
    app.register_blueprint(security)
    app.before_request(origin_guard)
    hooks=app.before_request_funcs[None];hooks.insert(0,hooks.pop())
    app.before_request(account_guard)
    app.after_request(audit_response)
    app.context_processor(lambda:dict(csp_nonce=getattr(g,'csp_nonce','')))
    user_logged_in.connect(primary_login,sender=app,weak=False)
    user_logged_out.connect(primary_logout,sender=app,weak=False)
