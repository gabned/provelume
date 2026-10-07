import base64
import json
import math
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 's07-browser-evidence'
BASE = 'http://127.0.0.1:8047'
fixture = json.loads((ROOT / 's07-visual-final/fixture.json').read_text())
rows = []


def ready(page):
    page.wait_for_load_state('networkidle')
    page.evaluate('document.fonts.ready')


def open_surface(page, name, language):
    path = {'settings':'/settings/ai','blocked-test':'/settings/ai',
            'document':f'/documents/{fixture["document"]}/ai',
            'document-preview':f'/documents/{fixture["document"]}/ai',
            'operations':'/operations/ai','components':'/components'}[name]
    page.goto(BASE+path+'?lang='+language)
    if name == 'document-preview':
        page.locator('#ai-end').fill(str(fixture['text_length']))
        page.locator('form.settings-form button[type=submit]').click()
    elif name == 'blocked-test':
        page.locator('form[action*="test/preview"] button').click()
    ready(page)


def keyboard(page):
    # Tab through the real document; inspect names/focus without changing tabindex.
    expected = page.evaluate('''() => [...document.querySelectorAll('a[href],button,input:not([type=hidden]),select,summary,[tabindex="0"]')]
      .filter(e => e.getClientRects().length && !e.disabled && e.tabIndex >= 0 && (!e.closest('details:not([open])') || e.matches('details:not([open]) > summary'))).length''')
    page.locator('body').click(position={'x':1,'y':1})
    seen = set()
    unnamed = []
    invisible_focus = []
    for _ in range(expected + 5):
        page.keyboard.press('Tab')
        current = page.evaluate('''() => {
          const e=document.activeElement,s=getComputedStyle(e);
          return {index:[...document.querySelectorAll('*')].indexOf(e),tag:e.tagName,
            name:(e.getAttribute('aria-label') || [...(e.labels||[])].map(l=>l.innerText).join(' ') || e.innerText || e.title).trim(),
            outline:s.outlineStyle,width:s.outlineWidth};}''')
        if current['tag'] in ['BODY','HTML']:
            continue
        seen.add(current['index'])
        if not current['name'] and current['tag'] != 'DIV':
            unnamed.append(current)
        if current['outline'] == 'none' or current['width'] == '0px':
            invisible_focus.append(current)
    return {'expected_focusable':expected,'visited':len(seen),'unnamed':unnamed,
            'invisible_focus':invisible_focus,'pass':len(seen)>=expected and not unnamed and not invisible_focus}


with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    context=browser.new_context(viewport={'width':390,'height':844})
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(BASE+'/') else route.abort())
    page=context.new_page()
    for language in ['de','en','es','fr','it','pt','ro']:
        page.goto(BASE+'/settings/ai?lang='+language)
        page.locator('#ai-mode').select_option('local')
        page.locator('form[action="/settings/ai?lang='+language+'"] button[type=submit]').click()
        for name in ['settings','blocked-test','document','document-preview','operations','components']:
            open_surface(page,name,language)
            row={'surface':name,'catalog':language,'keyboard':keyboard(page)}
            if name == 'settings':
                summary=page.locator('form details summary')
                summary.focus();page.keyboard.press('Enter')
                row['advanced_keyboard_open']=page.locator('form details').get_attribute('open') is not None
                row['expanded_keyboard']=keyboard(page)
                nav=page.locator('[data-cura-navigation] summary')
                nav.focus();page.keyboard.press('Enter');page.keyboard.press('Escape')
                row['escape_returns_focus']=nav.evaluate('(e)=>document.activeElement===e && !e.parentElement.open')
                page.goto(BASE+'/operations/ai?lang='+language)
                page.go_back();ready(page)
                before=page.locator('input[name=revision]').first.input_value()
                page.reload();ready(page)
                row['back_refresh_preserves_revision']=before==page.locator('input[name=revision]').first.input_value()
            if name=='components':
                table=page.locator('.components-table');table.focus();page.keyboard.press('ArrowRight')
                page.wait_for_timeout(250)
                row['table_keyboard_scroll']=table.evaluate('(e)=>e.scrollLeft>0 && e.scrollWidth>e.clientWidth')
            rows.append(row)
            (OUT/'accessibility.json').write_text(json.dumps(rows,indent=2))
            print(language,name,row,flush=True)
    browser.close()
    if '--keyboard-only' in sys.argv:
        sys.exit(0)
    profile=ROOT/'s07-zoom-qualification'
    (profile/'Default').mkdir(parents=True,exist_ok=True)
    zoom=math.log(2)/math.log(1.2)
    (profile/'Default/Preferences').write_text(json.dumps({'partition':{'default_zoom_level':{'x':zoom},'per_host_zoom_levels':{'x':{'127.0.0.1':zoom}}}}))
    context=p.chromium.launch_persistent_context(str(profile),executable_path='/usr/bin/chromium',headless=True,viewport=None,args=['--window-size=1280,900'])
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(BASE+'/') else route.abort())
    page=context.pages[0]
    zoom_rows=[]
    for theme in ['light','dark','system']:
        page.goto(BASE+'/settings/shell?lang=en')
        page.locator('#shell-theme').select_option(theme)
        page.locator('button[name=action][value=save]').click()
        page.emulate_media(color_scheme='dark' if theme=='system' else theme)
        for language in ['de','en','es','fr','it','pt','ro']:
            page.goto(BASE+'/settings/ai?lang='+language)
            page.locator('#ai-mode').select_option('local')
            page.locator('form[action="/settings/ai?lang='+language+'"] button[type=submit]').click()
            for name in ['settings','blocked-test','document','document-preview','operations','components']:
                open_surface(page,name,language)
                state=page.evaluate('({inner:innerWidth,outer:outerWidth,dpr:devicePixelRatio,scale:visualViewport.scale,width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})')
                state.update(surface=name,catalog=language,theme=theme)
                state['pass']=state['inner']==640 and state['outer']==1280 and state['dpr']==2 and state['scale']==1 and state['scroll']<=state['width']
                if language=='it':
                    shot=context.new_cdp_session(page).send('Page.captureScreenshot', {'format':'png','captureBeyondViewport':False})
                    (OUT/f'it-{name}-{theme}-zoom200.png').write_bytes(base64.b64decode(shot['data']))
                zoom_rows.append(state)
                (OUT/'zoom.json').write_text(json.dumps(zoom_rows,indent=2))
                print('ZOOM',state,flush=True)
    page.goto(BASE+'/settings/ai?lang=en')
    page.locator('#ai-mode').select_option('off')
    page.locator('form[action="/settings/ai?lang=en"] button[type=submit]').click()
    context.close()
