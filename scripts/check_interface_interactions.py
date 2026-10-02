import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent.parent
BASE='http://127.0.0.1:5057'
checks={}; errors=[]; console=[]; failures=[]
with sync_playwright() as p:
 browser=p.chromium.launch(channel='chrome',headless=True)
 context=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce')
 page=context.new_page()
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.on('console',lambda e:console.append(e.text) if e.type=='error' else None)
 page.on('response',lambda r:failures.append({'status':r.status,'url':r.url}) if r.status>=400 else None)
 page.goto(BASE+'/login');page.locator('[name=email]').fill('preview@example.com');page.locator('[name=password]').fill('Preview-Only-42!');page.locator('form[method=POST] input[type=submit]').click();page.wait_for_url('**/dashboard')
 assert page.url.endswith('/dashboard')
 page.goto(BASE+'/search');page.locator('[name=q]').fill('PUBG');page.locator('[name=q]').press('Enter');page.wait_for_url('**/search?q=PUBG')
 checks['search_enter_keeps_query']=page.locator('[name=q]').input_value()=='PUBG'
 page.get_by_role('link',name='PUBG Mobile',exact=True).click();page.wait_for_load_state('networkidle')
 checks['game_link_filters']=page.locator('select[name=game]').input_value()=='PUBG Mobile'
 page.goto(BASE+'/settings'); original=page.locator('[name=bio]').input_value();page.locator('[name=bio]').fill('Browser-verified profile bio');page.get_by_role('button',name='Save settings').click();page.wait_for_load_state('networkidle')
 page.goto(BASE+'/profile');checks['settings_persist_profile']=page.get_by_text('Browser-verified profile bio',exact=True).count()==1
 page.goto(BASE+'/settings');page.locator('[name=bio]').fill(original);page.get_by_role('button',name='Save settings').click();page.wait_for_load_state('networkidle')
 page.goto(BASE+'/notifications');read_count=page.locator('button',has_text='Mark as read').count();page.get_by_role('button',name='Mark all as read',exact=True).click();page.wait_for_load_state('networkidle')
 checks['mark_all_hides_zero_badge']=page.locator('[data-unread-badge]').is_hidden()
 unread=page.get_by_role('button',name='Mark unread',exact=True)
 if unread.count(): unread.first.click();page.wait_for_load_state('networkidle');checks['mark_unread_restores_badge']=not page.locator('[data-unread-badge]').is_hidden()
 page.goto(BASE+'/wallet');deposit=page.get_by_role('button',name='Deposit',exact=True);deposit.click()
 checks['deposit_dialog_focus']=page.locator('#depositAmount').evaluate('(el)=>el===document.activeElement')
 page.keyboard.press('Escape');checks['deposit_escape_restore']=page.locator('#addMoneyModal').is_hidden() and deposit.evaluate('(el)=>el===document.activeElement')
 page.route('**/wallet/banks',lambda route:route.fulfill(status=200,content_type='application/json',body='{"banks":[{"name":"Preview Bank","code":"058"}]}'))
 page.get_by_role('button',name='Withdraw',exact=True).click();checks['withdraw_dialog_scroll']=page.locator('#withdrawModal>div').evaluate('(el)=>el.clientHeight<=innerHeight')
 page.locator('#withdrawBank option[value="058"]').wait_for(state='attached');page.locator('#withdrawBank').select_option('058');checks['bank_selector_uses_real_code']=page.locator('#withdrawBank').input_value()=='058'
 page.keyboard.press('Escape')
 # Inspect financial error states using browser stubs; no provider/payment call.
 page.route('**/wallet/initialize-deposit',lambda route:route.fulfill(status=502,content_type='application/json',body='{"status":"error","message":"Preview checkout unavailable"}'))
 deposit.click();page.locator('#depositAmount').fill('500');page.get_by_role('button',name='Deposit Now').click();page.get_by_text('Preview checkout unavailable',exact=True).wait_for()
 checks['deposit_error_reenables_button']=page.get_by_role('button',name='Deposit Now').is_enabled();page.keyboard.press('Escape');page.unroute('**/wallet/initialize-deposit')
 page.goto(BASE+'/chat',wait_until='networkidle');page.wait_for_function('() => window.gamearenaSocket?.connected')
 import time
 message=f'Browser confirmation test {time.time_ns()}';page.locator('#chatInput').fill(message);page.get_by_role('button',name='Send',exact=True).click();page.wait_for_function("() => document.getElementById('chatStatus').textContent==='Sent'")
 checks['chat_ack_clears_composer']=page.locator('#chatInput').input_value()==''
 checks['chat_message_not_duplicated']=page.locator('#messages').get_by_text(message,exact=True).count()==1
 page.evaluate('window.gamearenaSocket.disconnect();window.gamearenaSocket.connect()');page.wait_for_function('() => window.gamearenaSocket?.connected');page.wait_for_timeout(700)
 checks['chat_reconnect_not_duplicated']=page.locator('#messages').get_by_text(message,exact=True).count()==1
 # Sample all rendered local GET links, excluding logout and OAuth/payment callbacks.
 links=set()
 for path in ['/','/tournaments','/leaderboard','/profile','/dashboard','/wallet','/settings','/notifications','/chat','/search?q=PUBG','/tournament/2','/players/2','/support','/pay/2','/forgot-password']:
  response=page.goto(BASE+path,wait_until='networkidle'); assert response.status==200,(path,response.status)
  for href in page.locator('a[href]').evaluate_all('(els)=>els.map(el=>el.href)'):
   url=urlparse(href)
   if url.netloc=='127.0.0.1:5057' and url.path not in ['/logout','/google-login','/login/google'] and not any(part in url.path for part in ['verify-payment','verify-deposit','google']):links.add(href.split('#')[0])
 broken=[]
 for href in sorted(links):
  response=context.request.get(href)
  if response.status>=400:broken.append({'url':href,'status':response.status})
 checks['internal_get_links_checked']=len(links);checks['broken_internal_links']=broken
 page.goto(BASE+'/profile',wait_until='networkidle')
 page.wait_for_function('() => navigator.serviceWorker.controller !== null')
 checks['root_pwa_scope']=page.evaluate('navigator.serviceWorker.getRegistration().then(r=>r.scope)')==BASE+'/'
 cached=page.evaluate('caches.keys().then(async keys=>(await Promise.all(keys.filter(k=>k.startsWith("gamearena-")).map(async key=>(await (await caches.open(key)).keys()).map(r=>new URL(r.url).pathname)))).flat())')
 checks['private_pages_not_cached']=all(path.startswith('/static/') for path in cached)
 context.set_offline(True);page.goto(BASE+'/profile');checks['offline_private_page_shows_public_fallback']='offline' in page.title().lower();context.set_offline(False)
 browser.close()
report={'checks':checks,'page_errors':errors,'console_errors':console,'http_errors':failures}
(ROOT/'.local-test/browser-interactions.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
assert not errors and not checks['broken_internal_links']
assert all(value is True for key,value in checks.items() if isinstance(value,bool))
