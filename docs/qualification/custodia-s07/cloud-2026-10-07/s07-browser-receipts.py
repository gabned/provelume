import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'s07-browser-evidence'
BASE='http://127.0.0.1:8048'
rows=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    context=browser.new_context()
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(BASE+'/') else route.abort())
    page=context.new_page()
    for size,viewport,theme in [('desktop',{'width':1280,'height':900},'light'),('mobile',{'width':390,'height':844},'dark')]:
        page.set_viewport_size(viewport)
        page.goto(BASE+'/settings/shell?lang=en')
        page.locator('#shell-theme').select_option(theme)
        page.locator('button[name=action][value=save]').click()
        for language in ['de','en','es','fr','it','pt','ro']:
            for name in ['populated-operations','test-consent','test-enqueue']:
                if name=='populated-operations':
                    page.goto(BASE+'/operations/ai?lang='+language)
                elif name=='test-consent':
                    page.goto(BASE+'/settings/ai?lang='+language)
                    page.locator('form[action*="test/preview"] button').click()
                else:
                    page.locator('input[name=acknowledge]').check()
                    page.locator('form[action*="test/consent"] button').click()
                page.wait_for_load_state('networkidle')
                result=page.evaluate('({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,heading:document.querySelector("h1").innerText,lang:document.documentElement.lang})')
                result.update(surface=name,catalog=language,viewport=size,theme=theme)
                result['pass']=result['width']>=result['scroll'] and result['lang']==language
                assert 'Public synthetic test.' not in page.locator('main').inner_text()
                result['screenshot']=f'{language}-{name}-{theme}-{size}.png'
                page.screenshot(path=str(OUT/result['screenshot']),full_page=True)
                rows.append(result)
                (OUT/'receipts.json').write_text(json.dumps(rows,indent=2))
                print(result,flush=True)
    browser.close()
