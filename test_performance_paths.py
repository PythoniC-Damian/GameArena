"""Protect cheap public delivery and private cache boundaries."""
from sqlalchemy import event
from app import app, db
from test_interface_contracts import player, client


def test_signed_in_static_assets_do_not_query_database():
    with app.app_context():
        browser=client(player('asset_reader'))
        statements=[]
        def collect(*args): statements.append(args[2])
        event.listen(db.engine,'before_cursor_execute',collect)
        try:
            response=browser.get('/static/css/site.css')
            assert response.status_code==200
            assert not statements
            assert 'public' in response.headers['Cache-Control']
        finally:
            event.remove(db.engine,'before_cursor_execute',collect)


def test_wallet_stays_private_and_worker_revalidates():
    with app.app_context():
        browser=client(player('private_wallet_cache'))
        assert 'no-store' in browser.get('/wallet').headers['Cache-Control']
        assert 'no-cache' in browser.get('/sw.js').headers['Cache-Control']
