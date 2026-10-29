"""Optional email-code second step. No authenticated login before code verification."""
from datetime import datetime,timedelta
import hashlib,hmac,re,secrets,time
from flask import Blueprint,abort,current_app,flash,redirect,render_template,request,session,url_for,jsonify
from flask_login import current_user,login_required,login_user,logout_user
from gamearena.extensions import db
from gamearena.models import User,AccountSecurity,EmailLoginChallenge

email_security=Blueprint('email_security',__name__)
TTL=300

def security_row(user_id,create=False):
    user=User.query.filter_by(id=user_id).with_for_update().populate_existing().one()
    row=AccountSecurity.query.filter_by(user_id=user_id).with_for_update().populate_existing().first()
    if not row and create:
        row=AccountSecurity(user_id=user_id);db.session.add(row);db.session.flush()
    return user,row

def digest(challenge_id,code):
    return hmac.new(current_app.secret_key.encode(),('email-step-v1:'+challenge_id+':'+code).encode(),hashlib.sha256).hexdigest()

def marked(user,row):
    session['email_step_uid']=user.id;session['email_step_version']=row.email_version

def verified_session(user):
    row=db.session.get(AccountSecurity,user.id)
    return not row or not row.email_enabled_at or (session.get('email_step_uid')==user.id and session.get('email_step_version')==row.email_version)

def issue(user_id,purpose):
    from app import consume_rate_limit,send_email
    if consume_rate_limit('email_step_send:'+purpose+':'+str(user_id),1,60) is not None or consume_rate_limit('email_step_hour:'+str(user_id),6,3600) is not None:
        return 'Wait before requesting another code.'
    user,row=security_row(user_id,create=True)
    if user.suspended or not user.email_verified:abort(403)
    if purpose=='login' and not row.email_enabled_at:abort(409)
    previous=session.get('email_challenge')
    if previous:
        old=EmailLoginChallenge.query.filter_by(id=previous,user_id=user.id).with_for_update().first()
        if old:old.used_at=datetime.utcnow()
    identifier=secrets.token_hex(24);code=''.join(secrets.choice('0123456789') for _ in range(8))
    entry=EmailLoginChallenge(id=identifier,user_id=user.id,purpose=purpose,code_hash=digest(identifier,code),
        expires_at=datetime.utcnow()+timedelta(seconds=TTL),factor_version=row.email_version or 0,auth_version=user.auth_session_version or 0)
    db.session.add(entry);db.session.commit()
    if not send_email('GameArena verification code',user.email,
        'Your GameArena '+('sign-in' if purpose=='login' else 'security settings')+' code is '+code+'. It expires in five minutes. Do not share it. If you did not request this, ignore this email.'):
        entry.used_at=datetime.utcnow();db.session.commit()
        return 'We could not send the code. No security setting was changed. Try again later.'
    session['email_challenge']=identifier
    return None

def finish_signin(user,target,provider=None):
    row=db.session.get(AccountSecurity,user.id)
    if row and row.email_enabled_at:
        session.pop('_user_id',None);session.pop('_fresh',None)
        session['email_primary_at']=time.time();session['email_target']=target;session['email_provider']=provider
        error=issue(user.id,'login')
        if error:flash(error,'error');return redirect(url_for('login'))
        return redirect(url_for('email_security.challenge'))
    session['auth_session_version']=user.auth_session_version
    if provider:session['auth_provider']=provider
    login_user(user)
    return redirect(target)

@email_security.route('/account/two-step',methods=['GET','POST'])
@login_required
def overview():
    from gamearena.account_security import fresh_primary
    row=db.session.get(AccountSecurity,current_user.id)
    if request.method=='POST':
        if not fresh_primary():return redirect(url_for('security.reauthenticate',next=url_for('.overview')))
        if not current_user.email_verified:abort(403)
        action=request.form.get('action')
        if action not in {'enable','disable'}:abort(400)
        if (action=='disable') != bool(row and row.email_enabled_at):abort(409)
        error=issue(current_user.id,action)
        if error:flash(error,'error')
        else:return redirect(url_for('.challenge'))
    return render_template('email_two_step.html',row=row,mode='overview')

@email_security.route('/account/two-step/challenge',methods=['GET','POST'])
def challenge():
    first=db.session.get(EmailLoginChallenge,session.get('email_challenge',''))
    if not first:return redirect(url_for('login'))
    purpose=first.purpose
    if purpose!='login' and (not current_user.is_authenticated or current_user.id!=first.user_id or not verified_session(current_user)):abort(403)
    if purpose=='login' and not 0<=time.time()-session.get('email_primary_at',0)<=600:
        session.pop('email_challenge',None);flash('Sign-in expired. Sign in again.','error');return redirect(url_for('login'))
    if request.method=='POST' and request.form.get('action')=='resend':
        owner=db.session.get(User,first.user_id)
        row=db.session.get(AccountSecurity,first.user_id)
        if owner.suspended or owner.auth_session_version!=first.auth_version or row.email_version!=first.factor_version:abort(403)
        error=issue(first.user_id,purpose)
        flash(error or 'A new code was sent. The previous code no longer works.','error' if error else 'success')
        return redirect(url_for('.challenge'))
    if request.method=='POST':
        from app import consume_rate_limit
        if consume_rate_limit('email_step_attempt:'+str(first.user_id),5,300) is not None:abort(429)
        user,row=security_row(first.user_id)
        entry=EmailLoginChallenge.query.filter_by(id=first.id).with_for_update().populate_existing().one()
        code=request.form.get('code','').strip()
        valid=bool(not user.suspended and user.email_verified and row and entry.used_at is None and entry.expires_at>datetime.utcnow()
            and entry.attempts<5 and user.auth_session_version==entry.auth_version and row.email_version==entry.factor_version)
        if not valid or not re.fullmatch(r'[0-9]{8}',code) or not hmac.compare_digest(entry.code_hash,digest(entry.id,code)):
            entry.attempts+=1
            if entry.attempts>=5:entry.used_at=datetime.utcnow()
            db.session.commit();flash('That code is invalid, expired or already used.','error')
        else:
            entry.used_at=datetime.utcnow()
            if purpose in {'enable','disable'}:
                row.email_enabled_at=datetime.utcnow() if purpose=='enable' else None
                row.email_version=(row.email_version or 0)+1
                user.auth_session_version=(user.auth_session_version or 0)+1
            db.session.commit()
            target=session.pop('email_target',None) or url_for('settings',section='privacy')
            if not target.startswith('/') or target.startswith('//') or '\\' in target or any(ord(c)<32 for c in target):target=url_for('dashboard')
            provider=session.get('email_provider')
            session.pop('email_challenge',None)
            if purpose=='login':
                session.clear();session['auth_session_version']=user.auth_session_version
                if provider:session['auth_provider']=provider
                login_user(user)
            else:session['auth_session_version']=user.auth_session_version
            marked(user,row)
            from gamearena.account_security import note
            note('auth.email_step_'+purpose)
            if purpose!='login':flash('Email two-step verification updated.','success')
            return redirect(target if purpose=='login' else url_for('settings',section='privacy'))
    email=db.session.get(User,first.user_id).email
    local,domain=email.rsplit('@',1)
    return render_template('email_two_step.html',row=None,mode='challenge',purpose=purpose,masked_email=local[:1]+'***@'+domain)

def guard():
    endpoint=request.endpoint or ''
    if endpoint in {'static','health','service_worker','android_asset_links','logout'} or endpoint.startswith('legal.'):return
    if current_user.is_authenticated and not verified_session(current_user):
        logout_user();session.clear()
        if request.is_json:return jsonify(error='Sign in again to verify your email code.'),401
        flash('Sign in again to verify your email code.','error');return redirect(url_for('login'))

def init_email_security(app):
    app.register_blueprint(email_security);app.before_request(guard)
