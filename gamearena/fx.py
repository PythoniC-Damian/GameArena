"""Hourly cached indicative FX. Exchange rates never change GP ledger balances."""
import json
import math
import threading
import time
from decimal import Decimal, ROUND_CEILING, InvalidOperation
from pathlib import Path
import requests
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from gamearena.extensions import db
from gamearena.models import User, UserSettings

fx=Blueprint('fx',__name__)
CURRENCIES=json.loads((Path(__file__).parent/'currencies.json').read_text(encoding='utf-8'))['currencies']
SOURCE='https://api.exchangerate.fun/latest?base=USD'
TTL=3600
MAX_SOURCE_AGE=7200
_cache=None
_retry_after=0
_lock=threading.Lock()

class RatesUnavailable(ValueError): pass

def validate_feed(payload, now):
    if not isinstance(payload,dict) or payload.get('base')!='USD':
        raise RatesUnavailable('Invalid exchange-rate response.')
    stamp=payload.get('timestamp')
    if isinstance(stamp,bool) or not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or stamp>now+300 or now-stamp>MAX_SOURCE_AGE:
        raise RatesUnavailable('The exchange-rate source is not current.')
    raw_rates=payload.get('rates')
    if not isinstance(raw_rates,dict):raise RatesUnavailable('Invalid exchange-rate response.')
    rates={}
    for code,raw in raw_rates.items():
        if code not in CURRENCIES: continue
        try: value=Decimal(str(raw))
        except InvalidOperation: continue
        if value.is_finite() and 0<value<Decimal('1e15'): rates[code]=value
    if not {'NGN','USD','GBP'}.issubset(rates) or rates['USD']!=1 or len(rates)<130:
        raise RatesUnavailable('Incomplete exchange-rate data.')
    normalized={code:str(value/rates['NGN']) for code,value in rates.items()}
    normalized['NGN']='1'
    return dict(base='NGN',rates=normalized,source='ExchangeRate.fun',source_url='https://www.exchangerate.fun/',
        source_updated_at=int(stamp),fetched_at=int(now),refresh_after=int(now+TTL),
        currencies={code:CURRENCIES[code] for code in sorted(normalized)})

def rate_snapshot():
    global _cache,_retry_after
    now=time.time()
    if _cache and now<_cache['refresh_after']:
        return dict(_cache,stale=now-_cache['source_updated_at']>MAX_SOURCE_AGE)
    with _lock:
        now=time.time()
        if _cache and now<_cache['refresh_after']:
            return dict(_cache,stale=now-_cache['source_updated_at']>MAX_SOURCE_AGE)
        redis=None
        url=current_app.config.get('CACHE_REDIS_URL')
        if url:
            from gamearena.services.redis_support import redis_connection
            try:
                redis=redis_connection(url)
                key=current_app.config.get('CACHE_NAMESPACE','gamearena')+':fx:v1'
                cached=redis.get(key)
                if cached:
                    candidate=json.loads(cached)
                    if candidate.get('base')=='NGN' and candidate.get('rates'):
                        _cache=candidate
                        if now<candidate['refresh_after']:
                            return dict(candidate,stale=now-candidate['source_updated_at']>MAX_SOURCE_AGE)
            except Exception:
                redis=None
                current_app.logger.warning('FX shared cache unavailable; using process cache.')
        if now<_retry_after:
            if _cache and now-_cache['fetched_at']<86400:return dict(_cache,stale=True)
            raise RatesUnavailable('Exchange rates are temporarily unavailable.')
        try:
            response=requests.get(SOURCE,timeout=(3.05,8))
            response.raise_for_status()
            _cache=validate_feed(response.json(),now)
            if redis:
                try:redis.setex(key,86400,json.dumps(_cache))
                except Exception:current_app.logger.warning('FX shared cache write unavailable.')
            return dict(_cache,stale=False)
        except (requests.RequestException,ValueError,TypeError,AttributeError):
            _retry_after=now+60
            if _cache and now-_cache['fetched_at']<86400:return dict(_cache,stale=True)
            raise RatesUnavailable('Exchange rates are temporarily unavailable.') from None

def quote_amount(amount, currency, snapshot=None):
    try: value=Decimal(str(amount))
    except InvalidOperation: raise ValueError('Enter a valid amount.') from None
    if not value.is_finite() or value<=0 or value>Decimal('1000000000') or value.as_tuple().exponent < -4:
        raise ValueError('Enter a positive amount with at most four decimal places.')
    if currency in {'GP','NGN'}:
        equivalent=value;stamp=None;rate=Decimal(1)
    else:
        snapshot=snapshot or rate_snapshot()
        if snapshot['stale'] or time.time()-snapshot['source_updated_at']>MAX_SOURCE_AGE:
            raise RatesUnavailable('Fresh rates are required to quote a match value.')
        if currency not in snapshot['rates']:raise ValueError('Unsupported currency.')
        rate=Decimal(snapshot['rates'][currency]);equivalent=value/rate;stamp=snapshot['source_updated_at']
    gp=int(equivalent.to_integral_value(rounding=ROUND_CEILING))
    if gp>2_000_000_000:raise ValueError('Amount is too large.')
    return dict(currency=currency,requested_amount=str(value),amount_gp=gp,rate_per_gp=str(rate),source_updated_at=stamp,
        rounding='up_to_whole_gp',settlement_currency='GP')

def quote_signer():
    return URLSafeTimedSerializer(current_app.secret_key,salt='match-value-v1')

def verify_match_quote(token,user_id):
    try: payload=quote_signer().loads(token,max_age=300)
    except (BadSignature,SignatureExpired):raise ValueError('Match quote expired or invalid.') from None
    if payload.get('user_id')!=user_id or payload.get('expires_at',0)<time.time():
        raise ValueError('Match quote expired or invalid.')
    return payload

@fx.route('/api/exchange-rates')
@login_required
def rates():
    try:return jsonify(rate_snapshot())
    except RatesUnavailable as error:return jsonify(error=str(error)),503

@fx.route('/wallet/display-currency',methods=['POST'])
@login_required
def preference():
    data=request.get_json(silent=True) or {}
    code=data.get('currency') if isinstance(data,dict) else None
    if not isinstance(code,str) or (code not in {'GP','NGN'} and code not in CURRENCIES):
        return jsonify(error='Unsupported currency.'),400
    db.session.execute(db.select(User).where(User.id==current_user.id).with_for_update())
    row=UserSettings.query.filter_by(user_id=current_user.id).first()
    if not row:row=UserSettings(user_id=current_user.id);db.session.add(row)
    row.display_currency=code
    db.session.commit()
    return jsonify(currency=code)

@fx.route('/api/match-value-quote',methods=['POST'])
@login_required
def quote():
    data=request.get_json(silent=True) or {}
    if not isinstance(data,dict):return jsonify(error='Invalid quote request.'),400
    code=data.get('currency')
    if not isinstance(code,str) or (code not in {'GP','NGN'} and code not in CURRENCIES):
        return jsonify(error='Unsupported currency.'),400
    try:
        result=quote_amount(data.get('amount'),code)
        result['expires_at']=int(time.time()+300)
        result['quote_token']=quote_signer().dumps(dict(result,user_id=current_user.id))
        return jsonify(result)
    except RatesUnavailable as error:return jsonify(error=str(error)),503
    except (ValueError,TypeError) as error:return jsonify(error=str(error)),400
