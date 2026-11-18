/* Граф на рабочем листе сцены «стол философа». Рендер от данных и состояния, без ручных координат:
   - линзы: страта сворачивается, остальные забирают высоту;
   - люди: ленты жизни раскладываются по дорожкам автоматически (жадная упаковка с учётом подписей);
   - труды: отметка у каждого, подпись — только у ключевых и у трудов выбранного, если есть место;
   - выбор: прямые влияния (к нему и от него) — киноварный поток, его труды — бирюзовая нить,
     его эпоха — подсветка. Остальные связи при выборе скрыты.
   Данные — desk-data.js (?data=demo | dense). */
(function(){
  const NS='http://www.w3.org/2000/svg';
  const DS=window.DESK_SETS[new URLSearchParams(location.search).get('data')]||window.DESK_SETS.demo;
  const {people,influences,works,eras,events}=DS,notes=window.DESK_NOTES||[];
  const dense=people.length>12;

  // Ширина — реальные пиксели листа (шире лист — больше места на годы, а не крупнее шрифт).
  let W=1160,PLOT_R=W-26,BODY=500;const PLOT_L=150,TOP=28,AXIS_H=46,COLL=28;
  const [Y0,Y1]=DS.range,X=y=>PLOT_L+(y-Y0)/(Y1-Y0)*(PLOT_R-PLOT_L);
  const plural=(n,f)=>{const a=n%10,b=n%100;return `${n} ${a===1&&b!==11?f[0]:a>=2&&a<=4&&(b<10||b>=20)?f[1]:f[2]}`;};
  const ORDER=['events','eras','people','works'];
  const META={
    events:{label:'События',w:.10,max:90,count:plural(events.length,['событие','события','событий'])},
    eras:{label:'Эпохи',w:.11,max:70,count:plural(eras.length,['эпоха','эпохи','эпох'])},
    people:{label:'Люди',w:.52,max:1e4,count:plural(people.length,['философ','философа','философов'])},
    works:{label:'Труды',w:.27,max:240,count:plural(works.length,['труд','труда','трудов'])},
  };
  const state={sel:DS.sel||null,on:{events:false,eras:true,people:true,works:true}};
  const byId=Object.fromEntries(people.map(p=>[p.id,p]));
  const mono=p=>p.name.split(/\s+/).map(s=>s[0]).join('').slice(0,2).toUpperCase();

  const S=(t,a,txt)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(txt!=null)e.textContent=txt;return e;};
  const cub=(P,t)=>{const u=1-t;return{x:u*u*u*P[0].x+3*u*u*t*P[1].x+3*u*t*t*P[2].x+t*t*t*P[3].x,y:u*u*u*P[0].y+3*u*u*t*P[1].y+3*u*t*t*P[2].y+t*t*t*P[3].y};};
  const tan=(P,t)=>{const u=1-t;return{x:3*u*u*(P[1].x-P[0].x)+6*u*t*(P[2].x-P[1].x)+3*t*t*(P[3].x-P[2].x),y:3*u*u*(P[1].y-P[0].y)+6*u*t*(P[2].y-P[1].y)+3*t*t*(P[3].y-P[2].y)};};
  const ribbon=(P,w0,w1,N=28)=>{const a=[],b=[];for(let i=0;i<=N;i++){const t=i/N,p=cub(P,t),d=tan(P,t),l=Math.hypot(d.x,d.y)||1,nx=-d.y/l,ny=d.x/l,w=(w0*(1-t)+w1*t)/2;a.push(`${(p.x+nx*w).toFixed(1)},${(p.y+ny*w).toFixed(1)}`);b.unshift(`${(p.x-nx*w).toFixed(1)},${(p.y-ny*w).toFixed(1)}`);}return 'M'+a.join(' L')+' L'+b.join(' L')+' Z';};

  const svg=document.getElementById('svg');
  const gutter=document.querySelector('.gutter'),selnote=document.querySelector('.selnote');
  const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
  svg.classList.toggle('compact',dense);
  const measure=(cls,txt)=>{const t=S('text',{class:cls},txt);svg.append(t);const w=t.getComputedTextLength();t.remove();return w;};

  // что связано с выбранным: прямые учителя и ученики, его труды, его эпоха
  function related(){
    const sel=state.sel;if(!sel)return null;
    const ins=influences.filter(e=>e.b===sel),outs=influences.filter(e=>e.a===sel);
    const p=byId[sel],mid=(p.birth+p.death)/2;
    return {up:ins.map(e=>e.a),down:outs.map(e=>e.b),edges:new Set([...ins,...outs].map(e=>e.a+'-'+e.b)),
      people:new Set([sel,...ins.map(e=>e.a),...outs.map(e=>e.b)]),works:new Set(works.filter(w=>w.author===sel).map(w=>w.id)),
      era:eras.find(e=>mid>=e.from&&mid<e.to)};
  }

  /* дорожки людей: жадная упаковка по году рождения; занятый отрезок — лента + подписи */
  function packPeople(R0){
    people.forEach(p=>{
      p.bx=X(p.birth);p.dx=X(p.death);
      const full=measure('person-name',p.name),short=measure('person-name',p.short);
      p.label=(p.dx-p.bx>=full+R0+30||!dense)?p.name:p.short;
      const lw=p.label===p.name?full:short,yw=dense?0:measure('person-years',`${p.birth}–${p.death}`);
      p.nameEnd=p.bx+R0+8+lw;p.yearsIn=dense||p.dx-p.nameEnd>=yw+26;
      p.occ=[p.bx-R0-6,p.yearsIn?Math.max(p.dx,p.nameEnd)+6:Math.max(p.dx,p.nameEnd)+8+yw+12];
    });
    const lanes=[];[...people].sort((a,b)=>a.birth-b.birth).forEach(p=>{
      let k=lanes.findIndex(end=>end<p.occ[0]);if(k<0){k=lanes.length;lanes.push(0);}lanes[k]=p.occ[1];p.lane=k;});
    return lanes.length;
  }

  /* подписи трудов: приоритет — труды выбранного, затем ключевые; ряд — первый свободный; нет места — без подписи */
  function planWorks(R,maxRows){
    const items=[...works].sort((a,b)=>a.year-b.year);let prev=-1e9;
    items.forEach(it=>{it.x=X(it.year);it.labeled=false;});
    const mine=it=>!!(R&&R.works.has(it.id));
    const cand=items.filter(it=>mine(it)||it.key).sort((a,b)=>(mine(b)-mine(a))||(a.year-b.year));
    const rows=[];
    cand.forEach(it=>{
      const lines=wrap(mine(it)?`${it.title}, ${it.year}`:it.title,dense?150:170,it.kind==='concept'?'concept-title':'work-title');
      const w=Math.max(...lines.map(l=>l.w)),x0=it.x-w/2-8,x1=it.x+w/2+8;
      if(x0<PLOT_L-10||x1>W-4)return;
      for(let r=0;r<maxRows;r++){rows[r]=rows[r]||[];if(rows[r].every(([a,b])=>x1<a||x0>b)){rows[r].push([x0,x1]);it.labeled=true;it.row=r;it.lines=lines;break;}}
    });
    // значки подписанных трудов одного года раздвигаются, чтобы не слипались
    items.filter(it=>it.labeled).forEach(it=>{it.ix=Math.max(it.x,prev+(mine(it)?34:24));prev=it.ix;});
    items.filter(it=>!it.labeled).forEach(it=>it.ix=it.x);
    return {items,rows:Math.max(1,rows.filter(r=>r&&r.length).length)};
  }
  function wrap(title,max,cls){
    const lines=[''];title.split(' ').forEach(w=>{const c=(lines[lines.length-1]+' '+w).trim();if(measure(cls,c)>max&&lines[lines.length-1])lines.push(w);else lines[lines.length-1]=c;});
    return lines.slice(0,2).map((t,i)=>{const s=i===1&&lines.length>2?t+'…':t;return {t:s,w:measure(cls,s)};});
  }

  function layoutBands(need){
    const on=ORDER.filter(k=>state.on[k]),free=BODY-(ORDER.length-on.length)*COLL,sw=on.reduce((a,k)=>a+META[k].w,0),h={};
    ORDER.forEach(k=>h[k]=state.on[k]?Math.min(META[k].max,free*META[k].w/sw):COLL);
    ORDER.forEach(k=>{if(state.on[k]&&need[k])h[k]=Math.max(h[k],need[k]);});
    if(state.on.people)h.people=Math.max(h.people,h.people+BODY-ORDER.reduce((a,k)=>a+h[k],0));
    let y=TOP;const b={};ORDER.forEach(k=>{b[k]={key:k,top:y,bot:y+h[k],collapsed:!state.on[k],...META[k]};y+=h[k];});return b;
  }

  function draw(){
    const ae=document.activeElement,focusId=ae&&ae.dataset?ae.dataset.person:null;
    svg.innerHTML='';
    const cw=Math.round(svg.getBoundingClientRect().width)||1160;W=Math.max(900,cw);PLOT_R=W-26;
    const top=svg.getBoundingClientRect().top+scrollY;BODY=Math.round(Math.min(760,Math.max(440,innerHeight-top-AXIS_H-TOP-96)));
    if(gutter)gutter.style.width=PLOT_L+'px';
    const R=related();

    // размеры от данных: дорожки людей и ряды подписей трудов
    const LANES=packPeople(dense?4:22),laneMin=dense?27:56;
    const plan=planWorks(R,dense?3:2);
    const need={people:LANES*laneMin+34,works:46+plan.rows*38+(dense?8:20),events:dense?78:64};
    const bands=layoutBands(need),H=bands.works.bot+AXIS_H;
    svg.setAttribute('viewBox',`0 0 ${W} ${H}`);

    const defs=S('defs',{});
    const duo=S('filter',{id:'duo'});duo.append(S('feColorMatrix',{type:'saturate',values:'0'}));
    const ct=S('feComponentTransfer',{});[['R','.16 .95'],['G','.13 .92'],['B','.10 .84']].forEach(([c,v])=>ct.append(S('feFunc'+c,{type:'table',tableValues:v})));duo.append(ct);defs.append(duo);
    const glow=S('filter',{id:'glow',x:'-60%',y:'-60%',width:'220%',height:'220%'});
    glow.append(S('feGaussianBlur',{in:'SourceGraphic',stdDeviation:'2.4',result:'b'}));
    const fm=S('feMerge',{});fm.append(S('feMergeNode',{in:'b'}));fm.append(S('feMergeNode',{in:'SourceGraphic'}));glow.append(fm);defs.append(glow);
    svg.append(defs);
    const L={};['grid','bands','eras','events','threads','works','people','axis'].forEach(k=>{L[k]=S('g',{});svg.append(L[k]);});
    const isDim=on=>R&&!on;

    /* шаг шкалы: подписи не ближе ~70 px */
    const pxYear=(PLOT_R-PLOT_L)/(Y1-Y0),step=[10,25,50,100].find(s=>s*pxYear>=70)||100;
    const ticks=[];for(let y=Math.ceil(Y0/step)*step;y<=Y1;y+=step)ticks.push(y);
    ticks.forEach(y=>L.grid.append(S('line',{x1:X(y),y1:TOP,x2:X(y),y2:bands.works.bot,class:'time-grid'})));
    ORDER.forEach(k=>{const b=bands[k];L.bands.append(S('line',{x1:PLOT_L-6,y1:b.top,x2:PLOT_R,y2:b.top,class:'band-sep'}));
      if(b.collapsed)L.bands.append(S('text',{x:PLOT_L+4,y:b.top+18,class:'collapsed-note'},`${b.count} · линза свёрнута`));});

    /* люди: геометрия (нужна эпохам и связям) */
    const bp=bands.people,laneH=(bp.bot-bp.top-30)/LANES;
    // плотный режим (Пристли): тонкие ленты без медальонов; медальон — только у выбранного
    const RY=dense?4:Math.min(27,laneH*.4),RX=dense?4:RY*.82,BAND=dense?Math.min(18,laneH*.66):Math.min(24,Math.max(14,laneH*.46));
    people.forEach(p=>{p.y=bp.top+20+(p.lane+.5)*laneH;});

    /* эпохи — только заливка и подпись */
    const be=bands.eras;
    if(!be.collapsed)eras.forEach(e=>{const x1=Math.max(X(e.from),PLOT_L),x2=Math.min(X(e.to),PLOT_R),act=R&&R.era===e;
      L.eras.append(S('rect',{x:x1,y:be.top+1,width:x2-x1-1,height:be.bot-be.top-2,fill:'var(--context)',opacity:act?.15:.06}));
      const t=S('text',{x:(x1+x2)/2,y:(be.top+be.bot)/2+5,class:'era-text'+(act?' era-active':'')},e.label);L.eras.append(t);
      if(t.getComputedTextLength()>x2-x1-12)t.remove();});

    /* события мира: кольцо + «год событие»; подписи в два ряда, без места — только кольцо */
    const bv=bands.events;
    if(!bv.collapsed){const ry=bv.top+20,rings=events.map(e=>[X(e.year)-8,X(e.year)+8]),rows=[[],[]];
      events.forEach((e,ei)=>{const x=X(e.year),g=S('g',{});L.events.append(g);
        g.append(S('circle',{cx:x,cy:ry,r:5,class:'event-ring'}));g.append(S('circle',{cx:x,cy:ry,r:1.8,fill:'var(--history)'}));
        g.append(S('title',{},`${e.year} — ${e.label}`));
        const t=S('text',{class:'event-text'});t.append(S('tspan',{class:'event-year'},e.year+' '));t.append(document.createTextNode(e.label));g.append(t);
        const w=t.getComputedTextLength();
        for(let r=0;r<2;r++){const x0=r?x-4:x+10,x1=x0+w;if(x1>PLOT_R)continue;
          if(rows[r].every(([a,b])=>x1+10<a||x0>b+10)&&(r||rings.every(([a,b],k)=>k===ei||x1+4<a||x0>b+4))){rows[r].push([x0,x1]);t.setAttribute('x',x0);t.setAttribute('y',r?ry+26:ry+4.5);return;}}
        t.remove();});}

    /* люди: ленты Пристли */
    if(bp.collapsed)people.forEach(p=>L.people.append(S('rect',{x:p.bx,y:bp.top+COLL-7,width:p.dx-p.bx,height:3,rx:1.5,fill:'var(--people)',opacity:.35})));
    else people.forEach(p=>{
      const sel=p.id===state.sel,on=!R||R.people.has(p.id);
      const g=S('g',{class:'person'+(isDim(on)?' dim':''),'data-person':p.id,tabindex:0,role:'button','aria-pressed':String(sel),'aria-label':`${p.name}, ${p.birth}–${p.death}`});L.people.append(g);
      g.append(S('rect',{x:p.bx,y:p.y-BAND/2,width:p.dx-p.bx,height:BAND,rx:BAND/2,class:'lifeline',fill:sel?'var(--graph-selected)':'var(--graph-ink-secondary)','fill-opacity':sel?.16:(dense?.17:.09)}));
      const name=S('text',{x:p.bx+(dense?10:RX+8),y:p.y+(dense?4.6:5.4),class:sel?'sel-name':'person-name'},p.label);g.append(name);
      g.append(S('title',{},`${p.name}, ${p.birth}–${p.death}`));
      const yr=S('text',{y:p.y+4.3,class:'person-years'},`${p.birth}–${p.death}`);if(!dense)g.append(yr);
      if(p.yearsIn){yr.setAttribute('x',p.dx-BAND/2);yr.setAttribute('text-anchor','end');}else yr.setAttribute('x',Math.max(p.dx,p.bx+RX+8+name.getComputedTextLength())+8);
      if(dense){g.append(S('circle',{cx:p.bx+BAND/2,cy:p.y,r:2.2,class:'life-dot'}));
        if(sel){const r=13;g.append(S('circle',{cx:p.bx,cy:p.y,r:r+3,fill:'none',stroke:'var(--graph-selected)','stroke-width':1.6,filter:'url(#glow)'}));
          g.append(S('circle',{cx:p.bx,cy:p.y,r,class:'medallion-ring'}));
          if(p.portrait){const cp=S('clipPath',{id:'clip-'+p.id});cp.append(S('circle',{cx:p.bx,cy:p.y,r}));defs.append(cp);
            g.append(S('image',{href:'../graph-f02/assets/'+p.portrait,x:p.bx-r,y:p.y-r,width:r*2,height:r*2,preserveAspectRatio:'xMidYMid slice','clip-path':`url(#clip-${p.id})`,filter:'url(#duo)'}));}
          else g.append(S('text',{x:p.bx,y:p.y+3.5,class:'monogram',style:'font-size:10px'},mono(p)));
          name.setAttribute('x',p.bx+r+7);}
        g.append(S('rect',{x:p.bx-6,y:p.y-BAND/2-3,width:p.dx-p.bx+12,height:BAND+6,rx:4,class:'focus-ring'}));
        p.labelEnd=+name.getAttribute('x')+name.getComputedTextLength();return;}
      if(sel)g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX+4,ry:RY+4,fill:'none',stroke:'var(--graph-selected)','stroke-width':1.8,'stroke-opacity':.85,filter:'url(#glow)'}));
      g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX+7,ry:RY+7,class:'focus-ring'}));
      g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX,ry:RY,class:'medallion-ring'}));
      if(p.portrait){const cp=S('clipPath',{id:'clip-'+p.id});cp.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX,ry:RY}));defs.append(cp);
        g.append(S('image',{href:'../graph-f02/assets/'+p.portrait,x:p.bx-RX,y:p.y-RY,width:RX*2,height:RY*2,preserveAspectRatio:'xMidYMid slice','clip-path':`url(#clip-${p.id})`,filter:'url(#duo)'}));
        g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX,ry:RY,fill:'none',stroke:'var(--graph-ink-secondary)','stroke-opacity':.8,'stroke-width':1}));}
      else g.append(S('text',{x:p.bx,y:p.y+RY*.27,class:'monogram',style:`font-size:${(RY*.72).toFixed(1)}px`},mono(p)));
      p.labelEnd=p.bx+RX+8+name.getComputedTextLength();
    });

    /* влияния: без выбора — тонкие линии; при выборе — только прямые связи выбранного, потоком */
    const mids={};
    // концы нитей одного философа раздвигаются вдоль его ленты — пучок не сходится в одну точку
    // без выбора тонкие линии рисуются, только пока их немного: на плотных данных это паутина — связи видны по выбору
    const shown=bp.collapsed||(!R&&influences.length>15)?[]:influences.filter(e=>byId[e.a]&&byId[e.b]&&(!R||R.edges.has(e.a+'-'+e.b)));
    const slot={};const order=(key,list)=>list.forEach((e,k)=>slot[key(e)]=k);
    people.forEach(p=>{order(e=>'in'+e.a+'-'+e.b,shown.filter(e=>e.b===p.id).sort((x,y)=>byId[x.a].y-byId[y.a].y));
      order(e=>'out'+e.a+'-'+e.b,shown.filter(e=>e.a===p.id).sort((x,y)=>byId[x.b].y-byId[y.b].y));});
    shown.forEach((e,i)=>{
      const s=byId[e.a],t=byId[e.b],act=!!R,si=slot['out'+e.a+'-'+e.b]*9,ti=slot['in'+e.a+'-'+e.b]*9;
      const down=t.y>s.y,via=e.via||Math.min(s.death-5,s.birth+40);
      const A={x:Math.min(Math.max(X(via),s.labelEnd+10)+si,s.dx-8),y:s.y+(down?BAND/2:-BAND/2)},bx0=Math.max(X(t.birth+22),t.labelEnd+14)+ti;
      const B=bx0>t.dx-8?{x:t.dx-3,y:t.y+(down?-BAND/2+5:BAND/2-5)}:{x:bx0,y:t.y+(down?-BAND/2:BAND/2)};
      const dx=B.x-A.x,dy=B.y-A.y,P=[A,{x:A.x+dx*.5,y:A.y+dy*.15},{x:B.x-dx*.15,y:B.y-dy*.65},B];mids[e.a+'-'+e.b]=cub(P,.5);
      if(!act){L.threads.append(S('path',{d:`M${A.x},${A.y} C${P[1].x},${P[1].y} ${P[2].x},${P[2].y} ${B.x},${B.y}`,class:'thread-quiet'}));return;}
      const gid='dg'+i,lg=S('linearGradient',{id:gid,gradientUnits:'userSpaceOnUse',x1:A.x,y1:A.y,x2:B.x,y2:B.y});
      lg.append(S('stop',{offset:'0%','stop-color':'var(--people)','stop-opacity':.7}));lg.append(S('stop',{offset:'100%','stop-color':'var(--graph-selected)','stop-opacity':.95}));defs.append(lg);
      const g=S('g',{filter:'url(#glow)',class:'thread-active'});
      g.append(S('path',{d:ribbon(P,dense?3.6:4.4,1.2),fill:`url(#${gid})`}));
      g.append(S('circle',{cx:B.x,cy:B.y,r:2.6,fill:'var(--graph-selected)'}));
      L.threads.append(g);
    });

    /* труды */
    const bw=bands.works;
    if(bw.collapsed)plan.items.forEach(it=>L.works.append(S('rect',{x:it.x-1,y:bw.top+COLL/2-5,width:2,height:10,fill:'var(--texts)',opacity:.45})));
    else{const my=bw.top+24;
      plan.items.forEach(it=>{
        const act=!!(R&&R.works.has(it.id)),x=it.ix;
        const g=S('g',isDim(act)?{class:'dim-soft'}:{});L.works.append(g);g.append(S('title',{},`${it.title}, ${it.year} — ${byId[it.author]?byId[it.author].name:''}`));
        if(!it.labeled){g.append(S('rect',{x:x-1,y:my-8,width:2,height:16,rx:1,class:'work-tick'}));return;}
        if(it.kind==='work'){g.append(S('rect',{x:x-8,y:my-10,width:16,height:20,rx:1.5,class:'work-mark',...(act?{'stroke-width':1.6}:{})}));
          g.append(S('rect',{x:x-8,y:my-10,width:4,height:20,rx:1.2,fill:'var(--texts)','fill-opacity':.55}));}
        else{g.append(S('path',{d:`M${x} ${my-9} L${x+9} ${my} L${x} ${my+9} L${x-9} ${my} Z`,class:'concept-mark'}));g.append(S('circle',{cx:x,cy:my,r:1.8,fill:'var(--ideas)'}));}
        const ty=my+30+it.row*38,t=S('text',{x,y:ty,class:act?'work-active-title':(it.kind==='work'?'work-title':'concept-title'),'text-anchor':'middle'});
        it.lines.forEach((ln,k)=>t.append(S('tspan',{x,dy:k?15:0},ln.t)));g.append(t);
        if(act){L.works.insertBefore(S('circle',{cx:x,cy:my,r:14.5,fill:'none',stroke:'var(--texts)','stroke-width':1.8,'stroke-opacity':.5,filter:'url(#glow)'}),g);
          const au=byId[it.author];if(!bp.collapsed&&au){const A={x:Math.min(Math.max(x-28,au.labelEnd+10),au.dx-10),y:au.y+BAND/2},B={x,y:my-12};
            L.threads.append(S('path',{d:`M${A.x},${A.y} C${A.x},${A.y+22} ${B.x},${B.y-22} ${B.x},${B.y}`,class:'tether'}));}}
      });}

    /* ось: линия, деления, годы */
    const ay=bw.bot;
    L.axis.append(S('line',{x1:PLOT_L-6,y1:ay,x2:PLOT_R,y2:ay,stroke:'var(--graph-ink)','stroke-opacity':.5,'stroke-width':.8}));
    ticks.forEach(y=>{const x=X(y);L.axis.append(S('line',{x1:x,y1:ay,x2:x,y2:ay+6,stroke:'var(--graph-ink)','stroke-opacity':.5,'stroke-width':.8}));L.axis.append(S('text',{x,y:ay+24,class:'axis-year'},y));});

    renderGutter(bands,H);renderNote(R);renderDesk(R);
    window.deskLayout={bands,H,people:byId,mids,state,BODY,svgTop:top,lanes:LANES,labeledWorks:plan.items.filter(i=>i.labeled).length};
    if(focusId){const f=svg.querySelector(`[data-person="${focusId}"]`);if(f)f.focus();}
    if(!reduce&&svg.animate)svg.animate([{opacity:.55},{opacity:1}],{duration:180,easing:'ease-out'});
  }

  // карточки на столе следуют за выбором: цитата (с источником) и труды «к чтению»; нет данных — нет карточки
  function renderDesk(R){
    const top=document.getElementById('card-top'),under=document.getElementById('card-under');
    const lines=(el,arr)=>{if(!el)return;el.querySelectorAll('.t').forEach(t=>t.remove());arr.forEach((x,i)=>{const d=document.createElement('div');d.className='t'+(i===0?' big':'');d.textContent=x;if(i===0&&el===top)d.style.marginTop='6px';el.append(d);});el.hidden=!arr.length;};
    const n=R&&notes.find(x=>x.about===state.sel);
    lines(top,n?[...n.lines,'— '+n.cite]:[]);
    const ws=R?works.filter(w=>w.author===state.sel&&w.kind==='work').sort((a,b)=>b.key-a.key).slice(0,3):[];
    lines(under,ws.length?['К чтению:',...ws.map(w=>`«${w.title}», ${w.year}`)]:[]);
    const ed=document.querySelector('.edition-note');
    if(ed)ed.textContent=dense?`Синтетический набор для проверки плотности · ${META.people.count} · ${META.works.count} · ${plural(influences.length,['влияние','влияния','влияний'])}`:'Демонстрационные данные';
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

  /* сноска «Выбрано» — словами объясняет подсветку; длинные списки сокращаются */
  function renderNote(R){
    if(!selnote)return;
    const h1=document.querySelector('.scene h1');
    if(!R){const more=influences.length>15?` Связей ${influences.length} — они показываются по выбору.`:'';
      selnote.innerHTML=`<div class="kicker">Как читать</div><p class="hint">Нажмите на философа — проявятся его влияния, труды и эпоха.${more} Нажмите на поле листа или Esc, чтобы снять выбор.</p>`;
      if(h1)h1.textContent=DS.title;return;}
    const p=byId[state.sel],cut=(a,n)=>a.length>n?a.slice(0,n).join(', ')+` и ещё ${a.length-n}`:a.join(', ');
    const ups=R.up.map(id=>byId[id]).sort((a,b)=>a.birth-b.birth).map(x=>x.short),downs=R.down.map(id=>byId[id]).sort((a,b)=>a.birth-b.birth).map(x=>x.short);
    const ws=works.filter(w=>R.works.has(w.id)&&w.kind==='work'),li=[];
    if(ups.length)li.push(`<li><i class="k k-flow"></i><span>Влияли: ${cut(ups,3)}</span></li>`);
    if(downs.length)li.push(`<li><i class="k k-flow"></i><span>Повлиял на: ${cut(downs,3)}</span></li>`);
    li.push(ws.length?`<li><i class="k k-works"></i><span>Труды: ${ws.length>1?plural(ws.length,['труд','труда','трудов'])+', главный — ':''}«${(ws.find(w=>w.key)||ws[0]).title}»</span></li>`:`<li><i class="k k-works"></i><span>Трудов в выборке нет</span></li>`);
    if(R.era)li.push(`<li><i class="k k-era"></i><span>Эпоха: ${R.era.label}</span></li>`);
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
