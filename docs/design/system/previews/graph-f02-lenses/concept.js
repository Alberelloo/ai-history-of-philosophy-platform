/* Hero-концепт раскладки «линзы»: статичная синхронологическая карта. Данные genesis + демо-эпохи/события. */
(function(){
  const SVG='http://www.w3.org/2000/svg';
  const W=1160, H=560;
  const PLOT_L=150, PLOT_R=W-26, PLOT_W=PLOT_R-PLOT_L;
  const Y0=1580, Y1=1812, SPAN=Y1-Y0;
  const X=y=>PLOT_L+(y-Y0)/SPAN*PLOT_W;

  // Страты (сверху вниз)
  const bands={
    events:{top:28, bot:92, label:'События мира'},
    eras:  {top:92, bot:150, label:'Контекст · эпохи'},
    people:{top:150, bot:404, label:'Люди'},
    works: {top:404, bot:516, label:'Труды и мысли'},
  };

  const people=[
    {id:'descartes', name:'Рене Декарт',   mono:'РД', birth:1596, death:1650, portrait:'descartes.jpg'},
    {id:'locke',     name:'Джон Локк',     mono:'ДЛ', birth:1632, death:1704, portrait:'locke.jpg'},
    {id:'hume',      name:'Дэвид Юм',      mono:'ДЮ', birth:1711, death:1776, portrait:'hume.jpg'},
    {id:'kant',      name:'Иммануил Кант', mono:'ИК', birth:1724, death:1804, portrait:'kant.jpg'},
  ];
  const lanes=people.length;
  const laneY=i=>bands.people.top+22+(i+0.5)*((bands.people.bot-bands.people.top-30)/lanes);
  people.forEach((p,i)=>{p.lane=i; p.cx=X(p.birth); p.cy=laneY(i);});
  const byId=Object.fromEntries(people.map(p=>[p.id,p]));

  const influences=[['descartes','locke'],['locke','hume'],['hume','kant']];

  const works=[
    {id:'essay',    title:'Опыт о человеческом разумении', year:1690, author:'locke'},
    {id:'enquiry',  title:'Исследование о человеческом познании', year:1748, author:'hume'},
    {id:'critique', title:'Критика чистого разума', year:1781, author:'kant'},
  ];
  const concepts=[{id:'causality', title:'Причинность', year:1739, author:'hume'}];

  const eras=[
    {label:'Научная революция', from:1600, to:1687},
    {label:'Просвещение', from:1687, to:1804},
  ];
  const events=[
    {year:1687, label:'«Начала» Ньютона'},
    {year:1751, label:'Энциклопедия'},
    {year:1789, label:'Французская революция'},
  ];

  const RX=20, RY=24;
  // пересечение луча из центра эллипса (cx,cy,rx,ry) в сторону (tx,ty) с контуром
  function ellipseAnchor(cx,cy,rx,ry,tx,ty){
    const dx=tx-cx, dy=ty-cy; if(!dx&&!dy)return{x:cx+rx,y:cy};
    const s=1/Math.sqrt((dx/rx)**2+(dy/ry)**2);
    return {x:cx+dx*s, y:cy+dy*s};
  }

  function el(tag,attrs,text){const e=document.createElementNS(SVG,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(text!=null)e.textContent=text;return e;}

  const svg=document.getElementById('svg');
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);

  // defs: дуотон портрета + клипы + стрелки
  const defs=el('defs',{});
  const f=el('filter',{id:'duo'});
  f.append(el('feColorMatrix',{type:'saturate',values:'0'}));
  const ct=el('feComponentTransfer',{});
  ct.append(el('feFuncR',{type:'table',tableValues:'.14 .94'}));
  ct.append(el('feFuncG',{type:'table',tableValues:'.18 .94'}));
  ct.append(el('feFuncB',{type:'table',tableValues:'.23 .90'}));
  f.append(ct); defs.append(f);
  people.forEach(p=>{const cp=el('clipPath',{id:'clip-'+p.id});cp.append(el('ellipse',{cx:p.cx,cy:p.cy,rx:RX,ry:RY}));defs.append(cp);});
  function marker(id,cls){const m=el('marker',{id,viewBox:'0 0 10 10',refX:'8',refY:'5',markerWidth:'7',markerHeight:'7',orient:'auto-start-reverse'});m.append(el('path',{d:'M0,0 L9,5 L0,10',fill:'none',stroke:'context-stroke','stroke-width':'1.4',class:cls}));return m;}
  const mI=el('marker',{id:'arrow-infl',viewBox:'0 0 10 10',refX:'8.5',refY:'5',markerWidth:'7.5',markerHeight:'7.5',orient:'auto-start-reverse'});
  mI.append(el('path',{d:'M0.5,1 L8.5,5 L0.5,9',fill:'none',stroke:'var(--genesis)','stroke-width':'1.3','stroke-linecap':'round','stroke-linejoin':'round'}));
  defs.append(mI);
  svg.append(defs);

  const gGrid=el('g',{}), gBands=el('g',{}), gEras=el('g',{}), gEvents=el('g',{}), gEdges=el('g',{}), gWorks=el('g',{}), gPeople=el('g',{}), gAxis=el('g',{});

  // Вертикальные тики времени (семантическая разлиновка вместо квадратов)
  for(let y=1600;y<=1800;y+=25){const x=X(y);gGrid.append(el('line',{x1:x,y1:bands.events.top,x2:x,y2:bands.works.bot,class:'time-grid'}));}

  // Полосы страт: разделители + подписи слева
  Object.values(bands).forEach(b=>{
    gBands.append(el('line',{x1:PLOT_L-6,y1:b.top,x2:PLOT_R,y2:b.top,class:'band-sep'}));
    gBands.append(el('text',{x:24,y:b.top+16,class:'band-label'},b.label));
  });
  gBands.append(el('line',{x1:PLOT_L-6,y1:bands.works.bot,x2:PLOT_R,y2:bands.works.bot,class:'band-sep'}));

  // Эпохи — пролёты-территории
  eras.forEach((e,i)=>{
    const x1=X(e.from), x2=X(e.to), y=bands.eras.top+30;
    gEras.append(el('rect',{x:x1,y:bands.eras.top+1,width:x2-x1,height:bands.eras.bot-bands.eras.top-2,fill:'var(--context)',class:'era-tint'}));
    gEras.append(el('path',{d:`M${x1+3},${y-6} L${x1+3},${y} L${x2-3},${y} L${x2-3},${y-6}`,class:'era-span'}));
    gEras.append(el('text',{x:(x1+x2)/2,y:y-10,class:'era-text'},e.label));
  });

  // События мира — кольца на году
  events.forEach(e=>{
    const x=X(e.year), y=bands.events.top+30;
    gEvents.append(el('circle',{cx:x,cy:y,r:6,class:'event-ring'}));
    gEvents.append(el('circle',{cx:x,cy:y,r:2.4,fill:'var(--history)',stroke:'none'}));
    gEvents.append(el('text',{x:x,y:y-13,class:'event-year','text-anchor':'middle'},e.year));
    gEvents.append(el('text',{x:x,y:y+22,class:'event-text','text-anchor':'middle'},e.label));
  });

  // Люди — линии жизни + медальоны
  people.forEach(p=>{
    const bx=X(p.birth), dx=X(p.death), y=p.cy;
    gPeople.append(el('line',{x1:bx,y1:y,x2:dx,y2:y,class:'lifeline'}));
    gPeople.append(el('line',{x1:dx,y1:y-5,x2:dx,y2:y+5,class:'life-cap'}));
    // медальон
    gPeople.append(el('ellipse',{cx:bx,cy:y,rx:RX,ry:RY,class:'medallion-ring'}));
    if(p.portrait){
      gPeople.append(el('image',{href:'../graph-f02/assets/'+p.portrait,x:bx-RX,y:y-RY,width:RX*2,height:RY*2,preserveAspectRatio:'xMidYMid slice','clip-path':'url(#clip-'+p.id+')',filter:'url(#duo)'}));
      gPeople.append(el('ellipse',{cx:bx,cy:y,rx:RX,ry:RY,fill:'none',stroke:'var(--people)','stroke-width':'1.25'}));
    } else {
      gPeople.append(el('text',{x:bx,y:y+6,class:'monogram'},p.mono));
    }
    gPeople.append(el('text',{x:bx+RX+8,y:y-2,class:'person-name'},p.name));
    gPeople.append(el('text',{x:bx+RX+8,y:y+13,class:'person-years'},`${p.birth}—${p.death}`));
  });

  // Влияния — монотонные кривые слева-направо, привязка к контуру эллипса
  influences.forEach(([a,b])=>{
    const s=byId[a], t=byId[b];
    const A=ellipseAnchor(s.cx,s.cy,RX,RY,t.cx,t.cy);
    const B=ellipseAnchor(t.cx,t.cy,RX,RY,s.cx,s.cy);
    const dx=(B.x-A.x);
    const c1x=A.x+dx*0.42, c2x=B.x-dx*0.42;
    gEdges.append(el('path',{d:`M${A.x},${A.y} C${c1x},${A.y} ${c2x},${B.y} ${B.x},${B.y}`,class:'influence','marker-end':'url(#arrow-infl)'}));
  });

  // Труды и понятия — марки на году, вертикальный коннектор авторства к линии жизни, подписи в 2 ряда
  const clip=(s,n)=>s.length>n?s.slice(0,n-1)+'…':s;
  const items=[...works.map(w=>({...w,kind:'work'})),...concepts.map(c=>({...c,kind:'concept'}))].sort((a,b)=>a.year-b.year);
  const my=bands.works.top+38;
  items.forEach((it,i)=>{
    const x=X(it.year), au=byId[it.author];
    // коннектор авторства: вверх к линии жизни автора в год труда (точка на линии жизни)
    if(au){
      const lx=Math.min(Math.max(x,X(au.birth)),X(au.death));
      gWorks.append(el('path',{d:`M${x},${my-11} C${x},${my-24} ${lx},${au.cy+RY+16} ${lx},${au.cy+RY+2}`,class:'authorship'}));
      gWorks.append(el('circle',{cx:lx,cy:au.cy+RY+2,r:1.6,fill:'var(--texts)'}));
    }
    // знак
    if(it.kind==='work'){
      gWorks.append(el('path',{d:`M${x-11},${my-9} L${x+6},${my-9} L${x+11},${my-4} L${x+11},${my+9} L${x-11},${my+9} Z`,class:'work-mark'}));
      gWorks.append(el('line',{x1:x-6,y1:my-3,x2:x+4,y2:my-3,stroke:'var(--texts)','stroke-width':'1'}));
      gWorks.append(el('line',{x1:x-6,y1:my+1,x2:x+4,y2:my+1,stroke:'var(--texts)','stroke-width':'1'}));
    } else {
      gWorks.append(el('path',{d:`M${x},${my-10} L${x+10},${my} L${x},${my+10} L${x-10},${my} Z`,class:'concept-mark'}));
    }
    // подпись — чередуем два ряда, чтобы не сталкивались
    const ty=my+(i%2?44:22), cls=it.kind==='work'?'work-title':'concept-title';
    gWorks.append(el('text',{x:x,y:ty,class:cls,'text-anchor':'middle'},clip(it.title,24)));
    gWorks.append(el('text',{x:x,y:ty+12,class:'work-year','text-anchor':'middle'},it.year));
  });

  // Шкала времени
  gAxis.append(el('line',{x1:PLOT_L-6,y1:bands.works.bot+16,x2:PLOT_R,y2:bands.works.bot+16,class:'time-tick'}));
  for(let y=1600;y<=1800;y+=50){const x=X(y);gAxis.append(el('line',{x1:x,y1:bands.works.bot+16,x2:x,y2:bands.works.bot+21,class:'time-tick'}));gAxis.append(el('text',{x:x,y:bands.works.bot+34,class:'time-text'},y));}

  [gGrid,gBands,gEras,gEvents,gEdges,gWorks,gPeople,gAxis].forEach(g=>svg.append(g));
})();
