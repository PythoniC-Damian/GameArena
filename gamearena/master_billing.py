"""Paystack monthly Master billing. No live plan is created by the application."""
import os
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import quote, urlparse
import requests
from flask import Blueprint, current_app, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from gamearena.extensions import db
from gamearena.models import User, MasterSubscription, MasterPayment, Notification

billing = Blueprint('master_billing', __name__)
PRICE_KOBO = 230000
REFERENCE = re.compile(r'^[A-Za-z0-9._-]{1,100}$')

class BillingError(Exception): pass

def configured():
    return os.environ.get('MASTER_BILLING_ENABLED') == '1' and bool(os.environ.get('PAYSTACK_SECRET_KEY')) and bool(os.environ.get('PAYSTACK_MASTER_PLAN_CODE'))

def provider(method, path, **kwargs):
    secret = os.environ.get('PAYSTACK_SECRET_KEY', '')
    if not secret: raise BillingError('Membership payments are not configured yet.')
    try:
        result = requests.request(method, 'https://api.paystack.co'+path, headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'}, timeout=(5,15), **kwargs)
        payload=result.json()
    except (requests.RequestException, ValueError):
        raise BillingError('Paystack could not be reached. Please try again.') from None
    if not result.ok or not isinstance(payload,dict) or not payload.get('status'):
        raise BillingError('Paystack could not complete this request. Please try again.')
    return payload.get('data') or {}

def timestamp(value):
    if not isinstance(value,str):raise BillingError('Invalid payment date.')
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:raise BillingError('Invalid payment date.') from None

def monthly_end(paid):
    # Paystack moves billing days 29-31 to the 28th of subsequent months.
    month=paid.month%12+1;year=paid.year+(paid.month==12)
    return paid.replace(year=year,month=month,day=min(paid.day,28))

def checkout_origin():
    origin=os.environ.get('PUBLIC_BASE_URL','').rstrip('/')
    parsed=urlparse(origin)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
        raise BillingError('The public site URL must be configured before checkout.')
    if parsed.scheme!='https' and parsed.hostname not in {'localhost','127.0.0.1'}:
        raise BillingError('Checkout requires a secure public site URL.')
    return origin

def safe_checkout(url):
    parsed=urlparse(url if isinstance(url,str) else '')
    return bool(parsed.scheme=='https' and parsed.hostname=='checkout.paystack.com' and not parsed.username and not parsed.password)

def valid_charge(transaction, subscription, reference):
    customer=transaction.get('customer') or {}
    plan=transaction.get('plan_object') or transaction.get('plan') or {}
    if isinstance(plan,str):plan={'plan_code':plan}
    return (transaction.get('status')=='success' and transaction.get('reference')==reference and type(transaction.get('amount')) is int and transaction['amount']==PRICE_KOBO and transaction.get('currency')=='NGN' and isinstance(customer,dict) and str(customer.get('email','')).casefold()==subscription.billing_email.casefold() and (not subscription.customer_code or customer.get('customer_code')==subscription.customer_code) and isinstance(plan,dict) and plan.get('plan_code')==subscription.plan_code)

def apply_charge(reference, transaction, subscription_id=None, period_end=None):
    if not isinstance(reference,str) or not REFERENCE.fullmatch(reference):raise BillingError('Invalid payment reference.')
    existing=db.session.get(MasterPayment,reference)
    if subscription_id is None:
        if not existing:return False
        subscription_id=existing.subscription_id
    subscription=db.session.get(MasterSubscription,subscription_id)
    if not subscription:raise BillingError('Subscription not found.')
    user=User.query.filter_by(id=subscription.user_id).with_for_update().first()
    db.session.refresh(subscription)
    existing=MasterPayment.query.filter_by(reference=reference).with_for_update().first()
    if existing and existing.subscription_id!=subscription.id:raise BillingError('Payment record mismatch.')
    if not valid_charge(transaction,subscription,reference):raise BillingError('Payment details did not match this membership.')
    if existing and existing.status=='success':return True
    paid=timestamp(transaction.get('paid_at') or transaction.get('paidAt'))
    end=timestamp(period_end) if period_end else monthly_end(paid)
    if end<=paid or (end-paid).days>32:raise BillingError('Invalid billing period.')
    if not existing:
        existing=MasterPayment(reference=reference,subscription_id=subscription.id)
        db.session.add(existing)
    existing.status='success';existing.paid_at=paid;existing.period_end=end
    subscription.customer_code=transaction['customer'].get('customer_code')
    if subscription.status=='pending':subscription.status='active'
    user.master_expires_at=max(user.master_expires_at or end,end)
    db.session.add(Notification(user_id=user.id,category='system',message='Master payment confirmed. Your membership benefits are active.',target_url='/pro'))
    db.session.commit()
    return True

@billing.route('/pro/checkout',methods=['POST'])
@login_required
def checkout():
    if current_user.suspended or not current_user.email_verified:return jsonify(error='Verify your email before subscribing.'),403
    if request.form.get('renewal_consent')!='yes':
        flash('Confirm the monthly renewal terms before subscribing.','error');return redirect(url_for('pro.membership'))
    if not configured():
        flash('Membership checkout is not configured yet. No payment was taken.','error');return redirect(url_for('pro.membership'))
    try:
        plan_code=os.environ['PAYSTACK_MASTER_PLAN_CODE']
        plan=provider('GET','/plan/'+quote(plan_code,safe=''))
        if plan.get('plan_code')!=plan_code or plan.get('amount')!=PRICE_KOBO or plan.get('currency')!='NGN' or plan.get('interval')!='monthly':raise BillingError('The membership plan must be NGN 2,300 per month.')
        User.query.filter_by(id=current_user.id).with_for_update().first()
        subscription=MasterSubscription.query.filter_by(user_id=current_user.id).filter(MasterSubscription.status.in_(['pending','active','attention','non-renewing'])).order_by(MasterSubscription.id.desc()).first()
        if subscription:
            payment=MasterPayment.query.filter_by(subscription_id=subscription.id,status='pending').first()
            if payment and payment.checkout_url:
                destination=payment.checkout_url;db.session.commit();return redirect(destination)
            if subscription.status!='pending':raise BillingError('You already have a subscription. Manage it below instead of subscribing twice.')
        else:
            subscription=MasterSubscription(user_id=current_user.id,plan_code=plan_code,billing_email=current_user.email,status='pending')
            db.session.add(subscription);db.session.flush()
        payment=MasterPayment.query.filter_by(subscription_id=subscription.id,status='pending').first()
        if not payment:
            payment=MasterPayment(reference='master-'+secrets.token_hex(20),subscription_id=subscription.id)
            db.session.add(payment)
        reference=payment.reference
        # Persist before the provider call so timeout/retry cannot create another reference.
        db.session.commit()
        User.query.filter_by(id=current_user.id).with_for_update().first()
        db.session.refresh(payment)
        if payment.status=='success':raise BillingError('Your membership payment is already confirmed.')
        if payment.checkout_url:
            destination=payment.checkout_url;db.session.commit();return redirect(destination)
        result=provider('POST','/transaction/initialize',json={'email':subscription.billing_email,'amount':PRICE_KOBO,'currency':'NGN','plan':plan_code,'reference':reference,'channels':['card'],'callback_url':checkout_origin()+url_for('master_billing.verify'),'metadata':{'type':'master_membership','user_id':current_user.id}})
        destination=result.get('authorization_url')
        if result.get('reference')!=reference or not safe_checkout(destination):raise BillingError('Unexpected checkout response.')
        payment.checkout_url=destination;db.session.commit()
        return redirect(destination)
    except BillingError as error:
        db.session.rollback();flash(str(error),'error');return redirect(url_for('pro.membership'))

@billing.route('/pro/verify')
@login_required
def verify():
    reference=request.args.get('reference','')
    payment=db.session.get(MasterPayment,reference) if REFERENCE.fullmatch(reference) else None
    if not payment or payment.subscription.user_id!=current_user.id:return jsonify(error='Payment not found.'),404
    try:
        transaction=provider('GET','/transaction/verify/'+quote(reference,safe=''))
        if transaction.get('status') in {'failed','abandoned'}:
            if payment.status!='success':
                payment.status='failed'
                if payment.subscription.status=='pending':payment.subscription.status='failed'
                db.session.commit()
            raise BillingError('Payment was not completed. You can start a new checkout.')
        if transaction.get('status')!='success':raise BillingError('Payment is not confirmed yet. You can check again from your membership page.')
        apply_charge(reference,transaction)
        flash('Master payment confirmed. Your benefits are active.','success')
    except BillingError as error:
        db.session.rollback();flash(str(error),'error')
    return redirect(url_for('pro.membership'))

@billing.route('/pro/cancel',methods=['POST'])
@login_required
def cancel():
    subscription=MasterSubscription.query.filter_by(user_id=current_user.id).filter(MasterSubscription.status.in_(['active','attention','non-renewing'])).order_by(MasterSubscription.id.desc()).first()
    if not subscription:return jsonify(error='No renewable membership found.'),404
    if request.form.get('confirmed')!='yes':
        flash('Confirm cancellation first.','error');return redirect(url_for('pro.membership'))
    try:
        if subscription.status!='non-renewing':
            if not subscription.subscription_code or not subscription.email_token:raise BillingError('Subscription details are still syncing. Please try again shortly.')
            provider('POST','/subscription/disable',json={'code':subscription.subscription_code,'token':subscription.email_token})
            subscription.status='non-renewing';db.session.commit()
        flash('Automatic renewal cancelled. Keep your Master benefits until your paid period ends.','success')
    except BillingError as error:
        db.session.rollback();flash(str(error),'error')
    return redirect(url_for('pro.membership'))

@billing.route('/pro/manage-payment',methods=['POST'])
@login_required
def manage_payment():
    subscription=MasterSubscription.query.filter_by(user_id=current_user.id).filter(MasterSubscription.subscription_code.isnot(None),MasterSubscription.status.in_(['active','attention','non-renewing'])).order_by(MasterSubscription.id.desc()).first()
    if not subscription:return jsonify(error='Subscription not found.'),404
    try:
        result=provider('GET','/subscription/'+quote(subscription.subscription_code,safe='')+'/manage/link')
        link=result.get('link');parsed=urlparse(link or '')
        if parsed.scheme!='https' or parsed.hostname!='paystack.com' or not parsed.path.startswith('/manage/subscriptions/') or parsed.username:raise BillingError('Unexpected subscription management link.')
        return redirect(link)
    except BillingError as error:
        flash(str(error),'error');return redirect(url_for('pro.membership'))

def handle_event(name,data):
    """Called only after the existing shared webhook verifies its HMAC signature."""
    if not isinstance(data,dict):return False
    if name=='charge.success':
        reference=data.get('reference')
        payment=db.session.get(MasterPayment,reference) if isinstance(reference,str) else None
        if not payment:return False
        apply_charge(reference,data);return True
    if name=='subscription.create':
        plan=data.get('plan') or {};customer=data.get('customer') or {}
        if not isinstance(plan,dict) or plan.get('plan_code')!=os.environ.get('PAYSTACK_MASTER_PLAN_CODE') or data.get('amount')!=PRICE_KOBO:return False
        if not isinstance(customer,dict):return False
        subscription=MasterSubscription.query.filter_by(billing_email=customer.get('email'),plan_code=plan['plan_code']).filter(MasterSubscription.status.in_(['pending','active'])).order_by(MasterSubscription.id.desc()).with_for_update().first()
        if not subscription:return False
        code=data.get('subscription_code');token=data.get('email_token')
        if not isinstance(code,str) or not code.startswith('SUB_') or not isinstance(token,str) or len(code)>80 or len(token)>150:raise BillingError('Invalid subscription details.')
        if subscription.subscription_code and subscription.subscription_code!=code:raise BillingError('Duplicate subscription detected.')
        subscription.subscription_code=code;subscription.email_token=token;subscription.customer_code=customer.get('customer_code');subscription.next_payment_at=timestamp(data['next_payment_date']) if data.get('next_payment_date') else None
        db.session.commit();return True
    nested=data.get('subscription') or data
    code=nested.get('subscription_code') if isinstance(nested,dict) else None
    subscription=MasterSubscription.query.filter_by(subscription_code=code).first() if code else None
    if not subscription:return False
    if name=='invoice.update' and data.get('paid') is True and data.get('status')=='success':
        transaction=data.get('transaction') or {};reference=transaction.get('reference') if isinstance(transaction,dict) else None
        if not reference:raise BillingError('Missing recurring payment reference.')
        verified=provider('GET','/transaction/verify/'+quote(reference,safe=''))
        apply_charge(reference,verified,subscription.id,data.get('period_end'));return True
    if name in {'subscription.not_renew','subscription.disable','invoice.payment_failed'}:
        if name=='subscription.not_renew':subscription.status='non-renewing'
        elif name=='subscription.disable':subscription.status='cancelled'
        elif subscription.status not in {'non-renewing','cancelled'}:subscription.status='attention'
        db.session.commit();return True
    return False
