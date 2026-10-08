import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 's07-browser-evidence'
OUT.mkdir(exist_ok=True)
fixture = json.loads((ROOT / 's07-visual-final/fixture.json').read_text())
BASE = 'http://127.0.0.1:8047'
rows = []
errors = []

def inspect(page, name, language, theme, size):
    page.wait_for_load_state('networkidle')
    page.evaluate('document.fonts.ready')
    result = page.evaluate('''() => ({
      title: document.title, heading: document.querySelector('h1')?.innerText,
      language: document.documentElement.lang, theme: document.documentElement.dataset.theme,
      width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth,
      unnamed: [...document.querySelectorAll('input:not([type=hidden]),select,textarea')]
        .filter(e => e.getClientRects().length && !e.labels?.length && !e.getAttribute('aria-label')).map(e=>e.id),
      alerts: [...document.querySelectorAll('[role=alert]')].map(e=>e.innerText),
      devicePixelRatio, viewportScale: visualViewport.scale
    })''')
    result.update(surface=name, catalog=language, appearance=theme, viewport=size)
    filename = f'{language}-{name}-{theme}-{size}.png'
    page.screenshot(path=str(OUT / filename), full_page=True)
    result['screenshot'] = filename
    result['pass'] = bool(result['heading']) and result['language'] == language and result['scroll'] <= result['width'] and not result['unnamed']
    rows.append(result)
    print(json.dumps({k:result[k] for k in ['surface','catalog','appearance','viewport','pass','scroll','width']}), flush=True)
    (OUT / 'matrix.json').write_text(json.dumps({'rows':rows,'page_errors':errors},indent=2))

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
    context = browser.new_context(viewport={'width':1280,'height':900})
    # This browser may request only the owned synthetic preview.
    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(BASE + '/') else route.abort())
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    for theme in ['light','dark','system']:
        page.goto(BASE+'/settings/shell?lang=en')
        page.locator('#shell-theme').select_option(theme)
        page.locator('button[name=action][value=save]').click()
        for size,viewport in [('desktop',{'width':1280,'height':900}),('mobile',{'width':390,'height':844})]:
            page.set_viewport_size(viewport)
            page.emulate_media(color_scheme='dark' if theme == 'system' else theme)
            for language in ['de','en','es','fr','it','pt','ro']:
                page.goto(BASE+'/settings/ai?lang='+language)
                page.locator('#ai-mode').select_option('local')
                page.locator('form[action="/settings/ai?lang='+language+'"] button[type=submit]').click()
                for name,path in [('settings','/settings/ai'),('document',f'/documents/{fixture["document"]}/ai'),('operations','/operations/ai'),('components','/components')]:
                    response=page.goto(BASE+path+'?lang='+language)
                    assert response.status == 200, (name,response.status)
                    inspect(page,name,language,theme,size)
                    if name == 'document':
                        page.locator('#ai-end').fill(str(fixture['text_length']))
                        page.locator('form.settings-form button[type=submit]').click()
                        inspect(page,'document-preview',language,theme,size)
                        assert '[REDACTED]' in page.locator('main').inner_text()
                        assert page.locator('script').count() == 1
                        assert not page.locator('form[action*="consent"],form[action*="enqueue"]').count()
                    if name == 'settings':
                        page.locator('form[action*="test/preview"] button').click()
                        inspect(page,'blocked-test',language,theme,size)
                        assert not page.locator('form[action*="consent"],form[action*="enqueue"]').count()
    page.goto(BASE+'/settings/ai?lang=en')
    page.locator('#ai-mode').select_option('off')
    page.locator('form[action="/settings/ai?lang=en"] button[type=submit]').click()
    browser.close()
print('COMPLETE',len(rows),'FAILURES',sum(not r['pass'] for r in rows),flush=True)
