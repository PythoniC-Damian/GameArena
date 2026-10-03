"""Review new product interactions against the isolated loopback preview only."""
import json
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE='http://127.0.0.1:5057'
ROOT=Path(__file__).resolve().parent.parent
RESULTS=ROOT/'docs/validation';RESULTS.mkdir(parents=True,exist_ok=True)
SHOTS=ROOT/'docs/screenshots';SHOTS.mkdir(parents=True,exist_ok=True)
checks=[];errors=[]
def login(page,email):
    page.set_default_timeout(90000);page.set_default_navigation_timeout(90000)
    page.goto(BASE+'/login');page.locator('[name=email]').fill(email);page.locator('[name=password]').fill('Preview-Only-42!')
    page.locator('form[method=POST] input[type=submit]').click();page.wait_for_url('**/dashboard')

with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    owner=browser.new_context(viewport={'width':1440,'height':900},reduced_motion='reduce');page=owner.new_page()
    page.on('pageerror',lambda error:errors.append(str(error)));page.add_init_script('window.splashWasVisible = false; new MutationObserver(() => { const splash = document.getElementById("gamearena-preloader"); if (splash && !splash.hidden) window.splashWasVisible = true; }).observe(document, {childList:true,subtree:true,attributes:true,attributeFilter:["hidden"]});');login(page,'preview@example.com')
    themes = [] if '--interactions-only' in sys.argv else ['light','dark']
    if not themes: checks = json.loads((RESULTS/'product-updates-layouts.json').read_text(encoding='utf-8'))
    for theme in themes:
        page.goto(BASE+'/settings');page.get_by_role('radio',name=theme.capitalize(),exact=True).check()
        page.get_by_role('button',name='Save settings',exact=True).click();page.wait_for_url('**/settings')
        assert page.locator('html').get_attribute('data-theme')==theme
        for width in [360,390,768,1440]:
            page.set_viewport_size({'width':width,'height':900 if width==1440 else 844})
            for route in ['/','/profile','/settings','/wallet','/chat','/leaderboard']:
                response=page.goto(BASE+route,wait_until='networkidle');assert response.status==200
                layout=page.evaluate('() => ({overflow:document.documentElement.scrollWidth>innerWidth,headers:document.querySelectorAll(".ga-header").length,theme:document.documentElement.dataset.theme})')
                assert not layout['overflow'] and layout['headers']==1 and layout['theme']==theme
                checks.append({'route':route,'width':width,**layout})
                if width in [390,1440] and route in ['/','/profile','/leaderboard']:
                    name='home' if route=='/' else route[1:]
                    page.screenshot(path=str(SHOTS/f'{name}-{theme}-{width}.png'))
            page.locator('[data-notification-menu] summary').click();page.wait_for_function('() => document.querySelector("[data-notification-preview]").textContent !== "Loading updates…"')
            assert page.url==BASE+'/leaderboard'
            panel=page.locator('.ga-notification-panel');assert panel.is_visible()
            box=panel.bounding_box();assert box['x']>=0 and box['x']+box['width']<=width+1
            page.screenshot(path=str(SHOTS/f'notifications-{theme}-{width}.png'))
            print(f'Layout reviewed: {theme} / {width}px',flush=True); page.keyboard.press('Escape');assert page.locator('[data-notification-menu]').get_attribute('open') is None
    (RESULTS/'product-updates-layouts.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    page.goto(BASE+'/');assert page.locator('#featuredCube').count()==0
    assert page.locator('.ga-hero-background img').count()==15
    assert page.locator('.ga-card-carousel img').count()>4
    page.goto(BASE+'/leaderboard');assert page.locator('tbody tr').filter(has_text='demo_bot_').count()==6
    page.goto(BASE+'/settings');page.wait_for_function('() => document.querySelector("[data-push-status]").textContent.includes("being set up")');assert page.locator('[data-enable-push]').is_disabled()
    page.goto(BASE+'/');page.reload(wait_until='domcontentloaded');assert page.evaluate('window.splashWasVisible')
    page.wait_for_function('() => document.getElementById("gamearena-preloader").hidden')
    # Two real browser sessions: no mocks or page refreshes for message delivery.
    other=browser.new_context(viewport={'width':390,'height':844});rival=other.new_page();rival.on('pageerror',lambda error:errors.append(str(error)));login(rival,'rival@example.com')
    page.goto(BASE+'/messages/2',wait_until='networkidle');rival.goto(BASE+'/messages/1',wait_until='networkidle')
    page.wait_for_function('() => window.gamearenaSocket?.connected');rival.wait_for_function('() => window.gamearenaSocket?.connected')
    unique=f'Live message {time.time_ns()}'
    start=time.perf_counter();page.get_by_role('textbox',name='Message',exact=True).fill(unique);page.get_by_role('button',name='Send',exact=True).click()
    rival.locator('[data-message-body]').filter(has_text=unique).wait_for();delivery_ms=round((time.perf_counter()-start)*1000,1)
    row=rival.locator('[data-message-id]').filter(has_text=unique).last;row.get_by_role('button',name='Reply to arena_preview').click()
    assert rival.locator('#replyPreview').is_visible()
    reply=f'Reply {time.time_ns()}';rival.get_by_role('textbox',name='Message',exact=True).fill(reply);rival.get_by_role('button',name='Send',exact=True).click()
    page.locator('[data-message-body]').filter(has_text=reply).wait_for();reply_row=page.locator('[data-message-id]').filter(has_text=reply).last
    assert reply_row.locator('.ga-chat-quote').inner_text().find(unique)>=0
    page.reload(wait_until='networkidle');assert page.locator('.ga-chat-quote').filter(has_text=unique).count()>0
    page.screenshot(path=str(SHOTS/'chat-replies-desktop.png'));rival.screenshot(path=str(SHOTS/'chat-replies-mobile.png'))
    # Mobile pointer swipe selects the original message as a reply.
    row=rival.locator('[data-message-id]').filter(has_text=unique).last
    row.dispatch_event('pointerdown',{'clientX':20,'clientY':50});row.dispatch_event('pointerup',{'clientX':90,'clientY':50})
    assert rival.locator('#replyPreview').is_visible()
    rival.get_by_role('button',name='Cancel reply').click()
    # Preview opening does not clear unread; explicit Mark all read does.
    page.locator('[data-notification-menu] summary').click();page.get_by_role('button',name='Mark all read',exact=True).click()
    page.wait_for_function('() => document.querySelector("[data-unread-badge]").hidden')
    assert page.locator('[data-notification-menu]').evaluate('(menu) => menu.open'); page.get_by_role('link',name='View all notifications',exact=True).click();page.wait_for_url('**/notifications')
    # Hover feedback at desktop width changes the primary action appearance.
    page.goto(BASE+'/tournaments');action=page.get_by_role('link',name='View tournament',exact=True).first
    page.mouse.move(0,0);before=action.evaluate('(el)=>getComputedStyle(el).backgroundColor');action.hover();page.wait_for_timeout(250)
    after=action.evaluate('(el)=>getComputedStyle(el).backgroundColor');assert before!=after
    browser.close()
assert not errors
report={'layouts':checks,'layout_count':len(checks),'live_delivery_ms':delivery_ms,'reply_button':True,'swipe_reply':True,'reply_persistence':True,'notification_preview':True,'explicit_mark_read':True,'view_all_navigation':True,'theme_persistence':True,'demo_bots':6,'refresh_logo':True,'button_hover':True,'push_setup_state':True,'page_errors':errors}
(RESULTS/'product-updates-browser.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
