/* Граф на рабочем листе сцены «стол философа». Рендер от состояния:
   линзы (страты сворачиваются, остальные забирают высоту) и выбранный философ
   (влияния — киноварный поток, труды — бирюзовая нить, эпоха — подсветка без линий). */
(function(){
  const NS='http://www.w3.org/2000/svg';
  // Ширина и высота графа — в реальных пикселях листа (не масштабированный viewBox):
  // шире лист — больше места на годы, а не крупнее шрифт. Пересчёт при resize.
  let W=1160,PLOT_R=W-26,BODY=500;const PLOT_L=150,TOP=28,AXIS_H=50,COLL=28;
  const Y0=1580,Y1=1812,X=y=>PLOT_L+(y-Y0)/(Y1-Y0)*(PLOT_R-PLOT_L);
  const ORDER=['events','eras','people','works'];
  const META={
    events:{label:'События',w:.10,max:90,count:'3 события'},
    eras:{label:'Эпохи',w:.11,max:80,count:'2 эпохи'},
    people:{label:'Люди',w:.52,max:9999,count:'5 философов'},
    works:{label:'Труды',w:.27,max:210,count:'4 труда'},
  };
  const state={sel:'kant',on:{events:false,eras:true,people:true,works:true}};

  const people=[
    {id:'descartes',lane:0,name:'Рене Декарт',     short:'Декарт', mono:'РД',birth:1596,death:1650,portrait:'descartes.jpg'},
    {id:'locke',    lane:1,name:'Джон Локк',       short:'Локк',   mono:'ДЛ',birth:1632,death:1704,portrait:'locke.jpg'},
    {id:'spinoza',  lane:2,name:'Бенедикт Спиноза',short:'Спиноза',mono:'БС',birth:1632,death:1677,portrait:null},
    {id:'hume',     lane:2,name:'Дэвид Юм',        short:'Юм',     mono:'ДЮ',birth:1711,death:1776,portrait:'hume.jpg'},
    {id:'kant',     lane:3,name:'Иммануил Кант',   short:'Кант',   mono:'ИК',birth:1724,death:1804,portrait:'kant.jpg'},
  ];
  const byId=Object.fromEntries(people.map(p=>[p.id,p]));
  // via — год ключевого труда учителя: влияние идёт через труды
  const influences=[{a:'descartes',b:'locke',via:1637},{a:'locke',b:'hume',via:1690},{a:'hume',b:'kant',via:1748},{a:'descartes',b:'spinoza',via:1641}];
  const works=[
    {id:'essay',title:'Опыт о человеческом разумении',year:1690,author:'locke',kind:'work'},
    {id:'causality',title:'Причинность',year:1739,author:'hume',kind:'concept'},
    {id:'enquiry',title:'Исследование о человеческом познании',year:1748,author:'hume',kind:'work'},
    {id:'critique',title:'Критика чистого разума',year:1781,author:'kant',kind:'work'},
  ];
  // Пометки на полях — данные (цитата + источник), а не текст макета: у каждой есть «про что» —
  // связь (a-b) или персона. Показывается одна, про выбранного; нет места на листе — уходит в сноску.
  const notes=[
    {about:'hume-kant',lines:['«…впервые прервало мою','догматическую дремоту»'],cite:'Кант о Юме, «Пролегомены», 1783'},
    {about:'descartes',lines:['«Я мыслю, следовательно,','я существую»'],cite:'«Рассуждение о методе», 1637'},
    {about:'locke',lines:['«…ум есть, так сказать,','белая бумага без всяких знаков»'],cite:'«Опыт…», кн. II, гл. 1'},
    {about:'hume',lines:['«Разум есть и должен быть','лишь рабом аффектов»'],cite:'«Трактат о человеческой природе»'},
    {about:'spinoza',lines:['«Порядок и связь идей те же,','что порядок и связь вещей»'],cite:'«Этика», ч. II, теор. 7'},
  ];
  const theme=['Опыт или разум?','— вот спор целой эпохи'];  // тема листа — только на карточке на столе, не на графе
  // карточки на столе: главный вопрос выбранного (редакторская выжимка, не цитата)
  const questions={
    descartes:['Что можно знать','несомненно?','— путь сомнения'],
    locke:['Откуда берутся','наши идеи?','— только из опыта'],
    spinoza:['Как связаны','мышление и протяжение?','— одна субстанция'],
    hume:['Откуда мы знаем','о причинах?','— из привычки'],
    kant:['Что я могу знать?','Что я должен делать?','На что смею надеяться?'],
  };
  const eras=[{label:'Научная революция',from:1600,to:1687},{label:'Просвещение',from:1687,to:1804}];
  const events=[{year:1687,label:'«Начала» Ньютона'},{year:1751,label:'Энциклопедия'},{year:1789,label:'Французская революция'}];

  const RX=22,RY=27,BAND=24;
  const S=(t,a,txt)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(txt!=null)e.textContent=txt;return e;};
  const cub=(P,t)=>{const u=1-t;return{x:u*u*u*P[0].x+3*u*u*t*P[1].x+3*u*t*t*P[2].x+t*t*t*P[3].x,y:u*u*u*P[0].y+3*u*u*t*P[1].y+3*u*t*t*P[2].y+t*t*t*P[3].y};};
  const tan=(P,t)=>{const u=1-t;return{x:3*u*u*(P[1].x-P[0].x)+6*u*t*(P[2].x-P[1].x)+3*t*t*(P[3].x-P[2].x),y:3*u*u*(P[1].y-P[0].y)+6*u*t*(P[2].y-P[1].y)+3*t*t*(P[3].y-P[2].y)};};
  const ribbon=(P,w0,w1,N=28)=>{const a=[],b=[];for(let i=0;i<=N;i++){const t=i/N,p=cub(P,t),d=tan(P,t),l=Math.hypot(d.x,d.y)||1,nx=-d.y/l,ny=d.x/l,w=(w0*(1-t)+w1*t)/2;a.push(`${(p.x+nx*w).toFixed(1)},${(p.y+ny*w).toFixed(1)}`);b.unshift(`${(p.x-nx*w).toFixed(1)},${(p.y-ny*w).toFixed(1)}`);}return 'M'+a.join(' L')+' L'+b.join(' L')+' Z';};

  const svg=document.getElementById('svg');
  const gutter=document.querySelector('.gutter'),selnote=document.querySelector('.selnote');
  const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;

  function layoutBands(){
    const on=ORDER.filter(k=>state.on[k]),free=BODY-(ORDER.length-on.length)*COLL,sw=on.reduce((a,k)=>a+META[k].w,0),h={};
    ORDER.forEach(k=>h[k]=state.on[k]?Math.min(META[k].max,free*META[k].w/sw):COLL);
    if(state.on.works)h.works=Math.max(h.works,136);  // две строки названий в два ряда — не налезают на шкалу
    if(state.on.people)h.people+=BODY-ORDER.reduce((a,k)=>a+h[k],0);
    let y=TOP;const b={};ORDER.forEach(k=>{b[k]={key:k,top:y,bot:y+h[k],collapsed:!state.on[k],...META[k]};y+=h[k];});return b;
  }
  // что связано с выбранным: вверх по цепочке влияний + его ученики, его труды, его эпоха
  function related(){
    const sel=state.sel;if(!sel)return null;
    const up=new Set([sel]);let ch=true;while(ch){ch=false;influences.forEach(e=>{if(up.has(e.b)&&!up.has(e.a)){up.add(e.a);ch=true;}});}
    const down=influences.filter(e=>e.a===sel).map(e=>e.b);
    const edges=new Set(influences.filter(e=>(up.has(e.a)&&up.has(e.b))||e.a===sel).map(e=>e.a+'-'+e.b));
    const p=byId[sel],mid=(p.birth+p.death)/2;
    return {up,down,edges,people:new Set([...up,...down]),works:new Set(works.filter(w=>w.author===sel).map(w=>w.id)),era:eras.find(e=>mid>=e.from&&mid<e.to)};
  }

  function draw(){
    const ae=document.activeElement,focusId=ae&&ae.dataset?ae.dataset.person:null;
    svg.innerHTML='';
    const cw=Math.round(svg.getBoundingClientRect().width)||1160;W=Math.max(900,cw);PLOT_R=W-26;
    const top=svg.getBoundingClientRect().top+scrollY;BODY=Math.round(Math.min(760,Math.max(440,innerHeight-top-AXIS_H-TOP-96)));
    if(gutter)gutter.style.width=PLOT_L+'px';
    const bands=layoutBands(),H=bands.works.bot+AXIS_H,R=related();
    svg.setAttribute('viewBox',`0 0 ${W} ${H}`);

    const defs=S('defs',{});
    const duo=S('filter',{id:'duo'});duo.append(S('feColorMatrix',{type:'saturate',values:'0'}));
    const ct=S('feComponentTransfer',{});[['R','.16 .95'],['G','.13 .92'],['B','.10 .84']].forEach(([c,v])=>ct.append(S('feFunc'+c,{type:'table',tableValues:v})));duo.append(ct);defs.append(duo);
    const glow=S('filter',{id:'glow',x:'-60%',y:'-60%',width:'220%',height:'220%'});
    glow.append(S('feGaussianBlur',{in:'SourceGraphic',stdDeviation:'2.6',result:'b'}));
    const fm=S('feMerge',{});fm.append(S('feMergeNode',{in:'b'}));fm.append(S('feMergeNode',{in:'SourceGraphic'}));glow.append(fm);defs.append(glow);
    svg.append(defs);
    const L={};['grid','bands','eras','events','threads','works','people','axis','notes'].forEach(k=>{L[k]=S('g',{});svg.append(L[k]);});
    const isDim=on=>R&&!on;

    /* сетка времени и границы страт */
    for(let y=1600;y<=1800;y+=25){const x=X(y);L.grid.append(S('line',{x1:x,y1:TOP,x2:x,y2:bands.works.bot,class:'time-grid'}));}
    ORDER.forEach(k=>{const b=bands[k];L.bands.append(S('line',{x1:PLOT_L-6,y1:b.top,x2:PLOT_R,y2:b.top,class:'band-sep'}));
      if(b.collapsed)L.bands.append(S('text',{x:PLOT_L+4,y:b.top+18,class:'collapsed-note'},`${b.count} · линза свёрнута`));});

    /* люди: геометрия заранее (нужна эпохам и связям) */
    const bp=bands.people,LANES=Math.max(...people.map(p=>p.lane))+1;
    people.forEach(p=>{p.bx=X(p.birth);p.dx=X(p.death);p.y=bp.top+24+(p.lane+.5)*((bp.bot-bp.top-34)/LANES);});

    /* эпохи */
    const be=bands.eras;
    if(!be.collapsed){eras.forEach(e=>{const x1=X(e.from),x2=X(e.to),act=R&&R.era===e,y=be.bot-Math.min(16,(be.bot-be.top)*.32);
      L.eras.append(S('rect',{x:x1,y:be.top+1,width:x2-x1,height:be.bot-be.top-2,fill:'var(--context)',opacity:act?.13:.07}));
      L.eras.append(S('path',{d:`M${x1+3},${y-5} L${x1+3},${y} L${x2-3},${y} L${x2-3},${y-5}`,class:'era-span'}));
      L.eras.append(S('text',{x:(x1+x2)/2,y:y-9,class:'era-text'+(act?' era-active':'')},e.label));});
      if(R&&R.era&&!bp.collapsed){const p=byId[state.sel];L.eras.append(S('path',{d:`M${p.bx} ${be.bot-2} V${be.bot+6}`,stroke:'var(--context)','stroke-opacity':.5,'stroke-width':1,'stroke-dasharray':'1 3'}));}}
    else eras.forEach(e=>L.eras.append(S('rect',{x:X(e.from),y:be.top+COLL-6,width:X(e.to)-X(e.from)-2,height:3,fill:'var(--context)',opacity:.35})));

    /* события мира */
    const bv=bands.events;
    events.forEach(e=>{const x=X(e.year);
      if(bv.collapsed){const y=(bv.top+bv.bot)/2;L.events.append(S('path',{d:`M${x} ${y-4} L${x+4} ${y} L${x} ${y+4} L${x-4} ${y} Z`,fill:'var(--history)','fill-opacity':.45}));return;}
      const y=bv.top+(bv.bot-bv.top)*.5;
      L.events.append(S('circle',{cx:x,cy:y,r:5.5,class:'event-ring'}));L.events.append(S('circle',{cx:x,cy:y,r:2,fill:'var(--history)'}));
      const yt=S('text',{x:x+11,y:y-2,class:'event-year'},e.year),lt=S('text',{x:x+11,y:y+11,class:'event-text'},e.label);L.events.append(yt);L.events.append(lt);
      // подпись прижимается к правому полю и уходит под кольцо — не за край листа и не на соседа
      const lw=lt.getComputedTextLength(),lx=Math.min(x+11,PLOT_R-lw);if(lx<x+11){lt.setAttribute('x',lx);lt.setAttribute('y',y+17);}});

    /* люди: ленты Пристли */
    if(bp.collapsed){people.forEach(p=>L.people.append(S('rect',{x:p.bx,y:bp.top+COLL-7,width:p.dx-p.bx,height:3,rx:1.5,fill:'var(--people)',opacity:.35})));}
    else people.forEach(p=>{
      const sel=p.id===state.sel,on=!R||R.people.has(p.id);
      const g=S('g',{class:'person'+(isDim(on)?' dim':''),'data-person':p.id,tabindex:0,role:'button','aria-pressed':String(sel),'aria-label':`${p.name}, ${p.birth}–${p.death}`});L.people.append(g);
      g.append(S('rect',{x:p.bx,y:p.y-BAND/2,width:p.dx-p.bx,height:BAND,rx:BAND/2,fill:sel?'var(--graph-selected)':'var(--graph-ink-secondary)','fill-opacity':sel?.12:.1}));
      g.append(S('path',{d:`M${p.bx+RX} ${p.y+BAND/2-.5} H${p.dx-BAND/2}`,stroke:sel?'var(--graph-selected)':'var(--graph-ink-secondary)','stroke-opacity':sel?.45:.25,'stroke-width':1}));
      const name=S('text',{x:p.bx+RX+8,y:p.y+5.4,class:sel?'sel-name':'person-name'},p.name);g.append(name);
      const yr=S('text',{x:p.dx+7,y:p.y+4.5,class:'person-years'},`${p.birth}–${p.death}`);g.append(yr);if(p.dx+7+yr.getComputedTextLength()>W-4){yr.setAttribute('x',p.dx-12);yr.setAttribute('text-anchor','end');}
      if(sel)g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX+6,ry:RY+6,fill:'none',stroke:'var(--graph-selected)','stroke-width':1.8,'stroke-opacity':.85,filter:'url(#glow)'}));
      g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX+9,ry:RY+9,class:'focus-ring'}));
      const cp=S('clipPath',{id:'clip-'+p.id});cp.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX,ry:RY}));defs.append(cp);
      g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX+3.5,ry:RY+3.5,fill:'var(--graph-sheet)',stroke:'var(--graph-ink-secondary)','stroke-opacity':.35,'stroke-width':.7}));
      g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX,ry:RY,class:'medallion-ring'}));
      if(p.portrait){g.append(S('image',{href:'../graph-f02/assets/'+p.portrait,x:p.bx-RX,y:p.y-RY,width:RX*2,height:RY*2,preserveAspectRatio:'xMidYMid slice','clip-path':`url(#clip-${p.id})`,filter:'url(#duo)'}));
                     g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX,ry:RY,fill:'none',stroke:'var(--graph-ink-secondary)','stroke-opacity':.8,'stroke-width':1.1}));}
      else g.append(S('text',{x:p.bx,y:p.y+7,class:'monogram'},p.mono));
      p.labelEnd=p.bx+RX+8+name.getComputedTextLength();
    });

    /* влияния: от года труда учителя к ленте ученика */
    const mids={};
    if(!bp.collapsed)influences.forEach((e,i)=>{
      const s=byId[e.a],t=byId[e.b],act=!!(R&&R.edges.has(e.a+'-'+e.b));
      const A={x:Math.min(Math.max(X(e.via),s.labelEnd+10),s.dx-8),y:s.y+BAND/2},bx0=Math.max(X(t.birth+22),t.labelEnd+14);
      const B=bx0>t.dx-8?{x:t.dx-3,y:t.y-BAND/2+5}:{x:bx0,y:t.y-BAND/2};
      const dx=B.x-A.x,dy=B.y-A.y,P=[A,{x:A.x+dx*.5,y:A.y+dy*.15},{x:B.x-dx*.15,y:B.y-dy*.65},B];mids[e.a+'-'+e.b]=cub(P,.5);
      const d=`M${A.x},${A.y} C${P[1].x},${P[1].y} ${P[2].x},${P[2].y} ${B.x},${B.y}`;
      if(R&&!act){L.threads.append(S('path',{d,fill:'none',stroke:'var(--graph-ink-muted)','stroke-opacity':.5,'stroke-width':1,'stroke-dasharray':'2 3','stroke-linecap':'round'}));return;}
      const gid='dg'+i,lg=S('linearGradient',{id:gid,gradientUnits:'userSpaceOnUse',x1:A.x,y1:A.y,x2:B.x,y2:B.y});
      lg.append(S('stop',{offset:'0%','stop-color':'var(--people)','stop-opacity':.75}));lg.append(S('stop',{offset:'100%','stop-color':act?'var(--graph-selected)':'var(--people)','stop-opacity':act?.95:.6}));defs.append(lg);
      const g=S('g',act?{filter:'url(#glow)',class:'thread-active'}:{});
      if(act)[[2.6,-2.2],[-2.2,2.6]].forEach(([ox,oy])=>g.append(S('path',{d:`M${A.x},${A.y} C${P[1].x+ox},${P[1].y+oy} ${P[2].x+ox},${P[2].y+oy} ${B.x},${B.y}`,fill:'none',stroke:`url(#${gid})`,'stroke-width':.6,'stroke-opacity':.45})));
      g.append(S('path',{d:ribbon(P,act?4.6:3.2,act?1.3:1),fill:`url(#${gid})`}));
      if(act)[.36,.64].forEach(tt=>{const q=cub(P,tt);g.append(S('circle',{cx:q.x,cy:q.y,r:1.4,fill:'#fff3e0','fill-opacity':.9}));});
      g.append(S('circle',{cx:A.x,cy:A.y,r:2.2,fill:'var(--people)'}));g.append(S('circle',{cx:B.x,cy:B.y,r:2.6,fill:act?'var(--graph-selected)':'var(--people)'}));
      L.threads.append(g);
    });

    /* труды */
    const bw=bands.works,items=[...works].sort((a,b)=>a.year-b.year);let active=null;
    if(bw.collapsed){items.forEach(it=>{const x=X(it.year),y=bw.top+COLL/2+1;L.works.append(S('rect',{x:x-3,y:y-4,width:6,height:8,rx:1,fill:'var(--texts)',opacity:.45}));});}
    else{const my=bw.top+36,rows=[[],[]];
      items.forEach(it=>{
        const x=X(it.year),act=!!(R&&R.works.has(it.id));if(act)active=it;
        const g=S('g',isDim(act)?{class:'dim-soft'}:{});
        if(it.kind==='work'){g.append(S('rect',{x:x-9,y:my-11,width:18,height:22,rx:1.5,class:'work-mark',...(act?{'stroke-width':1.6}:{})}));
          g.append(S('rect',{x:x-9,y:my-11,width:4.5,height:22,rx:1.2,fill:'var(--texts)','fill-opacity':.55}));
          g.append(S('path',{d:`M${x-1} ${my-4} h6 M${x-1} ${my} h6`,stroke:'var(--texts)','stroke-width':1,'stroke-opacity':.8}));}
        else{g.append(S('path',{d:`M${x} ${my-10} L${x+10} ${my} L${x} ${my+10} L${x-10} ${my} Z`,class:'concept-mark'}));g.append(S('circle',{cx:x,cy:my,r:2,fill:'var(--ideas)'}));}
        g.append(act?S('text',{x:x+25,y:my+4,class:'work-year','text-anchor':'start'},it.year):S('text',{x,y:my-22,class:'work-year','text-anchor':'middle'},it.year));
        const t=S('text',{x,class:act?'work-active-title':(it.kind==='work'?'work-title':'concept-title'),'text-anchor':'middle'});g.append(t);L.works.append(g);
        const lines=[''];it.title.split(' ').forEach(w=>{const c=(lines[lines.length-1]+' '+w).trim();t.textContent=c;if(t.getComputedTextLength()>170&&lines[lines.length-1])lines.push(w);else lines[lines.length-1]=c;});
        t.textContent='';lines.forEach((ln,k)=>t.append(S('tspan',{x,dy:k?15:0},ln)));
        const w2=t.getBBox().width,x0=x-w2/2-6,x1=x+w2/2+6,row=rows[0].every(([a,b])=>x1<a||x0>b)?0:1;rows[row].push([x0,x1]);
        t.setAttribute('y',my+30+row*38);t.firstChild.setAttribute('y',my+30+row*38);it.titleBox=t;
        if(act){L.works.insertBefore(S('circle',{cx:x,cy:my,r:15.5,fill:'none',stroke:'var(--texts)','stroke-width':1.8,'stroke-opacity':.5,filter:'url(#glow)'}),g);
          if(!bp.collapsed){const au=byId[it.author],A={x:Math.min(Math.max(x-28,au.labelEnd+10),au.dx-10),y:au.y+BAND/2},B={x,y:my-13};
            L.threads.append(S('path',{d:`M${A.x},${A.y} C${A.x},${A.y+22} ${B.x},${B.y-22} ${B.x},${B.y}`,fill:'none',stroke:'var(--texts)','stroke-width':1.5,'stroke-opacity':.85,'stroke-dasharray':'1 4','stroke-linecap':'round',filter:'url(#glow)'}));}}
      });}

    /* ось — гравированная масштабная линейка */
    const ay=bw.bot;
    L.axis.append(S('line',{x1:PLOT_L-6,y1:ay,x2:PLOT_R,y2:ay,stroke:'var(--graph-ink)','stroke-opacity':.55,'stroke-width':.8}));
    L.axis.append(S('line',{x1:X(1600),y1:ay+5,x2:X(1800),y2:ay+5,stroke:'var(--graph-ink)','stroke-opacity':.55,'stroke-width':.8}));
    for(let y=1600,k=0;y<1800;y+=25,k++)if(k%2===0)L.axis.append(S('rect',{x:X(y),y:ay,width:X(y+25)-X(y),height:5,fill:'var(--graph-ink)','fill-opacity':.5}));
    for(let y=1600;y<=1800;y+=25){const x=X(y),maj=y%50===0;L.axis.append(S('line',{x1:x,y1:ay,x2:x,y2:ay+(maj?9:5),stroke:'var(--graph-ink)','stroke-opacity':.55,'stroke-width':.8}));if(maj)L.axis.append(S('text',{x,y:ay+27,class:'axis-year'},y));}

    /* рукописные пометки: ищут свободное место у своего «якоря» */
    placeNotes({R});

    renderGutter(bands,H);renderNote(R);renderDesk(R);
    window.deskLayout={bands,H,people:byId,mids,state,BODY,svgTop:top};
    if(focusId){const f=svg.querySelector(`[data-person="${focusId}"]`);if(f)f.focus();}
    if(!reduce&&svg.animate)svg.animate([{opacity:.55},{opacity:1}],{duration:180,easing:'ease-out'});
  }

  function noteFor(sel){
    if(!sel)return null;
    return notes.find(n=>n.about.endsWith('-'+sel))||notes.find(n=>n.about===sel)||notes.find(n=>n.about.startsWith(sel+'-'))||null;
  }
  // На самом таймлайне рукописных пометок нет: карта только показывает данные.
  // Цитата выбранного — эпиграф на поле шапки, вне графа.
  function placeNotes({R}){
    const ep=document.querySelector('.epigraph'),n=R?noteFor(state.sel):null;
    if(ep){ep.innerHTML=n?`<blockquote>${n.lines.join(' ')}</blockquote><figcaption>— ${n.cite}</figcaption>`:'';ep.hidden=!n;}
  }
  // карточки на столе следуют за выбором: вопрос философа и его труды «к чтению»
  function renderDesk(R){
    const top=document.getElementById('card-top'),under=document.getElementById('card-under');
    const lines=(el,arr)=>{if(!el)return;el.querySelectorAll('.t').forEach(t=>t.remove());arr.forEach((x,i)=>{const d=document.createElement('div');d.className='t'+(i===0?' big':'');d.textContent=x;if(i===0&&el===top)d.style.marginTop='6px';el.append(d);});el.hidden=!arr.length;};
    const sel=state.sel;
    lines(top,sel?(questions[sel]||[]):theme.concat(['Декарт · Локк · Юм · Кант']));
    const ws=sel?works.filter(w=>w.author===sel&&w.kind==='work'):[];
    lines(under,ws.length?['К чтению:',...ws.map(w=>`«${w.title}», ${w.year}`)]:[]);
  }

  /* линзы — у своих страт, в левом поле */
  function renderGutter(bands,H){
    if(!gutter)return;
    if(!gutter.children.length)ORDER.forEach(k=>{const b=document.createElement('button');b.type='button';b.className='lens-toggle';b.dataset.lens=k;
      b.innerHTML=`<svg class="eye" viewBox="0 0 16 12" aria-hidden="true"><path d="M1 6 Q8 -1 15 6 Q8 13 1 6 Z"/><circle cx="8" cy="6" r="2.3"/><path class="slash" d="M2 11 L14 1"/></svg><span>${META[k].label}</span>`;
      b.addEventListener('click',()=>{const on=ORDER.filter(x=>state.on[x]);if(state.on[k]&&on.length===1)return;state.on[k]=!state.on[k];draw();});gutter.append(b);});
    [...gutter.children].forEach(b=>{const k=b.dataset.lens,band=bands[k];b.style.top=(band.top/H*100)+'%';b.setAttribute('aria-pressed',String(state.on[k]));
      b.title=state.on[k]?'Свернуть линзу':'Развернуть линзу';b.classList.toggle('off',!state.on[k]);});
  }

  /* сноска «Выбрано» — словами объясняет подсветку и служит легендой фокуса */
  function renderNote(R){
    if(!selnote)return;
    const h1=document.querySelector('.scene h1');
    if(!R){selnote.innerHTML='<div class="kicker">Как читать</div><p class="hint">Нажмите на философа — проявятся его влияния, труды и эпоха. Нажмите на поле листа или Esc, чтобы снять выбор.</p>';
      if(h1)h1.textContent='От Декарта до Канта';return;}
    const p=byId[state.sel];
    const ups=[...R.up].filter(id=>id!==p.id).map(id=>byId[id]).sort((a,b)=>a.birth-b.birth).map(x=>x.short);
    const downs=R.down.map(id=>byId[id].short),ws=works.filter(w=>R.works.has(w.id)),li=[];
    if(ups.length)li.push(`<li><i class="k k-flow"></i>Влияли: ${ups.join(' → ')}</li>`);
    if(downs.length)li.push(`<li><i class="k k-flow"></i>Повлиял на: ${downs.join(', ')}</li>`);
    li.push(ws.length?`<li><i class="k k-works"></i>Труды: ${ws.map(w=>`«${w.title}», ${w.year}`).join('; ')}</li>`:`<li><i class="k k-works"></i>Трудов в выборке нет</li>`);
    if(R.era)li.push(`<li><i class="k k-era"></i>Эпоха: ${R.era.label}</li>`);
    selnote.innerHTML=`<div class="kicker">Выбрано</div><div class="selname">${p.name} <span>${p.birth}–${p.death}</span></div><ul>${li.join('')}</ul>`;
    if(h1)h1.textContent=p.name;
  }

  /* выбор: клик/Enter по философу; клик по полю или Esc — снять */
  svg.addEventListener('click',ev=>{const g=ev.target.closest('[data-person]');state.sel=g?g.dataset.person:null;draw();});
  svg.addEventListener('keydown',ev=>{const g=ev.target.closest&&ev.target.closest('[data-person]');if(g&&(ev.key==='Enter'||ev.key===' ')){ev.preventDefault();state.sel=g.dataset.person;draw();}});
  document.addEventListener('keydown',ev=>{if(ev.key==='Escape'&&state.sel){state.sel=null;draw();}});
  window.desk={state,draw,select:id=>{state.sel=id;draw();},toggleLens:k=>{state.on[k]=!state.on[k];draw();}};
  let rz;addEventListener('resize',()=>{clearTimeout(rz);rz=setTimeout(draw,120);});
  document.fonts.ready.then(draw);
  draw();
})();
