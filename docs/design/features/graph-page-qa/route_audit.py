"""Геометрический аудит маршрутов: кривые ли это, не сливаются ли, не пересекают ли подписи."""
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = Path('docs/design/system/previews/graph-f02/index.html').resolve().as_uri()

def main():
    with sync_playwright() as p:
        b = p.chromium.launch(); page = b.new_page(viewport={'width':1440,'height':900})
        page.goto(URL); page.evaluate('document.fonts.ready')
        page.wait_for_function('window.atlas && atlas.geometry.length===8')
        page.evaluate('atlas.fit()')
        data = page.evaluate('''()=>{const gs=atlas.geometry.map(g=>({id:g.n.id,w:g.w,h:g.h,x:g.x,y:g.y}));const eps=atlas.edgePaths;return {gs,eps:eps.map(e=>({id:e.e.id,points:e.points,mid:e.mid}))};}''')
    gs = {g['id']:g for g in data['gs']}
    eps = data['eps']
    # 1) кривизна: доля длинных прямых горизонтальных/вертикальных участков между соседними сэмплами
    straight = {}
    for e in eps:
        pts = e['points']; n = len(pts); ax = 0
        for i in range(1, n):
            a, c = pts[i-1], pts[i]
            if abs(a['x']-c['x']) < 0.5 or abs(a['y']-c['y']) < 0.5:
                ax += 1
        straight[e['id']] = ax/max(n-1,1)
    # 2) мин. расстояние между парами кривых и маркеров
    import math
    def mindist(A,B):
        m=1e9
        for a in A:
            for q in B:
                d=math.hypot(a['x']-q['x'],a['y']-q['y'])
                if d<m:m=d
        return m
    pairmin=[]
    for i in range(len(eps)):
        for j in range(i+1,len(eps)):
            pairmin.append((eps[i]['id'],eps[j]['id'],round(mindist(eps[i]['points'],eps[j]['points']),2)))
    merged=[x for x in pairmin if x[2] < 6]
    # 3) маркер на своей кривой: расстояние маркера до своей кривой ~0 и до чужих
    foreign=[]
    for e in eps:
        own=mindist([e['mid']],e['points'])
        others=[mindist([e['mid']],o['points']) for o in eps if o['id']!=e['id']]
        nearest_other=min(others) if others else 1e9
        if own > 1 or nearest_other < 3:
            foreign.append((e['id'], round(own,2), round(nearest_other,2)))
    out={'axis_aligned_share':straight,'merged_pairs_lt6px':merged,'marker_foreign':foreign}
    Path('docs/design/features/graph-page-qa/route-audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('axis_aligned_share', straight)
    print('merged_pairs_lt6px', merged)
    print('marker_foreign', foreign)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
