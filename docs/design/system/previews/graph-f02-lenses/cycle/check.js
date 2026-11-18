// Прогон цикла: рендер desk.html + проверки корректности. node cycle.js <tag>
const {chromium}=require('playwright-core');const path=require('path');
const URL='file://'+path.resolve('/root/ai-history-of-philosophy-platform/docs/design/system/previews/graph-f02-lenses/desk.html');
const OUT=__dirname+'/out/';const tag=process.argv[2]||'run';
(async()=>{
 const b=await chromium.launch({executablePath:'/root/.cache/puppeteer/chrome/linux-148.0.7778.97/chrome-linux64/chrome',args:['--no-sandbox']});
 const report={};
 for(const [w,h] of [[1440,1080],[1280,900]]){
  const p=await b.newPage({viewport:{width:w,height:h}});const errs=[];
  p.on('pageerror',e=>errs.push('pageerror '+e.message));p.on('requestfailed',r=>errs.push('reqfail '+r.url()));
  p.on('console',m=>{if(m.type()==='error')errs.push('console '+m.text());});
  await p.goto(URL,{waitUntil:'networkidle'});
  await p.evaluate(async()=>{await document.fonts.load('20px "Bad Script"','Юм');await document.fonts.ready;});
  await p.waitForTimeout(600);
  for(const theme of ['light','dark']){
   await p.evaluate(t=>document.getElementById('app').dataset.theme=t,theme);await p.waitForTimeout(300);
   await p.screenshot({path:`${OUT}${tag}-${w}-${theme}.png`,fullPage:true});
  }
  if(w===1440){
   await p.evaluate(()=>document.getElementById('app').dataset.theme='light');await p.waitForTimeout(200);
   const r=await p.locator('.chart').boundingBox();
   const p2=await b.newPage({viewport:{width:w,height:h},deviceScaleFactor:2});
   await p2.goto(URL,{waitUntil:'networkidle'});await p2.evaluate(async()=>{await document.fonts.load('20px "Bad Script"','Юм');await document.fonts.ready;});await p2.waitForTimeout(600);
   await p2.screenshot({path:`${OUT}${tag}-chart-2x.png`,clip:{x:r.x,y:r.y,width:r.width,height:r.height},fullPage:true});await p2.close();
  }
  const geo=await p.evaluate(()=>{
   const R=e=>e.getBoundingClientRect();const inter=(a,b,m=0)=>a.left<b.right-m&&b.left<a.right-m&&a.top<b.bottom-m&&b.top<a.bottom-m;
   const texts=[...document.querySelectorAll('#svg text, .chart-notes text')].filter(t=>t.textContent.trim()&&getComputedStyle(t).opacity!=='0');
   const tt=[];for(let i=0;i<texts.length;i++)for(let j=i+1;j<texts.length;j++){if(inter(R(texts[i]),R(texts[j]),1))tt.push(texts[i].textContent.trim().slice(0,22)+' ✕ '+texts[j].textContent.trim().slice(0,22));}
   const lines=[...document.querySelectorAll('#svg line.lifeline, #svg .lifeline')];
   const tl=[];texts.forEach(t=>lines.forEach(l=>{if(l.closest('.person')&&l.closest('.person')===t.closest('.person'))return;/* имя и годы внутри своей ленты — по замыслу */if(inter(R(t),R(l),0.5))tl.push(t.textContent.trim().slice(0,22));}));
   return {fontBad:document.fonts.check('20px "Bad Script"','Юм'),hOverflow:document.documentElement.scrollWidth>innerWidth,textOverlaps:tt,textOnLifeline:[...new Set(tl)]};
  });
  report[w]={errors:errs,...geo};await p.close();
 }
 console.log(JSON.stringify(report,null,1));await b.close();
})();
