"""Точечная проверка 7 фиксов round-2 перед раундом 3 (всё в user-координатах)."""
import json, math
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = Path('docs/design/system/previews/graph-f02/index.html').resolve().as_uri()
def main():
    with sync_playwright() as p:
        b=p.chromium.launch(); page=b.new_page(viewport={'width':1440,'height':900})
        page.goto(URL); page.evaluate('document.fonts.ready'); page.wait_for_function('window.atlas&&atlas.geometry.length===8')
        out={}
        page.select_option('#fixture','specimens'); page.evaluate('atlas.fit()')
        out['F-R2-01_parallel']=page.evaluate('''()=>{const a=atlas.edgePaths.find(p=>p.e.id==='spec-0'),b=atlas.edgePaths.find(p=>p.e.id==='spec-parallel');return {sameD:a.d===b.d,midDist:Math.round(Math.hypot(a.points[14].x-b.points[14].x,a.points[14].y-b.points[14].y)*10)/10};}''')
        page.select_option('#fixture','genesis'); page.evaluate('atlas.fit()')
        out['F-R2-02_enquiry']=page.evaluate('''()=>{const g=atlas.geometry.find(g=>g.n.id==='enquiry');const d=document.querySelector('[data-node-id="enquiry"] .node-date');const fo=document.querySelector('[data-node-id="enquiry"] .node-label');const db=d?d.getBoundingClientRect():null,fb=fo?fo.getBoundingClientRect():null;return {labelH:Math.round(g.labelH),date:d?d.textContent:null,clippedPx:db&&fb?Math.round(Math.max(0,db.bottom-fb.bottom)*10)/10:0};}''')
        out['F-R2-03_label']=page.evaluate('''()=>{const boxes=atlas.geometry.map(g=>({id:g.n.id,x:g.x-g.labelWidth/2,y:g.y+g.labelY,w:g.labelWidth,h:g.labelH}));const viol=new Set();for(const e of atlas.edgePaths){for(const p of e.points.slice(1,-1)){for(const r of boxes){if(p.x>r.x&&p.x<r.x+r.w&&p.y>r.y&&p.y<r.y+r.h){viol.add(e.e.id);break;}}}}return {edgesIntoLabel:[...viol]};}''')
        page.select_option('#fixture','dense'); page.evaluate('atlas.setZoom(.5)')
        out['F-R2-04_overview']=page.evaluate('''()=>{const r=[];for(const n of document.querySelectorAll('.node-sign')){const bb=n.getBoundingClientRect();r.push([Math.round(bb.width*10)/10,Math.round(bb.height*10)/10]);}return {bad:r.filter(s=>s[0]<15.5||s[1]<15.5||s[0]>24.5||s[1]>24.5),count:r.length};}''')
        page.select_option('#fixture','specimens'); page.evaluate("atlas.state.lang='en';atlas.render()")
        out['F-R2-05_en_date']=page.evaluate("()=>document.querySelector('[data-node-id=\"s-0\"] .node-date')?.textContent||null")
        page.select_option('#fixture','genesis'); page.evaluate("atlas.state.theme='dark';atlas.render()")
        out['F-R2-06_shadow']=page.evaluate("()=>({dark:getComputedStyle(document.querySelector('.folio')).boxShadow})")
        page.evaluate("atlas.state.theme='light';atlas.render()")
        out['F-R2-06_shadow']['light']=page.evaluate("()=>getComputedStyle(document.querySelector('.folio')).boxShadow")
        out['F-R2-07_button']=page.evaluate("()=>{const r=document.querySelector('#list-button').getBoundingClientRect();return {w:Math.round(r.width*10)/10,h:Math.round(r.height*10)/10};}")
        print(json.dumps(out,ensure_ascii=False,indent=2))
        b.close()
    return 0
if __name__=='__main__': raise SystemExit(main())
