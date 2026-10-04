"""Local-only review of the October 4 chat, hero and wallet changes."""
import json
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE='http://127.0.0.1:5059'
ROOT=Path(__file__).resolve().parent.parent
SHOTS=ROOT/'docs/screenshots';SHOTS.mkdir(exist_ok=True)
results={'layouts':[],'errors':[]}
def login(page,email):
    page.set_default_timeout(60000);page.goto(BASE+'/login')
    page.locator('[name=email]').fill(email);page.locator('[name=password]').fill('Preview-Only-42!')
    page.locator('form[method=POST] input[type=submit]').click();page.wait_for_url('**/dashboard')

with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    a=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce');b=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce')
    first=a.new_page();second=b.new_page()
    for page in [first,second]:page.on('pageerror',lambda error:results['errors'].append(str(error)))
    login(first,'preview@example.com')
    if '--layouts-only' not in sys.argv: login(second,'rival@example.com')
    if '--layouts-only' in sys.argv:
        results=json.loads((ROOT/'docs/validation/oct4-interactions.json').read_text())
    else:
        first.goto(BASE+'/messages/2');second.goto(BASE+'/messages/1')
        first.wait_for_function('() => window.gamearenaSocket?.connected');second.wait_for_function('() => window.gamearenaSocket?.connected')
        text='Live October 4 '+str(time.time_ns()); first.locator('#chatInput').fill(text)
        second.locator('#chatTyping').wait_for(state='visible');results['typing']=True
        started=time.perf_counter();first.locator('#chatForm button[type=submit]').click();second.get_by_text(text,exact=True).wait_for()
        results['live_delivery_ms']=round((time.perf_counter()-started)*1000,1)
        first.wait_for_function('() => document.getElementById("chatInput").value === ""')
        assert 'not confirmed' not in first.locator('#chatStatus').inner_text();results['confirmation']=True
        row=second.locator('[data-message-id]').filter(has=second.locator('[data-message-body]').filter(has_text=text));box=row.bounding_box()
        second.mouse.move(box['x']+15,box['y']+25);second.mouse.down();second.mouse.move(box['x']+85,box['y']+25,steps=4);second.mouse.up()
        second.locator('#replyPreview').wait_for(state='visible');results['swipe_reply']=True
        reply='Quoted October 4 '+str(time.time_ns());second.locator('#chatInput').fill(reply);second.locator('#chatForm button[type=submit]').click();first.get_by_text(reply,exact=True).wait_for()
        row=first.locator('[data-message-id]').filter(has=first.locator('[data-message-body]').filter(has_text=text));row.click(button='right')
        first.locator('[data-delete-message]').click();first.locator('[data-delete-confirm]').click()
        second.wait_for_function('(text) => !Array.from(document.querySelectorAll("[data-message-body]")).some(el => el.textContent === text)',arg=text)
        assert second.locator('.ga-chat-quote p').filter(has_text=text).count()==0;results['live_deletion']=True
        own=second.locator('[data-message-id]').filter(has=second.locator('[data-message-body]').filter(has_text=reply));own.scroll_into_view_if_needed();box=own.bounding_box()
        second.mouse.move(box['x']+20,box['y']+20);second.mouse.down();second.wait_for_timeout(650);second.mouse.up();second.locator('#messageActions').wait_for(state='visible');second.keyboard.press('Escape');results['long_press']=True
        # Force no socket delivery: the same UI recovers using authenticated HTTP.
        first.evaluate('window.gamearenaSocket.disconnect()');fallback='HTTP recovery '+str(time.time_ns())
        first.locator('#chatInput').fill(fallback);first.locator('#chatForm button[type=submit]').click();second.get_by_text(fallback,exact=True).wait_for();results['http_recovery']=True
        first.goto(BASE+'/wallet')
        attempts=[0]
        def banks(route):
            attempts[0]+=1
            if attempts[0]==1:route.fulfill(status=502,content_type='text/html',body='<!DOCTYPE html><h1>Temporary proxy error</h1>')
            else:route.fulfill(status=200,content_type='application/json',body=json.dumps({'banks':[{'name':'Isolated Example Bank','code':'058'}]}))
        first.route('**/wallet/banks',banks);first.get_by_role('button',name='Withdraw',exact=True).click()
        first.locator('#retryBanks').wait_for(state='visible');assert 'Unexpected token' not in first.locator('#bankStatus').inner_text()
        first.locator('#retryBanks').click();first.locator('#withdrawBank option[value="058"]').wait_for(state='attached');results['bank_retry']=True
        first.screenshot(path=str(SHOTS/'oct4-wallet-390.png'));first.keyboard.press('Escape')
        (ROOT/'docs/validation/oct4-interactions.json').write_text(json.dumps(results,indent=2))
    for theme in ['dark','light']:
        first.goto(BASE+'/settings');first.get_by_role('radio',name=theme.capitalize(),exact=True).check();first.get_by_role('button',name='Save settings',exact=True).click();first.wait_for_url('**/settings')
        for width in [360,390,768,1440]:
            first.set_viewport_size({'width':width,'height':900 if width==1440 else 844})
            for route in ['/','/messages/2','/wallet']:
                first.goto(BASE+route,wait_until='networkidle')
                state=first.evaluate('() => ({overflow:document.documentElement.scrollWidth>innerWidth,headers:document.querySelectorAll(".ga-header").length})')
                assert not state['overflow'] and state['headers']==1,(route,width,state)
                results['layouts'].append({'route':route,'width':width,'theme':theme,**state})
                if route=='/':
                    assert first.locator('.ga-hero').evaluate('(el)=>getComputedStyle(el).borderTopWidth')=='0px'
                    assert first.locator('.ga-hero').evaluate('(el)=>getComputedStyle(el).borderRadius')=='0px'
                if width in [390,1440] and route!=' /wallet':
                    name='home' if route=='/' else 'chat' if route.startswith('/messages') else 'wallet'
                    first.screenshot(path=str(SHOTS/f'oct4-{name}-{theme}-{width}.png'))
    assert not results['errors'];browser.close()
(ROOT/'docs/validation/oct4-updates.json').write_text(json.dumps(results,indent=2))
print(json.dumps({key:value for key,value in results.items() if key!='layouts'}));print(f"{len(results['layouts'])} responsive layouts passed")
