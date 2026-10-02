"""Review the isolated preview at multiple widths; save evidence and screenshots."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / '.local-test/screenshots'
OUTPUT.mkdir(parents=True, exist_ok=True)
BASE = 'http://127.0.0.1:5057'
results = []
errors = []
console_errors = []
from urllib.request import urlopen
import time
for attempt in range(30):
    try:
        with urlopen(BASE+'/health', timeout=2) as response:
            if response.status == 200: break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit('Start scripts/preview_interface.py before running this check.')
with sync_playwright() as pw:
    browser = pw.chromium.launch(channel='chrome', headless=True)
    context = browser.new_context(viewport={'width':390,'height':844}, reduced_motion='reduce')
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: console_errors.append(message.text) if message.type == 'error' else None)
    for width in (360,390,768,1440):
        page.set_viewport_size({'width':width,'height':900 if width>767 else 844})
        for name, route in [('home','/'),('tournaments','/tournaments'),('leaderboard','/leaderboard'),('search','/search?q=PUBG'),('register','/register'),('details','/tournament/2')]:
            response = page.goto(BASE+route, wait_until='networkidle')
            state = page.evaluate('''() => ({overflow: document.documentElement.scrollWidth > innerWidth, headers: document.querySelectorAll('.ga-header').length, h1s: document.querySelectorAll('h1').length, guestBell: document.querySelectorAll('.ga-notifications').length})''')
            results.append({'state':'guest','page':name,'width':width,'status':response.status,**state})
            if (width in (390,1440) and name in ('home','leaderboard','details')) or (width == 390 and name == 'register'):
                page.screenshot(path=str(OUTPUT/f'guest-{name}-{width}.png'), full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    page.goto(BASE+'/login')
    page.locator('input[name=email]').fill('preview@example.com')
    page.locator('input[name=password]').fill('Preview-Only-42!')
    page.locator('form[method=POST] input[type=submit]').click()
    page.wait_for_load_state('networkidle')
    results.append({'login_url':page.url,'login_success':page.url.endswith('/dashboard')})
    if page.url.endswith('/dashboard'):
        for width in (360,390,768,1440):
            page.set_viewport_size({'width':width,'height':900 if width>767 else 844})
            for name, route in [(name,'/'+name) for name in ('profile','dashboard','wallet','settings','notifications','chat')] + [('player','/players/2'),('support','/support'),('payment','/pay/2'),('direct-chat','/messages/2')]:
                response = page.goto(BASE+route, wait_until='networkidle')
                state = page.evaluate('''() => ({overflow: document.documentElement.scrollWidth > innerWidth, headers: document.querySelectorAll('.ga-header').length, bell: document.querySelectorAll('.ga-notifications').length, badge: document.querySelector('[data-unread-badge]')?.textContent.trim()})''')
                results.append({'state':'authenticated','page':name,'width':width,'status':response.status,**state})
                if width in (390,1440) and name in ('profile','dashboard','wallet','settings','chat'):
                    page.screenshot(path=str(OUTPUT/f'owner-{name}-{width}.png'), full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.goto(BASE+'/profile',wait_until='networkidle')
        menu = page.locator('.ga-mobile-menu summary')
        menu.focus(); page.keyboard.press('Enter')
        page.keyboard.press('Escape')
        results.append({'menu_escape_closes':not page.locator('.ga-mobile-menu').evaluate('(el)=>el.open'),'menu_focus_restored':menu.evaluate('(el)=>el===document.activeElement')})
    # The admin fixture uses the existing login and permission checks.
    admin = browser.new_context(viewport={'width':390,'height':844}, reduced_motion='reduce')
    admin_page = admin.new_page()
    admin_page.on('pageerror', lambda error: errors.append(str(error)))
    admin_page.goto(BASE+'/login')
    admin_page.locator('input[name=email]').fill('admin@example.com')
    admin_page.locator('input[name=password]').fill('Preview-Only-42!')
    admin_page.locator('form[method=POST] input[type=submit]').click()
    admin_page.wait_for_url('**/dashboard')
    for width in (360,390,768,1440):
        admin_page.set_viewport_size({'width':width,'height':900 if width>767 else 844})
        for name, route in [('admin','/admin'),('reports','/admin/reports'),('create','/admin/create-tournament'),('edit','/admin/tournaments/2/edit'),('results','/admin/tournaments/1/leaderboard')]:
            response = admin_page.goto(BASE+route,wait_until='networkidle')
            state = admin_page.evaluate('''() => ({overflow: document.documentElement.scrollWidth > innerWidth, headers: document.querySelectorAll('.ga-header').length})''')
            results.append({'state':'admin','page':name,'width':width,'status':response.status,**state})
    browser.close()
report={'checks':results,'page_errors':errors,'console_errors':console_errors}
(ROOT / '.local-test/browser-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
assert all(item.get('status',200)==200 and not item.get('overflow',False) for item in results), 'Page status or overflow failure: inspect browser-results.json'
assert not errors and not console_errors, 'Browser errors: inspect browser-results.json'
assert any(item.get('login_success') for item in results), 'Login did not succeed'
print(json.dumps({'page_checks':sum('status' in item for item in results),'page_errors':errors,'console_errors':console_errors}))
