const {chromium}=require('playwright-core');const path=require('path');
const BASE='file://'+path.resolve('/root/ai-history-of-philosophy-platform/docs/design/system/previews/graph-f02-lenses/desk.html');
const frames=(process.argv[2]||'').split(';').filter(Boolean);
(async()=>{const b=await chromium.launch({executablePath:'/root/.cache/puppeteer/chrome/linux-148.0.7778.97/chrome-linux64/chrome',args:['--no-sandbox']});
for(const fr of frames){const [name,qs]=fr.split('=');const p=await b.newPage({viewport:{width:1440,height:900}});const errs=[];p.on('pageerror',e=>errs.push(e.message));
 await p.goto(BASE+'?'+qs.replace(/!/g,'='),{waitUntil:'networkidle'});await p.evaluate(()=>document.fonts.ready);await p.waitForTimeout(400);
 const geo=await p.evaluate(()=>{const R=e=>e.getBoundingClientRect();const inter=(a,b,m=1)=>a.left<b.right-m&&b.left<a.right-m&&a.top<b.bottom-m&&b.top<a.bottom-m;
  const texts=[...document.querySelectorAll('#svg text')].filter(t=>t.textContent.trim());const tt=[];
  for(let i=0;i<texts.length;i++)for(let j=i+1;j<texts.length;j++)if(inter(R(texts[i]),R(texts[j])))tt.push(texts[i].textContent.slice(0,18)+' ✕ '+texts[j].textContent.slice(0,18));
  const lines=[...document.querySelectorAll('#svg .lifeline')];const tl=[];
  texts.forEach(t=>lines.forEach(l=>{if(l.closest('.person')===t.closest('.person'))return;if(inter(R(t),R(l),.5))tl.push(t.textContent.slice(0,20));}));
  const L=deskLayout;return {lanes:L.lanes,works:L.labeledWorks,events:L.labeledEvents,H:Math.round(L.H),overlaps:tt.slice(0,6),onLife:[...new Set(tl)].slice(0,6),hOver:document.documentElement.scrollWidth>innerWidth};});
 console.log(name,JSON.stringify(geo),errs.join('|'));await p.screenshot({path:`out/v5-${name}.png`,fullPage:true});await p.close();}
await b.close();})();
