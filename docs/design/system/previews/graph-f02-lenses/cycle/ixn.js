// Проверка интеракций desk.html: линзы и выбор. node ixn.js <tag>
const {chromium}=require('playwright-core');const path=require('path');
const URL='file://'+path.resolve('/root/ai-history-of-philosophy-platform/docs/design/system/previews/graph-f02-lenses/desk.html');
const OUT=__dirname+'/out/';const tag=process.argv[2]||'ixn';
(async()=>{
 const b=await chromium.launch({executablePath:'/root/.cache/puppeteer/chrome/linux-148.0.7778.97/chrome-linux64/chrome',args:['--no-sandbox']});
 const p=await b.newPage({viewport:{width:1440,height:1080}});const errs=[];p.on('pageerror',e=>errs.push(e.message));
 await p.goto(URL,{waitUntil:'networkidle'});await p.evaluate(()=>document.fonts.ready);await p.waitForTimeout(500);
 const R={},h=k=>p.evaluate(k=>{const b=window.deskLayout.bands[k];return Math.round(b.bot-b.top);},k);
 const all=()=>p.evaluate(()=>Object.fromEntries(Object.entries(window.deskLayout.bands).map(([k,b])=>[k,Math.round(b.bot-b.top)])));
 R.default={bands:await all(),sel:await p.evaluate(()=>desk.state.sel),note:(await p.locator('.selnote').innerText()).replace(/\n/g,' | ')};
 // линза «События мира»: развернуть → остальные отдают высоту
 await p.click('.lens-toggle[data-lens=events]');await p.waitForTimeout(300);
 R.eventsOn={bands:await all(),pressed:await p.getAttribute('.lens-toggle[data-lens=events]','aria-pressed'),rings:await p.locator('#svg .event-ring').count()};
 await p.screenshot({path:OUT+tag+'-events-on.png',fullPage:true});
 // линза «Труды»: свернуть → люди растут
 await p.click('.lens-toggle[data-lens=works]');await p.waitForTimeout(300);
 R.worksOff={bands:await all(),workMarks:await p.locator('#svg .work-mark').count()};
 await p.screenshot({path:OUT+tag+'-works-off.png',fullPage:true});
 await p.click('.lens-toggle[data-lens=works]');await p.click('.lens-toggle[data-lens=events]');await p.waitForTimeout(300);
 R.restored=await all();
 // выбор кликом: Декарт
 await p.click('#svg [data-person=descartes] .medallion-ring');await p.waitForTimeout(300);
 R.clickDescartes={sel:await p.evaluate(()=>desk.state.sel),pressed:await p.getAttribute('#svg [data-person=descartes]','aria-pressed'),note:(await p.locator('.selnote').innerText()).replace(/\n/g,' | '),h1:await p.locator('.scene h1').innerText()};
 await p.screenshot({path:OUT+tag+'-sel-descartes.png',fullPage:true});
 // клавиатура: фокус на Локке + Enter
 await p.focus('#svg [data-person=locke]');await p.keyboard.press('Enter');await p.waitForTimeout(300);
 R.keyLocke={sel:await p.evaluate(()=>desk.state.sel),focusKept:await p.evaluate(()=>document.activeElement.dataset.person)};
 // клик по полю → снять выбор
 const box=await p.locator('#svg').boundingBox();await p.mouse.click(box.x+box.width*.3,box.y+box.height*.93);await p.waitForTimeout(300);
 R.clickEmpty={sel:await p.evaluate(()=>desk.state.sel),note:(await p.locator('.selnote').innerText()).slice(0,40),dims:await p.locator('#svg .dim').count()};
 await p.screenshot({path:OUT+tag+'-none.png',fullPage:true});
 // Esc
 await p.evaluate(()=>desk.select('hume'));await p.keyboard.press('Escape');await p.waitForTimeout(200);
 R.esc=await p.evaluate(()=>desk.state.sel);
 // последнюю линзу выключить нельзя
 await p.evaluate(()=>{desk.state.on={events:false,eras:false,people:true,works:false};desk.draw();});await p.click('.lens-toggle[data-lens=people]');
 R.lastLensGuard=await p.evaluate(()=>desk.state.on.people);
 R.errors=errs;console.log(JSON.stringify(R,null,1));await b.close();
})();
