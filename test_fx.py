"""Live-rate boundary validation, hourly caching and signed indicative match quotes."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import time
import pytest
from app import app,db
import gamearena.fx as module
from gamearena.models import UserSettings
from test_interface_contracts import player,client,token

@pytest.fixture(autouse=True)
def reset_fx(monkeypatch):
    monkeypatch.setattr(module,'_cache',None)
    monkeypatch.setattr(module,'_retry_after',0)
    monkeypatch.setitem(app.config,'CACHE_REDIS_URL',None)


def feed(now=None):
    rates={code:2 for code in list(module.CURRENCIES)[:140]}
    rates.update(USD=1,NGN=1600,GBP=0.75,EUR=0.9)
    return {'base':'USD','timestamp':int(now or time.time()),'rates':rates}


def test_normalized_feed_and_quote_keep_gp_value():
    snap=module.validate_feed(feed(),time.time());snap['stale']=False
    assert snap['rates']['NGN']=='1' and snap['rates']['USD']=='0.000625'
    quote=module.quote_amount('5','USD',snap)
    assert quote['amount_gp']==8000 and quote['settlement_currency']=='GP'
    assert module.quote_amount('5.001','USD',snap)['amount_gp']==8002
    assert len(snap['rates'])>=130 and 'BTC' not in snap['rates']


@pytest.mark.parametrize('change',[
    {'base':'EUR'},{'timestamp':0},{'timestamp':float('inf')},{'timestamp':True},
    {'timestamp':time.time()+10000},{'rates':{'USD':1,'NGN':0}}, {'rates':[]},
])
def test_bad_or_outdated_feed_is_rejected(change):
    payload=feed();payload.update(change)
    with pytest.raises(module.RatesUnavailable):module.validate_feed(payload,time.time())


def test_cache_fetches_once_per_hour_and_coalesces_threads(monkeypatch):
    clock=[time.time()]
    monkeypatch.setattr(module.time,'time',lambda:clock[0])
    response=Mock();response.json.side_effect=lambda:feed(clock[0]);get=Mock(return_value=response)
    monkeypatch.setattr(module.requests,'get',get)
    def read(_):
        with app.app_context():return module.rate_snapshot()
    with ThreadPoolExecutor(max_workers=6) as pool: snapshots=list(pool.map(read,range(6)))
    assert get.call_count==1 and all(not snap['stale'] for snap in snapshots)
    clock[0]+=3599;read(0);assert get.call_count==1
    clock[0]+=2;read(0);assert get.call_count==2


def test_stale_fallback_never_issues_match_quote(monkeypatch):
    now=time.time();response=Mock();response.json.return_value=feed(now)
    monkeypatch.setattr(module.requests,'get',Mock(return_value=response))
    with app.app_context():module.rate_snapshot()
    monkeypatch.setattr(module.time,'time',lambda:now+3700)
    failed=Mock(side_effect=module.requests.Timeout());monkeypatch.setattr(module.requests,'get',failed)
    with app.app_context():
        stale=module.rate_snapshot();assert stale['stale']
        assert module.rate_snapshot()['stale'] and failed.call_count==3
        with pytest.raises(module.RatesUnavailable):module.quote_amount('5','USD',stale)


@pytest.mark.parametrize('amount',['NaN','Infinity','-1','0','1e9999','0.00001','text'])
def test_invalid_quote_amounts(amount):
    with pytest.raises(ValueError):module.quote_amount(amount,'GP')


def test_currency_preference_and_quotes_are_owner_bound_and_csrf_protected(monkeypatch):
    with app.app_context():
        owner=player('fx_owner');owner.wallet_balance=1000;db.session.commit()
        browser=client(owner);csrf=token(browser.get('/wallet'));headers={'X-CSRFToken':csrf}
        assert browser.post('/wallet/display-currency',json={'currency':'USD'}).status_code==400
        assert browser.post('/wallet/display-currency',json={'currency':'USD'},headers=headers).json=={'currency':'USD'}
        assert UserSettings.query.filter_by(user_id=owner.id).one().display_currency=='USD'
        db.session.refresh(owner);assert owner.wallet_balance==1000
        assert browser.post('/wallet/display-currency',json={'currency':['USD']},headers=headers).status_code==400
        snap=module.validate_feed(feed(),time.time());snap['stale']=False
        monkeypatch.setattr(module,'rate_snapshot',lambda:snap)
        assert browser.get('/api/exchange-rates').json['base']=='NGN'
        quote=browser.post('/api/match-value-quote',json={'amount':'5','currency':'USD'},headers=headers)
        assert quote.status_code==200 and quote.json['amount_gp']==8000
        verified=module.verify_match_quote(quote.json['quote_token'],owner.id)
        assert verified['amount_gp']==8000
        with pytest.raises(ValueError):module.verify_match_quote(quote.json['quote_token'],owner.id+1)
        with pytest.raises(ValueError):module.verify_match_quote(quote.json['quote_token']+'x',owner.id)
        db.session.refresh(owner);assert owner.wallet_balance==1000


def test_daily_fallback_is_labelled_and_uses_its_original_date(monkeypatch):
    from datetime import datetime,timezone
    now=time.time()
    daily=feed(now)
    payload={'date':datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m-%d'),'usd':{k.lower():v for k,v in daily['rates'].items()}}
    response=Mock();response.json.return_value=payload
    denied=module.requests.HTTPError();denied.response=Mock(status_code=403)
    get=Mock(side_effect=[denied,response]);monkeypatch.setattr(module.requests,'get',get)
    with app.app_context():
        snap=module.rate_snapshot()
        assert snap['cadence']=='daily' and snap['degraded'] and not snap['stale']
        assert snap['source']=='Currency API' and snap['source_updated_at']<=now
        assert module.quote_amount('5','USD',snap)['amount_gp']==8000
        assert module.rate_snapshot()['cadence']=='daily' and get.call_count==2


def test_expired_daily_fallback_is_rejected():
    with pytest.raises(module.RatesUnavailable):module.validate_feed(feed(time.time()-172801),time.time(),max_age=172800)
