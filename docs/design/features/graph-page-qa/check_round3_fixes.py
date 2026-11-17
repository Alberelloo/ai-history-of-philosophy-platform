"""Проверка 6 findings round-3 после фиксов."""
import json, math
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = Path('docs/design/system/previews/graph-f02/index.html').resolve().as_uri()
def main():
    with sync_playwright() as p:
        b=p.chromium.launch(); page=b.new_page(viewport={'width':1440,'height':900})
        page.goto(URL); page.evaluate('document.fonts.ready'); page.wait_for_function('window.atlas&&atlas.geometry.length===8')
        out={}
        # F-R3-01: edges/markers outside frame on F1 fit 1440
        page.select_option('#fixture','genesis'); page.evaluate('atlas.fit()')
        out['F-R3-01_outside']=page.evaluate('''()=>{const f=document.querySelector('#graph').getBoundingClientRect();const r={edges:[],marks:[]};for(const e of document.querySelectorAll('.edge-line')){const bb=e.getBoundingClientRect();if(bb.top<f.top-1||bb.bottom>f.bottom+1||bb.left<f.left-1||bb.right>f.right+1)r.edges.push(e.parentElement.dataset.edgeId);}for(const m of document.querySelectorAll('.edge-status')){const bb=m.getBoundingClientRect();if(bb.top<f.top||bb.bottom>f.bottom||bb.left<f.left||bb.right>f.right)r.marks.push(m.dataset.edgeStatus);}return r;}''')
        # F-R3-02: dates clipped in F1/F2/F3
        page.select_option('#fixture','genesis'); page.evaluate('atlas.fit()')
        out['F-R3-02_enquiry']=page.evaluate('''()=>{const d=document.querySelector('[data-node-id="enquiry"] .node-date'),f=document.querySelector('[data-node-id="enquiry"] .node-label');const db=d.getBoundingClientRect(),fb=f.getBoundingClientRect();return Math.round(Math.max(0,db.bottom-fb.bottom)*10)/10;}''')
        page.select_option('#fixture','dense'); page.evaluate('atlas.setZoom(.5)')
        out['F-R3-02_d0']=page.evaluate('''()=>{const d=document.querySelector('[data-node-id="d-0"] .node-date'),f=document.querySelector('[data-node-id="d-0"] .node-label');if(!d||!f)return null;const db=d.getBoundingClientRect(),fb=f.getBoundingClientRect();return Math.round(Math.max(0,db.bottom-fb.bottom)*10)/10;}''')
        # F-R3-03: marker overlaps F3 overview
        out['F-R3-03_overlaps']=page.evaluate('''()=>{const ms=[...document.querySelectorAll('.edge-status')].map(m=>{const r=m.getBoundingClientRect();return {id:m.dataset.edgeStatus,x:r.x,y:r.y,w:r.width,h:r.height};});const ov=[];for(let i=0;i<ms.length;i++)for(let j=i+1;j<ms.length;j++){const a=ms[i],c=ms[j];const ix=Math.min(a.x+a.w,c.x+c.w)-Math.max(a.x,c.x),iy=Math.min(a.y+a.h,c.y+c.h)-Math.max(a.y,c.y);if(ix>1&&iy>1)ov.push([a.id,c.id,Math.round(ix),Math.round(iy)]);}return ov;}''')
        # F-R3-04: edges into foreign sign F3
        out['F-R3-04_signs']=page.evaluate('''()=>{const signs=[...document.querySelectorAll('.node-sign')].map(s=>s.getBoundingClientRect());const viol=[];for(const e of document.querySelectorAll('.edge-line')){const bb=e.getBoundingClientRect();for(const s of signs){const ix=Math.min(bb.right,s.right)-Math.max(bb.left,s.left),iy=Math.min(bb.bottom,s.bottom)-Math.max(bb.top,s.top);if(ix>1&&iy>1)viol.push(e.parentElement.dataset.edgeId);}}return [...new Set(viol)];}''')
        # F-R3-05: edges into label F3 overview
        out['F-R3-05_labels']=page.evaluate('''()=>{const labs=[...document.querySelectorAll('.node-label')].map(s=>s.getBoundingClientRect());const viol=[];for(const e of document.querySelectorAll('.edge-line')){const bb=e.getBoundingClientRect();for(const s of labs){const ix=Math.min(bb.right,s.right)-Math.max(bb.left,s.left),iy=Math.min(bb.bottom,s.bottom)-Math.max(bb.top,s.top);if(ix>1&&iy>1)viol.push(e.parentElement.dataset.edgeId);}}return [...new Set(viol)];}''')
        # F-R3-06: states duplicate
        page.select_option('#fixture','genesis')
        out['F-R3-06_states']={}
        for sc in ['loading','error','filtered']:
            page.select_option('#scenario',sc)
            out['F-R3-06_states'][sc]=page.evaluate('''()=>{const n=document.querySelector('#notice'),e=document.querySelector('#empty-message');return {notice:n.innerText,emptyVisible:!e.hidden,empty:e.innerText};}''')
        print(json.dumps(out,ensure_ascii=False,indent=2))
        b.close()
    return 0
if __name__=='__main__': raise SystemExit(main())
