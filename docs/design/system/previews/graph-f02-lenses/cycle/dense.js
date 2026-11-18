const {chromium}=require('playwright-core');const path=require('path');
const BASE='file://'+path.resolve('/root/ai-history-of-philosophy-platform/docs/design/system/previews/graph-f02-lenses/desk.html');
(async()=>{const b=await chromium.launch({executablePath:'/root/.cache/puppeteer/chrome/linux-148.0.7778.97/chrome-linux64/chrome',args:['--no-sandbox']});
const shots=[['demo','kant',false],['demo',null,false],['dense','kant',false],['dense',null,false],['dense','locke',true],['dense','hegel',false]];
for(const [ds,sel,ev] of shots){const p=await b.newPage({viewport:{width:1440,height:900}});const errs=[];p.on('pageerror',e=>errs.push(e.message));
 await p.goto(BASE+'?data='+ds,{waitUntil:'networkidle'});await p.evaluate(async()=>{await document.fonts.ready;});await p.waitForTimeout(300);
 await p.evaluate(([s,e])=>{if(e)desk.state.on.events=true;desk.select(s);},[sel,ev]);await p.waitForTimeout(350);
 const geo=await p.evaluate(()=>{const R=e=>e.getBoundingClientRect();const inter=(a,b,m=1)=>a.left<b.right-m&&b.left<a.right-m&&a.top<b.bottom-m&&b.top<a.bottom-m;
  const texts=[...document.querySelectorAll('#svg text')].filter(t=>t.textContent.trim());const tt=[];
  for(let i=0;i<texts.length;i++)for(let j=i+1;j<texts.length;j++)if(inter(R(texts[i]),R(texts[j])))tt.push(texts[i].textContent.slice(0,18)+' ✕ '+texts[j].textContent.slice(0,18));
  const lines=[...document.querySelectorAll('#svg .lifeline')];const tl=[];
  texts.forEach(t=>{if(t.closest('.person'))return;lines.forEach(l=>{if(inter(R(t),R(l),.5))tl.push(t.textContent.slice(0,20));});});
  return {lanes:deskLayout.lanes,labeled:deskLayout.labeledWorks,H:deskLayout.H,overlaps:tt,textOnLifeline:[...new Set(tl)],hOverflow:document.documentElement.scrollWidth>innerWidth};});
 console.log(ds,sel,ev?'+events':'',JSON.stringify(geo),errs);
 await p.screenshot({path:`out/v4-${ds}-${sel||'none'}${ev?'-ev':''}.png`,fullPage:true});await p.close();}
await b.close();})();
