// Аудит контраста текста на бумаге (обе темы), с учётом прозрачности приглушённых групп.
const {chromium}=require('playwright-core');const path=require('path');
const URL='file://'+path.resolve('/root/ai-history-of-philosophy-platform/docs/design/system/previews/graph-f02-lenses/desk.html');
(async()=>{
 const b=await chromium.launch({executablePath:'/root/.cache/puppeteer/chrome/linux-148.0.7778.97/chrome-linux64/chrome',args:['--no-sandbox']});
 const p=await b.newPage({viewport:{width:1440,height:1080}});await p.goto(URL,{waitUntil:'networkidle'});await p.evaluate(()=>document.fonts.ready);
 const out={};
 for(const theme of ['light','dark']){
  await p.evaluate(t=>{document.getElementById('app').dataset.theme=t;document.getAnimations().forEach(a=>a.finish());},theme);await p.waitForTimeout(200);
  out[theme]=await p.evaluate(()=>{
   const PAPER=[0xef,0xe5,0xcc]; // консервативно: бумага в тени края
   const parse=c=>{const m=c.match(/[\d.]+/g).map(Number);return m;};
   const lum=([r,g,b])=>{const f=v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4);};return .2126*f(r)+.7152*f(g)+.0722*f(b);};
   const cr=(a,b)=>{const x=lum(a),y=lum(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
   const op=el=>{let o=1;for(let e=el;e&&e!==document.body;e=e.parentElement||e.parentNode){const v=parseFloat(getComputedStyle(e).opacity);if(!isNaN(v))o*=v;}return o;};
   const rows=[];
   const sel=['#svg text','.selnote','.selnote li','.legend>span','.lens-toggle','.edition-note','.scene h1','.subtitle','.eyebrow'];
   document.querySelectorAll(sel.join(',')).forEach(el=>{
     const cs=getComputedStyle(el);const isSvg=el instanceof SVGElement;
     let c=parse(isSvg?cs.fill:cs.color);if(!c||c.length<3)return;
     const fo=isSvg?parseFloat(cs.fillOpacity||1):(c[3]??1);const o=op(el)*fo;
     const mix=c.slice(0,3).map((v,i)=>v*o+PAPER[i]*(1-o));
     const txt=(el.textContent||'').trim().slice(0,24);if(!txt)return;
     rows.push({t:txt,cls:(el.getAttribute('class')||el.tagName).slice(0,20),cr:+cr(mix,PAPER).toFixed(2),o:+o.toFixed(2)});
   });
   rows.sort((a,b)=>a.cr-b.cr);
   const ideas=getComputedStyle(document.querySelector('.folio')).getPropertyValue('--ideas').trim(),focus=getComputedStyle(document.querySelector('.folio')).getPropertyValue('--graph-focus').trim();
   return {ideas,focus,worst:rows.slice(0,8),below45:rows.filter(r=>r.cr<4.5).length,total:rows.length};
  });
 }
 console.log(JSON.stringify(out,null,1));await b.close();
})();
