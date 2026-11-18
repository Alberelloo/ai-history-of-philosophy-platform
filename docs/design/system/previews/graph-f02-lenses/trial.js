/* Пробный кадр «линзы v2»: выбран Кант. Связи — светящиеся пучки с градиентом (без стрелок);
   труды и влияния подсвечены по-разному; «События мира» свёрнута; контекст приглушён. Статичный кадр. */
(function(){
  const SVG='http://www.w3.org/2000/svg';
  const W=1160,H=560,PLOT_L=150,PLOT_R=W-26,PLOT_W=PLOT_R-PLOT_L;
  const Y0=1580,Y1=1812,SPAN=Y1-Y0,X=y=>PLOT_L+(y-Y0)/SPAN*PLOT_W;

  // «События мира» свёрнута → тонкая лента, остальные линзы расширились
  const bands={
    events:{top:28,bot:54,label:'События мира',collapsed:true},
    eras:  {top:54,bot:112,label:'Контекст · эпохи'},
    people:{top:112,bot:384,label:'Люди'},
    works: {top:384,bot:506,label:'Труды и мысли'},
  };

  const SEL='kant';
  const people=[
    {id:'descartes',name:'Рене Декарт',   mono:'РД',birth:1596,death:1650,portrait:'descartes.jpg'},
    {id:'spinoza',  name:'Бенедикт Спиноза',mono:'БС',birth:1632,death:1677,portrait:null},
    {id:'locke',    name:'Джон Локк',     mono:'ДЛ',birth:1632,death:1704,portrait:'locke.jpg'},
    {id:'hume',     name:'Дэвид Юм',      mono:'ДЮ',birth:1711,death:1776,portrait:'hume.jpg'},
    {id:'kant',     name:'Иммануил Кант', mono:'ИК',birth:1724,death:1804,portrait:'kant.jpg'},
  ];
  const lanes=people.length;
  const laneY=i=>bands.people.top+26+(i+0.5)*((bands.people.bot-bands.people.top-38)/lanes);
  people.forEach((p,i)=>{p.lane=i;p.cx=X(p.birth);p.cy=laneY(i);});
  const byId=Object.fromEntries(people.map(p=>[p.id,p]));

  // цепочка влияний на Канта — подсвечена; descartes→spinoza — приглушённая (контекст)
  const influences=[
    {a:'descartes',b:'locke',active:true},
    {a:'locke',b:'hume',active:true},
    {a:'hume',b:'kant',active:true},
    {a:'descartes',b:'spinoza',active:false},
  ];
  const chain=new Set(['descartes','locke','hume','kant']);

  const works=[
    {id:'essay',title:'Опыт о человеческом разумении',year:1690,author:'locke',kind:'work'},
    {id:'causality',title:'Причинность',year:1739,author:'hume',kind:'concept'},
    {id:'enquiry',title:'Исследование о человеческом познании',year:1748,author:'hume',kind:'work'},
    {id:'critique',title:'Критика чистого разума',year:1781,author:'kant',kind:'work',active:true},
  ];
  const eras=[{label:'Научная революция',from:1600,to:1687},{label:'Просвещение',from:1687,to:1804}];
  const events=[{year:1687},{year:1751},{year:1789}];

  const RX=19,RY=23;
  const ellipseAnchor=(cx,cy,rx,ry,tx,ty)=>{const dx=tx-cx,dy=ty-cy;if(!dx&&!dy)return{x:cx+rx,y:cy};const s=1/Math.sqrt((dx/rx)**2+(dy/ry)**2);return{x:cx+dx*s,y:cy+dy*s};};
  const el=(t,a,txt)=>{const e=document.createElementNS(SVG,t);for(const k in a)e.setAttribute(k,a[k]);if(txt!=null)e.textContent=txt;return e;};
  const hash=s=>{let h=0;for(const c of s)h=(h*31+c.charCodeAt(0))|0;return h;};

  // кубика и касательная
  const cub=(P,t)=>{const u=1-t;return{x:u*u*u*P[0].x+3*u*u*t*P[1].x+3*u*t*t*P[2].x+t*t*t*P[3].x,y:u*u*u*P[0].y+3*u*u*t*P[1].y+3*u*t*t*P[2].y+t*t*t*P[3].y};};
  const tan=(P,t)=>{const u=1-t;return{x:3*u*u*(P[1].x-P[0].x)+6*u*t*(P[2].x-P[1].x)+3*t*t*(P[3].x-P[2].x),y:3*u*u*(P[1].y-P[0].y)+6*u*t*(P[2].y-P[1].y)+3*t*t*(P[3].y-P[2].y)};};
  function ribbon(P,w0,w1,N){N=N||26;const top=[],bot=[];for(let i=0;i<=N;i++){const t=i/N,p=cub(P,t),d=tan(P,t),len=Math.hypot(d.x,d.y)||1,nx=-d.y/len,ny=d.x/len,w=(w0*(1-t)+w1*t)/2;top.push([p.x+nx*w,p.y+ny*w]);bot.push([p.x-nx*w,p.y-ny*w]);}let d='M'+top[0][0].toFixed(1)+','+top[0][1].toFixed(1);for(let i=1;i<=N;i++)d+=' L'+top[i][0].toFixed(1)+','+top[i][1].toFixed(1);for(let i=N;i>=0;i--)d+=' L'+bot[i][0].toFixed(1)+','+bot[i][1].toFixed(1);return d+' Z';}
  const curve=P=>`M${P[0].x},${P[0].y} C${P[1].x},${P[1].y} ${P[2].x},${P[2].y} ${P[3].x},${P[3].y}`;

  const svg=document.getElementById('svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  const defs=el('defs',{});
  // дуотон портретов
  const duo=el('filter',{id:'duo'});duo.append(el('feColorMatrix',{type:'saturate',values:'0'}));const ct=el('feComponentTransfer',{});ct.append(el('feFuncR',{type:'table',tableValues:'.14 .94'}));ct.append(el('feFuncG',{type:'table',tableValues:'.18 .94'}));ct.append(el('feFuncB',{type:'table',tableValues:'.23 .90'}));duo.append(ct);defs.append(duo);
  // свечение (несколько проходов)
  const glow=el('filter',{id:'glow',x:'-60%',y:'-60%',width:'220%',height:'220%'});
  glow.append(el('feGaussianBlur',{in:'SourceGraphic',stdDeviation:'4',result:'b1'}));
  glow.append(el('feGaussianBlur',{in:'SourceGraphic',stdDeviation:'1.6',result:'b2'}));
  const fm=el('feMerge',{});fm.append(el('feMergeNode',{in:'b1'}));fm.append(el('feMergeNode',{in:'b2'}));fm.append(el('feMergeNode',{in:'SourceGraphic'}));glow.append(fm);defs.append(glow);
  people.forEach(p=>{const cp=el('clipPath',{id:'clip-'+p.id});cp.append(el('ellipse',{cx:p.cx,cy:p.cy,rx:RX,ry:RY}));defs.append(cp);});
  svg.append(defs);

  const gGrid=el('g',{}),gBands=el('g',{}),gEras=el('g',{}),gEvents=el('g',{}),
        gDim=el('g',{}),gThreads=el('g',{style:'isolation:isolate'}),gWorks=el('g',{}),gPeople=el('g',{}),gAxis=el('g',{});

  for(let y=1600;y<=1800;y+=25){const x=X(y);gGrid.append(el('line',{x1:x,y1:bands.events.top,x2:x,y2:bands.works.bot,class:'time-grid'}));}
  Object.values(bands).forEach(b=>{gBands.append(el('line',{x1:PLOT_L-6,y1:b.top,x2:PLOT_R,y2:b.top,class:'band-sep'}));gBands.append(el('text',{x:24,y:b.top+16,class:'band-label'+(b.collapsed?' ':''),'fill-opacity':b.collapsed?.75:1},b.label));});
  gBands.append(el('line',{x1:PLOT_L-6,y1:bands.works.bot,x2:PLOT_R,y2:bands.works.bot,class:'band-sep'}));

  // эпохи (контекст) — приглушённо
  eras.forEach(e=>{const x1=X(e.from),x2=X(e.to),y=bands.eras.top+34;gEras.append(el('rect',{x:x1,y:bands.eras.top+1,width:x2-x1,height:bands.eras.bot-bands.eras.top-2,fill:'var(--context)',class:'era-tint'}));gEras.append(el('path',{d:`M${x1+3},${y-6} L${x1+3},${y} L${x2-3},${y} L${x2-3},${y-6}`,class:'era-span'}));gEras.append(el('text',{x:(x1+x2)/2,y:y-10,class:'era-text'},e.label));});
  gEras.setAttribute('class','dim');
  // События мира — свёрнуты: только тонкие тики на ленте
  events.forEach(e=>{const x=X(e.year),y=(bands.events.top+bands.events.bot)/2+2;gEvents.append(el('circle',{cx:x,cy:y,r:3,class:'event-ring'}));gEvents.append(el('circle',{cx:x,cy:y,r:1.1,fill:'var(--history)'}));});
  gEvents.setAttribute('class','dim');

  // Приглушённые связи (не в фокусе)
  influences.filter(e=>!e.active).forEach(e=>{const s=byId[e.a],t=byId[e.b];const A=ellipseAnchor(s.cx,s.cy,RX,RY,t.cx,t.cy),B=ellipseAnchor(t.cx,t.cy,RX,RY,s.cx,s.cy);const dx=B.x-A.x;const P=[A,{x:A.x+dx*.42,y:A.y},{x:B.x-dx*.42,y:B.y},B];gDim.append(el('path',{d:curve(P),fill:'none',stroke:'var(--graph-ink-muted)','stroke-width':1.1,'stroke-opacity':.3,'stroke-linecap':'round'}));});

  // Активные влияния → светящиеся сужающиеся пучки с градиентом в киноварь
  influences.filter(e=>e.active).forEach((e,idx)=>{
    const s=byId[e.a],t=byId[e.b];
    const A=ellipseAnchor(s.cx,s.cy,RX,RY,t.cx,t.cy),B=ellipseAnchor(t.cx,t.cy,RX,RY,s.cx,s.cy);
    const dx=B.x-A.x,dy=B.y-A.y,len=Math.hypot(dx,dy)||1,nx=-dy/len,ny=dx/len;
    const j=((hash(e.a+e.b)%7)-3)/3; // лёгкий джиттер контрольной точки
    const off=len*0.10, bowx=len*0.42;
    const gid='grad-'+idx;
    const lg=el('linearGradient',{id:gid,gradientUnits:'userSpaceOnUse',x1:A.x,y1:A.y,x2:B.x,y2:B.y});
    lg.append(el('stop',{offset:'0%','stop-color':'var(--people)','stop-opacity':.85}));
    lg.append(el('stop',{offset:'60%','stop-color':'var(--graph-selected)','stop-opacity':.75}));
    lg.append(el('stop',{offset:'100%','stop-color':'var(--graph-selected)','stop-opacity':.95}));
    defs.append(lg);
    const P=[A,{x:A.x+bowx,y:A.y+nx*0+off*j+ (A.y)*0+ off*0.0},{x:B.x-bowx,y:B.y+off*j},B];
    // пряди пучка
    const g=el('g',{filter:'url(#glow)','mix-blend-mode':'multiply'});
    g.append(el('path',{d:ribbon(P,6.5,1.6),fill:'url(#'+gid+')','fill-opacity':.9}));
    const P2=[A,{x:A.x+bowx,y:A.y+nx*5+off*j},{x:B.x-bowx,y:B.y+nx*5+off*j},B];
    g.append(el('path',{d:curve(P2),fill:'none',stroke:'var(--graph-selected)','stroke-width':1,'stroke-opacity':.35,'stroke-linecap':'round'}));
    // светящиеся точки-искры вдоль пути (статично)
    [0.4,0.72].forEach(tt=>{const p=cub(P,tt);g.append(el('circle',{cx:p.x,cy:p.y,r:1.7,fill:'var(--graph-selected)','fill-opacity':.9}));});
    gThreads.append(g);
  });

  // Труды — марки; активный труд Канта подсвечен ИНАЧЕ (бирюзовое гало + тонкая нить), без вертикальных линий
  const items=[...works].sort((a,b)=>a.year-b.year);
  const clip=(s,n)=>s.length>n?s.slice(0,n-1)+'…':s;
  items.forEach((it,i)=>{
    const x=X(it.year),my=bands.works.top+40;
    const active=it.active;
    const node=el('g',active?{}:{class:'dim'});
    if(it.kind==='work'){node.append(el('path',{d:`M${x-11},${my-9} L${x+6},${my-9} L${x+11},${my-4} L${x+11},${my+9} L${x-11},${my+9} Z`,class:'work-mark',...(active?{'stroke-width':1.6}:{})}));node.append(el('line',{x1:x-6,y1:my-3,x2:x+4,y2:my-3,stroke:'var(--texts)','stroke-width':1}));node.append(el('line',{x1:x-6,y1:my+1,x2:x+4,y2:my+1,stroke:'var(--texts)','stroke-width':1}));}
    else{node.append(el('path',{d:`M${x},${my-10} L${x+10},${my} L${x},${my+10} L${x-10},${my} Z`,class:'concept-mark'}));}
    const ty=my+(i%2?44:22);
    node.append(el('text',{x,y:ty,class:active?'work-active-title':(it.kind==='work'?'work-title':'concept-title'),'text-anchor':'middle'},clip(it.title,24)));
    node.append(el('text',{x,y:ty+12,class:'work-year','text-anchor':'middle'},it.year));
    gWorks.append(node);
    if(active){
      // гало вокруг труда
      gWorks.append(el('circle',{cx:x,cy:my,r:17,fill:'none',stroke:'var(--texts)','stroke-width':2,'stroke-opacity':.5,filter:'url(#glow)'}));
      // мягкая нить к выбранной персоне (бирюзовая, тонкая, светящаяся — иной стиль, чем влияния)
      const au=byId[it.author];const A={x,y:my-11},B={x:au.cx,y:au.cy+RY};
      const P=[A,{x:A.x,y:A.y-28},{x:B.x,y:B.y+30},B];
      gWorks.append(el('path',{d:curve(P),fill:'none',stroke:'var(--texts)','stroke-width':1.6,'stroke-opacity':.85,'stroke-linecap':'round','stroke-dasharray':'1 5',filter:'url(#glow)'}));
    }
  });

  // Люди — линии жизни + медальоны (вне цепочки — приглушены)
  people.forEach(p=>{
    const bx=X(p.birth),dx=X(p.death),y=p.cy,inChain=chain.has(p.id),sel=p.id===SEL;
    const g=el('g',inChain?{}:{class:'dim'});
    g.append(el('line',{x1:bx,y1:y,x2:dx,y2:y,class:'lifeline',...(sel?{'stroke-opacity':.75,'stroke-width':2}:{})}));
    g.append(el('line',{x1:dx,y1:y-5,x2:dx,y2:y+5,class:'life-cap'}));
    if(sel){g.append(el('ellipse',{cx:bx,cy:y,rx:RX+4,ry:RY+4,fill:'none',stroke:'var(--graph-selected)','stroke-width':2,'stroke-opacity':.8,filter:'url(#glow)'}));}
    g.append(el('ellipse',{cx:bx,cy:y,rx:RX,ry:RY,class:'medallion-ring'}));
    if(p.portrait){g.append(el('image',{href:'../graph-f02/assets/'+p.portrait,x:bx-RX,y:y-RY,width:RX*2,height:RY*2,preserveAspectRatio:'xMidYMid slice','clip-path':'url(#clip-'+p.id+')',filter:'url(#duo)'}));g.append(el('ellipse',{cx:bx,cy:y,rx:RX,ry:RY,fill:'none',stroke:'var(--people)','stroke-width':1.25}));}
    else{g.append(el('text',{x:bx,y:y+6,class:'monogram'},p.mono));}
    g.append(el('text',{x:bx+RX+8,y:y-2,class:sel?'sel-name':'person-name'},p.name));
    g.append(el('text',{x:bx+RX+8,y:y+13,class:'person-years'},`${p.birth}—${p.death}`));
    gPeople.append(g);
  });

  // Шкала времени
  gAxis.append(el('line',{x1:PLOT_L-6,y1:bands.works.bot+16,x2:PLOT_R,y2:bands.works.bot+16,class:'time-tick'}));
  for(let y=1600;y<=1800;y+=50){const x=X(y);gAxis.append(el('line',{x1:x,y1:bands.works.bot+16,x2:x,y2:bands.works.bot+21,class:'time-tick'}));gAxis.append(el('text',{x,y:bands.works.bot+34,class:'time-text'},y));}

  [gGrid,gBands,gEras,gEvents,gDim,gThreads,gWorks,gPeople,gAxis].forEach(g=>svg.append(g));
})();
