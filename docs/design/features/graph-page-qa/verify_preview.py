"""Браузерные проверки isolated preview Ф0.2; запуск из корня репозитория."""
from pathlib import Path
import base64
import json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[4]
QA = Path(__file__).resolve().parent
OUT = QA / 'captures'
URL = (ROOT / 'docs/design/system/previews/graph-f02/index.html').as_uri()


def main():
    OUT.mkdir(exist_ok=True)
    results = []
    errors = []
    def record(case, passed, detail=''):
        results.append(dict(case=case, passed=bool(passed), detail=detail))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width':1440,'height':900}, device_scale_factor=1)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(URL)
        page.evaluate('document.fonts.ready')
        page.wait_for_function('window.atlas && window.atlas.geometry.length===8')
        capture_session = page.context.new_cdp_session(page)
        def snap(name):
            # Evidence fix: Playwright full_page can resize/trigger fit(), corrupting z=.5.
            size = capture_session.send('Page.getLayoutMetrics')['cssContentSize']
            png = capture_session.send('Page.captureScreenshot', {
                'format':'png', 'captureBeyondViewport':True,
                'clip':dict(x=0,y=0,width=size['width'],height=size['height'],scale=1),
            })
            (OUT / f'{name}.png').write_bytes(base64.b64decode(png['data']))
        def state(**changes):
            page.evaluate('(c)=>{Object.assign(atlas.state,c);atlas.render();}', changes)
        def fixture(name):
            page.select_option('#fixture', name)
        for w,h in [(1440,900),(1024,768)]:
            page.set_viewport_size({'width':w,'height':h})
            for theme in ['light','dark']:
                for lang in ['ru','en']:
                    state(theme=theme,lang=lang)
                    page.evaluate('atlas.fit()')
                    snap(f'genesis-{theme}-{lang}-{w}')
                    record(f'TC-03/06/{w}/{theme}/{lang}', page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'No page horizontal overflow')
        state(theme='light',lang='ru')
        for w,pinned in [(1280,False),(1280,True),(1920,False)]:
            page.set_viewport_size({'width':w,'height':900 if w==1280 else 1080})
            state(pinned=pinned)
            page.evaluate('atlas.fit()')
            snap(f'layout-{w}-pinned-{pinned}')
            positions=page.evaluate('''()=>{const g=document.querySelector('#graph').getBoundingClientRect(), n=document.querySelector('#note').getBoundingClientRect();return {below:n.top>=g.bottom-1,gw:g.width,gh:g.height};}''')
            record(f'TC-04/05/{w}/{pinned}',positions['below']==(w==1280 and pinned),positions)
        page.set_viewport_size({'width':1440,'height':900})
        state(pinned=False)
        page.evaluate('atlas.fit()')
        network=page.locator('#graph').bounding_box()
        note=page.locator('#note').bounding_box()
        record('TC-02', network['width']/(note['x']+note['width']-network['x'])>=.7 and network['height']>=480, network)
        page.evaluate("atlas.selectNode('hume')")
        snap('selected-node')
        record('TC-09',page.locator('[data-node-id="hume"]').get_attribute('aria-pressed')=='true' and page.evaluate("atlas.state.start==='kant'"))
        page.locator('#restart-node').click()
        record('TC-17/restart',page.evaluate("atlas.state.start==='hume'") and 'Юм' in page.locator('#title').inner_text())
        page.select_option('#fixture','genesis')
        page.evaluate("atlas.selectEdge('kant-hume')")
        snap('selected-edge')
        record('TC-10', 'Иммануил Кант' in page.locator('#note').inner_text() and page.evaluate("""()=>{const p=atlas.edgePaths.find(p=>p.e.id==='kant-hume');const nearest=q=>atlas.geometry.reduce((a,g)=>Math.hypot(q.x-g.x,q.y-g.y)<Math.hypot(q.x-a.x,q.y-a.y)?g:a).n.id;const path=document.querySelector('[data-edge-id=\"kant-hume\"] .edge-line');return p.e.subject==='kant'&&p.e.object==='hume'&&nearest(p.points[0])==='kant'&&nearest(p.points.at(-1))==='hume'&&path.getAttribute('marker-end')==='url(#arrow-genesis)';}"""))
        record('TC-18',page.locator('#note blockquote').count()==1 and page.locator('#note [data-status="verified"]').count()==1)
        page.keyboard.press('Escape')
        page.locator('[data-node-id="hume"]').focus()
        snap('keyboard-focus')
        record('TC-17/focus',page.locator('#note').inner_text().find('Дэвид Юм')>=0)
        page.locator('#search').fill('Локк')
        page.locator('#search').press('Enter')
        record('TC-17/search',page.evaluate("atlas.state.selected.id==='locke'"))
        page.locator('#search').fill('несуществующий')
        record('TC-17/empty-search','Ничего не найдено' in page.locator('#note').inner_text())
        page.locator('#search').fill('')
        page.evaluate('atlas.fit();atlas.setZoom(2)')
        record('TC-16/minimap',page.locator('#minimap').is_visible())
        page.locator('#minimap').click(position={'x':20,'y':20})
        page.locator('#fit').click()
        record('TC-16/fit',not page.locator('#minimap').is_visible())
        for theme in ['light','dark']:
            fixture('specimens');state(theme=theme)
            snap(f'specimens-{theme}')
            record(f'TC-11/{theme}',page.locator('[data-edge-id]').count()==20 and page.locator('[data-edge-status]').count()==20)
        fixture('dense')
        for theme in ['light','dark']:
            state(theme=theme);page.evaluate('atlas.setZoom(.5)')
            snap(f'dense-overview-{theme}')
        record('TC-14',page.locator('[data-node-id]').count()==16 and page.locator('[data-cluster-id]').count()==2)
        page.locator('[data-cluster-id]').first.click()
        snap('dense-expanded')
        record('TC-15',page.locator('[data-node-id]').count()==32 and page.locator('[data-cluster-id]').count()==1)
        fixture('genesis');state(theme='light',lang='ru')
        for scenario in ['loading','extending','off','unavailable','error','empty','filtered','limited']:
            page.select_option('#scenario',scenario)
            snap(f'state-{scenario}')
            record(f'TC-20/{scenario}',bool(page.locator('#notice').inner_text()))
        page.select_option('#scenario','normal')
        page.emulate_media(reduced_motion='reduce')
        snap('reduced-motion')
        record('TC-21',page.locator('[data-edge-id]').count()==10)
        page.add_style_tag(content='#atlas-app{filter:grayscale(1)} .sheet{box-shadow:none!important}')
        snap('grayscale')
        record('JS-errors',not errors,errors)
        browser.close()
    report={'results':results,'errors':errors,'screenshots':len(list(OUT.glob('*.png'))),'not_tested':['TC-22 real browser zoom 200%','TC-23b streaming API (not applicable)','full route-label collision audit','portrait failure interception']}
    (QA/'browser-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':len(results),'failed':[r for r in results if not r['passed']],'screenshots':report['screenshots']},ensure_ascii=True))
    return int(any(not r['passed'] for r in results))

if __name__=='__main__':
    raise SystemExit(main())
