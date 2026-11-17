/* Граф на рабочем листе сцены «стол философа». Статичный кадр: выбран Кант.
   Линии жизни — ленты Пристли (имя внутри ленты), влияния цепляются к лентам вне подписей,
   труды — значки книг с подписями без столкновений, ось — гравированная масштабная линейка. */
(function(){
  const NS='http://www.w3.org/2000/svg';
  const W=1160,H=566,PLOT_L=150,PLOT_R=W-26,PLOT_W=PLOT_R-PLOT_L;
  const Y0=1580,Y1=1812,X=y=>PLOT_L+(y-Y0)/(Y1-Y0)*PLOT_W;
  const bands={
    events:{top:28,bot:50,label:'События мира',collapsed:true},
    eras:  {top:50,bot:104,label:'Контекст · эпохи'},
    people:{top:104,bot:392,label:'Люди'},
    works: {top:392,bot:520,label:'Труды и мысли'},
  };
  const SEL='kant';
  const people=[
    {id:'descartes',lane:0,name:'Рене Декарт',     mono:'РД',birth:1596,death:1650,portrait:'descartes.jpg'},
    {id:'spinoza',lane:2,  name:'Бенедикт Спиноза',mono:'БС',birth:1632,death:1677,portrait:null},
    {id:'locke',lane:1,    name:'Джон Локк',       mono:'ДЛ',birth:1632,death:1704,portrait:'locke.jpg'},
    {id:'hume',lane:2,     name:'Дэвид Юм',        mono:'ДЮ',birth:1711,death:1776,portrait:'hume.jpg'},
    {id:'kant',lane:3,     name:'Иммануил Кант',   mono:'ИК',birth:1724,death:1804,portrait:'kant.jpg'},
  ];
  const chain=new Set(['descartes','locke','hume','kant']);
  const influences=[
    // via — год ключевого труда учителя: влияние идёт через труды, а не в момент смерти
    {a:'descartes',b:'locke',via:1637,active:true},{a:'locke',b:'hume',via:1690,active:true},
    {a:'hume',b:'kant',via:1748,active:true},{a:'descartes',b:'spinoza',via:1641,active:false},
  ];
  const works=[
    {id:'essay',title:'Опыт о человеческом разумении',year:1690,author:'locke',kind:'work'},
    {id:'causality',title:'Причинность',year:1739,author:'hume',kind:'concept'},
    {id:'enquiry',title:'Исследование о человеческом познании',year:1748,author:'hume',kind:'work'},
    {id:'critique',title:'Критика чистого разума',year:1781,author:'kant',kind:'work',active:true},
  ];
  const eras=[{label:'Научная революция',from:1600,to:1687},{label:'Просвещение',from:1687,to:1804}];
  const events=[{year:1687},{year:1751},{year:1789}];

  const RX=19,RY=23,BAND=20;
  const S=(t,a,txt)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(txt!=null)e.textContent=txt;return e;};
  const svg=document.getElementById('svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  // упаковка дорожек по Пристли: не пересекающиеся во времени жизни делят дорожку
  const LANES=Math.max(...people.map(p=>p.lane))+1;
  const laneY=i=>bands.people.top+24+(i+.5)*((bands.people.bot-bands.people.top-34)/LANES);
  people.forEach((p,i)=>{p.y=laneY(p.lane);p.bx=X(p.birth);p.dx=X(p.death);});
  const byId=Object.fromEntries(people.map(p=>[p.id,p]));

  /* ---------- defs ---------- */
  const defs=S('defs',{});
  const duo=S('filter',{id:'duo'});duo.append(S('feColorMatrix',{type:'saturate',values:'0'}));
  const ct=S('feComponentTransfer',{});[['R','.16 .95'],['G','.13 .92'],['B','.10 .84']].forEach(([c,v])=>ct.append(S('feFunc'+c,{type:'table',tableValues:v})));
  duo.append(ct);defs.append(duo);
  const glow=S('filter',{id:'glow',x:'-60%',y:'-60%',width:'220%',height:'220%'});
  glow.append(S('feGaussianBlur',{in:'SourceGraphic',stdDeviation:'2.6',result:'b'}));
  const fm=S('feMerge',{});fm.append(S('feMergeNode',{in:'b'}));fm.append(S('feMergeNode',{in:'SourceGraphic'}));glow.append(fm);defs.append(glow);
  people.forEach(p=>{const cp=S('clipPath',{id:'clip-'+p.id});cp.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX,ry:RY}));defs.append(cp);});
  svg.append(defs);

  const L={};['grid','bands','eras','events','bandsP','threads','works','people','axis','notes'].forEach(k=>{L[k]=S('g',{});svg.append(L[k]);});

  /* ---------- сетка времени и страты ---------- */
  for(let y=1600;y<=1800;y+=25){const x=X(y);L.grid.append(S('line',{x1:x,y1:bands.events.top,x2:x,y2:bands.works.bot,class:'time-grid'}));}
  ['events','eras','people','works'].forEach(k=>{const b=bands[k];
    L.bands.append(S('line',{x1:PLOT_L-6,y1:b.top,x2:PLOT_R,y2:b.top,class:'band-sep'}));
    L.bands.append(S('text',{x:24,y:b.top+(b.collapsed?15:17),class:'band-label','fill-opacity':b.collapsed?.7:1},b.label));});

  /* ---------- эпохи: фон-территории, не приглушаем ---------- */
  eras.forEach(e=>{const x1=X(e.from),x2=X(e.to),y=bands.eras.top+36;
    L.eras.append(S('rect',{x:x1,y:bands.eras.top+1,width:x2-x1,height:bands.eras.bot-bands.eras.top-2,fill:'var(--context)',opacity:.07}));
    L.eras.append(S('path',{d:`M${x1+3},${y-5} L${x1+3},${y} L${x2-3},${y} L${x2-3},${y-5}`,class:'era-span'}));
    L.eras.append(S('text',{x:(x1+x2)/2,y:y-9,class:'era-text'},e.label));});

  /* ---------- свёрнутая линза ---------- */
  const ey=(bands.events.top+bands.events.bot)/2;
  events.forEach(e=>{const x=X(e.year);L.events.append(S('path',{d:`M${x} ${ey-4} L${x+4} ${ey} L${x} ${ey+4} L${x-4} ${ey} Z`,fill:'var(--history)','fill-opacity':.45}));});
  L.events.append(S('text',{x:PLOT_L+4,y:ey+4,class:'collapsed-note'},'3 события · линза свёрнута'));

  /* ---------- люди: ленты Пристли ---------- */
  people.forEach(p=>{
    const sel=p.id===SEL,inC=chain.has(p.id);
    const g=S('g',inC?{}:{class:'dim'});
    g.append(S('rect',{x:p.bx,y:p.y-BAND/2,width:p.dx-p.bx,height:BAND,rx:BAND/2,fill:'var(--people)','fill-opacity':sel?.2:.12}));
    g.append(S('path',{d:`M${p.bx+RX} ${p.y+BAND/2-.5} H${p.dx-BAND/2}`,stroke:'var(--people)','stroke-opacity':sel?.45:.28,'stroke-width':1}));
    const name=S('text',{x:p.bx+RX+8,y:p.y+4.6,class:sel?'sel-name':'person-name'},p.name);g.append(name);
    const yrIn=p.dx+74>W-4;g.append(S('text',{x:yrIn?p.dx-12:p.dx+7,y:p.y+4,class:'person-years','text-anchor':yrIn?'end':'start'},`${p.birth}–${p.death}`));
    if(sel)g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX+4,ry:RY+4,fill:'none',stroke:'var(--graph-selected)','stroke-width':1.8,'stroke-opacity':.85,filter:'url(#glow)'}));
    g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX,ry:RY,class:'medallion-ring'}));
    if(p.portrait){g.append(S('image',{href:'../graph-f02/assets/'+p.portrait,x:p.bx-RX,y:p.y-RY,width:RX*2,height:RY*2,preserveAspectRatio:'xMidYMid slice','clip-path':`url(#clip-${p.id})`,filter:'url(#duo)'}));
                   g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX,ry:RY,fill:'none',stroke:'var(--people)','stroke-width':1.2}));}
    else g.append(S('text',{x:p.bx,y:p.y+6,class:'monogram'},p.mono));
    L.people.append(g);
    p.labelEnd=p.bx+RX+8+name.getComputedTextLength();
  });

  /* ---------- влияния: от ленты учителя к ленте ученика, вне подписей ---------- */
  const cub=(P,t)=>{const u=1-t;return{x:u*u*u*P[0].x+3*u*u*t*P[1].x+3*u*t*t*P[2].x+t*t*t*P[3].x,y:u*u*u*P[0].y+3*u*u*t*P[1].y+3*u*t*t*P[2].y+t*t*t*P[3].y};};
  const tan=(P,t)=>{const u=1-t;return{x:3*u*u*(P[1].x-P[0].x)+6*u*t*(P[2].x-P[1].x)+3*t*t*(P[3].x-P[2].x),y:3*u*u*(P[1].y-P[0].y)+6*u*t*(P[2].y-P[1].y)+3*t*t*(P[3].y-P[2].y)};};
  const ribbon=(P,w0,w1,N=28)=>{const a=[],b=[];for(let i=0;i<=N;i++){const t=i/N,p=cub(P,t),d=tan(P,t),l=Math.hypot(d.x,d.y)||1,nx=-d.y/l,ny=d.x/l,w=(w0*(1-t)+w1*t)/2;a.push(`${(p.x+nx*w).toFixed(1)},${(p.y+ny*w).toFixed(1)}`);b.unshift(`${(p.x-nx*w).toFixed(1)},${(p.y-ny*w).toFixed(1)}`);}return 'M'+a.join(' L')+' L'+b.join(' L')+' Z';};
  window.deskLayout={people:byId,threads:{}};
  influences.forEach((e,i)=>{
    const s=byId[e.a],t=byId[e.b];
    const A={x:Math.min(Math.max(X(e.via),s.labelEnd+10),s.dx-8),y:s.y+BAND/2};
    const B={x:Math.min(Math.max(X(t.birth+22),t.labelEnd+14),t.dx-10),y:t.y-BAND/2};
    const dx=B.x-A.x,dy=B.y-A.y;
    // уход по касательной, приход круто сверху — нить не задевает подпись ученика
    const P=[A,{x:A.x+dx*.5,y:A.y+dy*.15},{x:B.x-dx*.15,y:B.y-dy*.65},B];
    window.deskLayout.threads[e.a+'-'+e.b]=cub(P,.5);
    const d=`M${A.x},${A.y} C${P[1].x},${P[1].y} ${P[2].x},${P[2].y} ${B.x},${B.y}`;
    if(!e.active){L.threads.append(S('path',{d,fill:'none',stroke:'var(--graph-ink-muted)','stroke-opacity':.5,'stroke-width':1,'stroke-dasharray':'2 3','stroke-linecap':'round'}));return;}
    const gid='dg'+i,lg=S('linearGradient',{id:gid,gradientUnits:'userSpaceOnUse',x1:A.x,y1:A.y,x2:B.x,y2:B.y});
    lg.append(S('stop',{offset:'0%','stop-color':'var(--people)','stop-opacity':.75}));
    lg.append(S('stop',{offset:'100%','stop-color':'var(--graph-selected)','stop-opacity':.95}));defs.append(lg);
    const g=S('g',{filter:'url(#glow)'});
    // пряди-спутники: пучок, а не одиночная линия
    [[2.6,-2.2],[-2.2,2.6]].forEach(([ox,oy])=>g.append(S('path',{d:`M${A.x},${A.y} C${P[1].x+ox},${P[1].y+oy} ${P[2].x+ox},${P[2].y+oy} ${B.x},${B.y}`,fill:'none',stroke:`url(#${gid})`,'stroke-width':.6,'stroke-opacity':.45})));
    g.append(S('path',{d:ribbon(P,4.6,1.3),fill:`url(#${gid})`}));
    [.36,.64].forEach(tt=>{const q=cub(P,tt);g.append(S('circle',{cx:q.x,cy:q.y,r:1.4,fill:'#fff3e0','fill-opacity':.9}));});
    g.append(S('circle',{cx:A.x,cy:A.y,r:2.2,fill:'var(--people)'}));
    g.append(S('circle',{cx:B.x,cy:B.y,r:2.6,fill:'var(--graph-selected)'}));
    L.threads.append(g);
  });

  /* ---------- контекст выбранного: подсветка эпохи без линий ---------- */
  const selP=byId[SEL],mid=(selP.birth+selP.death)/2,era=eras.find(e=>mid>=e.from&&mid<e.to);
  if(era){const x1=X(era.from),x2=X(era.to);
    L.eras.insertBefore(S('rect',{x:x1,y:bands.eras.top+1,width:x2-x1,height:bands.eras.bot-bands.eras.top-2,fill:'var(--context)',opacity:.12}),L.eras.firstChild);
    [...L.eras.querySelectorAll('text')].forEach(t=>{if(t.textContent===era.label)t.setAttribute('class','era-text era-active');});
    L.eras.append(S('path',{d:`M${selP.bx} ${bands.eras.bot-2} V${bands.eras.bot+6}`,stroke:'var(--context)','stroke-opacity':.5,'stroke-width':1,'stroke-dasharray':'1 3'}));}

  /* ---------- труды: значки, подписи без столкновений ---------- */
  const my=bands.works.top+36,rowsEnd=[[],[]];
  const items=[...works].sort((a,b)=>a.year-b.year);
  items.forEach(it=>{
    const x=X(it.year),au=byId[it.author];
    const g=S('g',it.active?{}:{class:'dim-soft'});
    if(it.kind==='work'){
      g.append(S('rect',{x:x-9,y:my-11,width:18,height:22,rx:1.5,class:'work-mark',...(it.active?{'stroke-width':1.6}:{})}));
      g.append(S('rect',{x:x-9,y:my-11,width:4.5,height:22,rx:1.2,fill:'var(--texts)','fill-opacity':.55}));
      g.append(S('path',{d:`M${x-1} ${my-4} h6 M${x-1} ${my} h6`,stroke:'var(--texts)','stroke-width':1,'stroke-opacity':.8}));
    } else {
      g.append(S('path',{d:`M${x} ${my-10} L${x+10} ${my} L${x} ${my+10} L${x-10} ${my} Z`,class:'concept-mark'}));
      g.append(S('circle',{cx:x,cy:my,r:2,fill:'var(--ideas)'}));
    }
    g.append(it.active?S('text',{x:x+25,y:my+4,class:'work-year','text-anchor':'start'},it.year):S('text',{x,y:my-21,class:'work-year','text-anchor':'middle'},it.year));
    // подпись: перенос в 2 строки по ширине 124
    const t=S('text',{x,class:it.active?'work-active-title':(it.kind==='work'?'work-title':'concept-title'),'text-anchor':'middle'});g.append(t);
    L.works.append(g);
    const words=it.title.split(' '),lines=[''];
    words.forEach(w=>{const cand=(lines[lines.length-1]+' '+w).trim();t.textContent=cand;if(t.getComputedTextLength()>150&&lines[lines.length-1])lines.push(w);else lines[lines.length-1]=cand;});
    t.textContent='';let maxW=0;
    lines.forEach((ln,k)=>{const sp=S('tspan',{x,dy:k?13:0},ln);t.append(sp);});
    maxW=t.getBBox().width;
    const x0=x-maxW/2-6,x1=x+maxW/2+6;
    const row=rowsEnd[0].every(([a,b])=>x1<a||x0>b)?0:1;rowsEnd[row].push([x0,x1]);
    t.setAttribute('y',my+28+row*34);[...t.children].forEach((sp,k)=>{if(!k)sp.setAttribute('y',my+28+row*34);});
    it.x=x;it.my=my;it.titleBox=t;
    if(it.active){
      L.works.insertBefore(S('circle',{cx:x,cy:my,r:15.5,fill:'none',stroke:'var(--texts)','stroke-width':1.8,'stroke-opacity':.5,filter:'url(#glow)'}),g);
      const A={x:Math.min(Math.max(x-28,au.labelEnd+10),au.dx-10),y:au.y+BAND/2},B={x,y:my-13};
      L.threads.append(S('path',{d:`M${A.x},${A.y} C${A.x},${A.y+22} ${B.x},${B.y-22} ${B.x},${B.y}`,fill:'none',stroke:'var(--texts)','stroke-width':1.5,'stroke-opacity':.85,'stroke-dasharray':'1 4','stroke-linecap':'round',filter:'url(#glow)'}));
    }
  });

  /* ---------- ось: гравированная масштабная линейка ---------- */
  const ay=bands.works.bot;
  L.axis.append(S('line',{x1:PLOT_L-6,y1:ay,x2:PLOT_R,y2:ay,stroke:'var(--graph-ink)','stroke-opacity':.55,'stroke-width':.8}));
  L.axis.append(S('line',{x1:X(1600),y1:ay+5,x2:X(1800),y2:ay+5,stroke:'var(--graph-ink)','stroke-opacity':.55,'stroke-width':.8}));
  for(let y=1600,k=0;y<1800;y+=25,k++){if(k%2===0)L.axis.append(S('rect',{x:X(y),y:ay,width:X(y+25)-X(y),height:5,fill:'var(--graph-ink)','fill-opacity':.5}));}
  for(let y=1600;y<=1800;y+=25){const x=X(y),maj=y%50===0;L.axis.append(S('line',{x1:x,y1:ay,x2:x,y2:ay+(maj?9:5),stroke:'var(--graph-ink)','stroke-opacity':.55,'stroke-width':.8}));
    if(maj)L.axis.append(S('text',{x,y:ay+24,class:'axis-year'},y));}

  /* ---------- рукописные пометки философа (от вычисленной раскладки) ---------- */
  const hand=(x,y,s,txt,rot)=>L.notes.append(S('text',{x,y,class:'hand','font-size':s,transform:`rotate(${rot} ${x} ${y})`},txt));
  const hs=(d)=>L.notes.append(S('path',{d,class:'hand-stroke'}));
  hand(838,170,19,'«Юм пробудил меня',-3);hand(852,197,19,'от догматического сна»',-3);hand(958,222,14,'— Кант, 1783',-3);
  const m=window.deskLayout.threads['hume-kant'];
  hs(`M${910} ${232} C${906} ${262} ${m.x+20} ${m.y-30} ${m.x+5} ${m.y-8}`);hs(`M${m.x+1} ${m.y-19} L${m.x+5} ${m.y-7} L${m.x+15} ${m.y-15}`);
  const sp=byId.spinoza;L.notes.append(S('text',{x:sp.bx-30,y:sp.y+5,class:'hand','font-size':15,'text-anchor':'end',transform:`rotate(-4 ${sp.bx-30} ${sp.y+5})`},'а Спиноза? →'));
  hand(178,bands.works.top+52,18,'Опыт или разум?',-2);hand(196,bands.works.top+78,16,'— вот спор целой эпохи',-2);
  const cr=items.find(i=>i.active),bb=cr.titleBox.getBBox();hs(`M${bb.x-4} ${bb.y+bb.height+4} Q${bb.x+bb.width/2} ${bb.y+bb.height+9} ${bb.x+bb.width+6} ${bb.y+bb.height+2}`);
})();
