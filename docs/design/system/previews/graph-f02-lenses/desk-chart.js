/* Граф на рабочем листе сцены «стол философа». Рендер от данных и состояния, без ручных координат.
   Три механизма не смешиваются:
   - линза — какие слои видны (страта сворачивается, остальные забирают высоту);
   - фильтр — какие объекты остаются (скрытые исчезают, дорожки перепаковываются);
   - выбор — фокус: нерелевантные труды убираются, люди приглушаются, но читаются и кликабельны.
   Связи-линии — только между людьми. Принадлежность трудов — цветом автора.
   Подписи не отрываются от значков: «булавка» — отметка года на кромке страты, ножка к ряду, значок+подпись.
   Данные — desk-data.js (?data=demo | dense). Фильтры, поиск и открытые меню пока задаются адресом (кадр). */
(function(){
  const NS='http://www.w3.org/2000/svg';
  const Q=new URLSearchParams(location.search);
  const DS=window.DESK_SETS[Q.get('data')]||window.DESK_SETS.demo;
  const ALL={people:DS.people,works:DS.works,influences:DS.influences,eras:DS.eras,events:DS.events,groups:DS.groups||[]};
  const notes=window.DESK_NOTES||[];
  const dense=ALL.people.length>12;
  const list=k=>(Q.get(k)||'').split(',').filter(Boolean);
  const filter={from:+Q.get('from')||null,to:+Q.get('to')||null,groups:list('groups'),roles:list('roles'),kinds:list('kinds'),ekinds:list('ekinds'),verified:Q.get('verified')==='1'};

  /* фильтр → видимые данные */
  const V=(()=>{
    const gs=ALL.groups.filter(g=>filter.groups.includes(g.id)),from=filter.from||DS.range[0],to=filter.to||DS.range[1];
    const people=ALL.people.filter(p=>(!gs.length||gs.some(g=>g.members.includes(p.id)))&&(!filter.roles.length||(p.roles||[]).some(r=>filter.roles.includes(r)))&&p.death>=from&&p.birth<=to);
    const ids=new Set(people.map(p=>p.id));
    return {people,range:[from,to],
      works:ALL.works.filter(w=>ids.has(w.author)&&(!filter.kinds.length||filter.kinds.includes(w.kind))&&w.year>=from&&w.year<=to),
      influences:ALL.influences.filter(e=>ids.has(e.a)&&ids.has(e.b)&&(!filter.verified||e.verified)),
      events:ALL.events.filter(e=>(!filter.ekinds.length||filter.ekinds.includes(e.kind))&&e.year>=from&&e.year<=to),
      eras:ALL.eras.filter(e=>e.to>from&&e.from<to)};
  })();
  const filtered=V.people.length<ALL.people.length||V.works.length<ALL.works.length||!!filter.from||!!filter.to||filter.verified||filter.ekinds.length>0;

  let W=1160,PLOT_R=W-26,BODY=500;const PLOT_L=150,TOP=28,COLL=28;
  const [Y0,Y1]=V.range,X=y=>PLOT_L+(y-Y0)/(Y1-Y0)*(PLOT_R-PLOT_L),clampX=x=>Math.max(PLOT_L,Math.min(PLOT_R,x));
  const plural=(n,f)=>{const a=n%10,b=n%100;return `${n} ${a===1&&b!==11?f[0]:a>=2&&a<=4&&(b<10||b>=20)?f[1]:f[2]}`;};
  const F={people:['философ','философа','философов'],works:['труд','труда','трудов'],events:['событие','события','событий'],eras:['эпоха','эпохи','эпох'],links:['влияние','влияния','влияний']};
  const ORDER=['events','eras','people','works'];
  const META={
    events:{label:'События',w:.10,max:90,count:plural(V.events.length,F.events)},
    eras:{label:'Эпохи',w:.11,max:70,count:plural(V.eras.length,F.eras)},
    people:{label:'Люди',w:.52,max:1e4,count:plural(V.people.length,F.people)},
    works:{label:'Труды',w:.27,max:260,count:plural(V.works.length,F.works)},
  };
  const state={sel:Q.has('sel')?(Q.get('sel')||null):(DS.sel||null),on:{events:Q.get('events')!=='0',eras:true,people:true,works:true}};
  if(!dense&&!Q.has('events'))state.on.events=false;
  const byId=Object.fromEntries(ALL.people.map(p=>[p.id,p])),wById=Object.fromEntries(ALL.works.map(w=>[w.id,w]));
  const eById=Object.fromEntries(ALL.events.map(e=>[e.id,e])),eraById=Object.fromEntries(ALL.eras.map(e=>[e.id,e])),gById=Object.fromEntries(ALL.groups.map(g=>[g.id,g]));
  const find=id=>byId[id]?{type:'person',obj:byId[id]}:wById[id]?{type:'work',obj:wById[id]}:eById[id]?{type:'event',obj:eById[id]}:eraById[id]?{type:'era',obj:eraById[id]}:gById[id]?{type:'group',obj:gById[id]}:null;
  const mono=p=>p.name.split(/\s+/).map(s=>s[0]).join('').slice(0,2).toUpperCase();
  // цвета ролей и палитра группы (тёмные оттенки: подписи этим цветом читаются на бумаге ≥4.5:1)
  const C={sel:'#a8371f',teacher:'#3c4d78',student:'#3f6b2a',neutral:'#5a4632'};
  const PAL=['#3c4d78','#2f6670','#8a3b45','#3f6b2a','#6d3f78','#7f5410'];
  const KIND={work:'Произведение',concept:'Понятие',position:'Позиция',argument:'Аргумент'};

  const S=(t,a,txt)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(txt!=null)e.textContent=txt;return e;};
  const cub=(P,t)=>{const u=1-t;return{x:u*u*u*P[0].x+3*u*u*t*P[1].x+3*u*t*t*P[2].x+t*t*t*P[3].x,y:u*u*u*P[0].y+3*u*u*t*P[1].y+3*u*t*t*P[2].y+t*t*t*P[3].y};};

  const svg=document.getElementById('svg');
  const gutter=document.querySelector('.gutter'),selnote=document.querySelector('.selnote');
  const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
  svg.classList.toggle('compact',dense);
  const measure=(cls,txt)=>{const t=S('text',{class:cls},txt);svg.append(t);const w=t.getComputedTextLength();t.remove();return w;};

  /* выбор → кто и что в фокусе, каким цветом */
  function related(){
    const f=state.sel&&find(state.sel);if(!f)return null;
    const R={type:f.type,obj:f.obj,people:new Map(),works:null,edges:[],era:null,events:null,primary:null,legend:[]};
    const mid=p=>(p.birth+p.death)/2,eraOf=y=>V.eras.find(e=>y>=e.from&&y<e.to)||null;
    const group=members=>{
      const imp=p=>V.works.filter(w=>w.author===p.id&&w.key).length*2+V.influences.filter(e=>e.a===p.id).length;
      const top=[...members].sort((a,b)=>imp(b)-imp(a)).slice(0,6).sort((a,b)=>a.birth-b.birth);
      members.forEach(p=>R.people.set(p.id,C.neutral));top.forEach((p,i)=>R.people.set(p.id,PAL[i]));
      R.legend=[...top.map(p=>[R.people.get(p.id),p.short]),...(members.length>top.length?[[C.neutral,`и ещё ${members.length-top.length}`]]:[])];
    };
    if(f.type==='person'){const p=f.obj;R.people.set(p.id,C.sel);
      V.influences.forEach(e=>{if(e.b===p.id){R.people.set(e.a,C.teacher);R.edges.push({e,color:C.teacher});}if(e.a===p.id){R.people.set(e.b,C.student);R.edges.push({e,color:C.student});}});
      R.works=new Set(V.works.filter(w=>w.author===p.id).map(w=>w.id));R.era=eraOf(mid(p));R.events=new Set(V.events.filter(e=>e.year>=p.birth&&e.year<=p.death).map(e=>e.id));}
    else if(f.type==='work'){const w=f.obj,p=byId[w.author];R.people.set(p.id,C.sel);R.primary=w.id;
      R.works=new Set(V.works.filter(x=>x.author===p.id).map(x=>x.id));R.era=eraOf(w.year);R.events=new Set(V.events.filter(e=>Math.abs(e.year-w.year)<=10).map(e=>e.id));}
    else if(f.type==='era'){const e=f.obj;group(V.people.filter(p=>mid(p)>=e.from&&mid(p)<e.to));R.era=e;
      R.works=new Set(V.works.filter(w=>R.people.has(w.author)&&w.year>=e.from&&w.year<e.to).map(w=>w.id));R.events=new Set(V.events.filter(x=>x.year>=e.from&&x.year<e.to).map(x=>x.id));}
    else if(f.type==='event'){const e=f.obj;group(V.people.filter(p=>p.birth<=e.year&&p.death>=e.year));R.era=eraOf(e.year);
      R.works=new Set(V.works.filter(w=>R.people.has(w.author)&&Math.abs(w.year-e.year)<=10).map(w=>w.id));R.events=new Set([e.id]);}
    else if(f.type==='group'){const g=f.obj;group(V.people.filter(p=>g.members.includes(p.id)));
      R.works=new Set(V.works.filter(w=>R.people.has(w.author)).map(w=>w.id));
      V.influences.forEach(e=>{if(R.people.has(e.a)&&R.people.has(e.b))R.edges.push({e,color:R.people.get(e.a)});});}
    return R;
  }

  /* дорожки людей: жадная упаковка по году рождения; занятый отрезок — лента + подписи */
  function packPeople(R0){
    V.people.forEach(p=>{
      p.bx=clampX(X(p.birth));p.dx=clampX(X(p.death));
      const full=measure('person-name',p.name),short=measure('person-name',p.short);
      p.label=(p.dx-p.bx>=full+R0+30||!dense)?p.name:p.short;
      const lw=p.label===p.name?full:short,yw=dense?0:measure('person-years',`${p.birth}–${p.death}`);
      p.nameEnd=p.bx+R0+8+lw;p.yearsIn=dense||p.dx-p.nameEnd>=yw+26;
      p.occ=[p.bx-R0-6,p.yearsIn?Math.max(p.dx,p.nameEnd)+6:Math.max(p.dx,p.nameEnd)+8+yw+12];
    });
    const lanes=[];[...V.people].sort((a,b)=>a.birth-b.birth).forEach(p=>{
      let k=lanes.findIndex(end=>end<p.occ[0]);if(k<0){k=lanes.length;lanes.push(0);}lanes[k]=p.occ[1];p.lane=k;});
    return lanes.length;
  }

  /* «булавки»: блок (значок+подпись) в первом свободном ряду рядом с годом; ножка от кромки страты
     не пересекает блоки верхних рядов, блок не пересекает чужие ножки. Нет места — только отметка года. */
  function pins(items,{maxRows,block,maxShift}){
    // кандидаты (ряд, сдвиг) по «цене»: сдвиг вдоль кромки + глубина ряда; ножка: от года по кромке к блоку, затем вниз
    const rows=[],stems=[],cands=[];
    for(let r=0;r<maxRows;r++)for(let s=-maxShift;s<=maxShift;s+=12)cands.push({r,s,cost:Math.abs(s)+r*45});
    cands.sort((a,b)=>a.cost-b.cost);
    items.forEach(it=>{it.row=-1;
      for(const {r,s} of cands){rows[r]=rows[r]||[];const bx=it.x+s,[a,b]=block(it,bx);
        if(a<PLOT_L-8||b>W-6)continue;
        if(rows[r].some(([c,d])=>b>c&&a<d))continue;
        if(r>0&&rows.slice(0,r).some(row=>row.some(([c,d])=>bx>c-3&&bx<d+3)))continue;
        if(stems.some(st=>st.row>r&&st.x>a-3&&st.x<b+3))continue;
        rows[r].push([a,b]);stems.push({x:bx,row:r});it.row=r;it.bx=bx;break;}
    });
    return Math.max(1,rows.filter(r=>r&&r.length).length);
  }
  function wrap(title,max,cls){
    const lines=[''];title.split(' ').forEach(w=>{const c=(lines[lines.length-1]+' '+w).trim();if(measure(cls,c)>max&&lines[lines.length-1])lines.push(w);else lines[lines.length-1]=c;});
    return lines.slice(0,2).map((t,i)=>{const s=i===1&&lines.length>2?t+'…':t;return {t:s,w:measure(cls,s)};});
  }
  const W_ROW=56,E_ROW=24;
  function planWorks(R,maxRows){
    const vis=V.works.filter(w=>!R||!R.works||R.works.has(w.id)).sort((a,b)=>a.year-b.year);
    vis.forEach(it=>{it.x=X(it.year);it.row=-1;});
    const cand=vis.filter(it=>R||it.key).sort((a,b)=>((b.id===(R&&R.primary))-(a.id===(R&&R.primary)))||(b.key-a.key)||(a.year-b.year));
    cand.forEach(it=>{const cls=it.kind==='work'?'work-title':'concept-title',t=R?`${it.title}, ${it.year}`:it.title;it.lines=wrap(t,dense?150:170,cls);it.w=Math.max(...it.lines.map(l=>l.w));});
    const rows=pins(cand,{maxRows,maxShift:R?210:84,block:(it,bx)=>[bx-Math.max(it.w,20)/2-8,bx+Math.max(it.w,20)/2+8]});
    return {items:vis,rows:cand.some(c=>c.row>=0)?rows:0};
  }
  function planEvents(R,maxRows){
    const vis=[...V.events].sort((a,b)=>a.year-b.year);
    vis.forEach(e=>{e.x=X(e.year);e.row=-1;e.w=measure('event-text',`${e.year} ${e.label}`);});
    const order=[...vis].sort((a,b)=>((R&&R.events&&R.events.has(b.id))-(R&&R.events&&R.events.has(a.id)))||(a.year-b.year));
    // кольцо стоит точно на годе (ножка не нужна); подпись справа или слева, ряды — по «цене»
    const rows=[];order.forEach(e=>{e.row=-1;
      for(let r=0;r<maxRows&&e.row<0;r++)for(const side of [1,-1]){rows[r]=rows[r]||[];
        const a=side>0?e.x-7:e.x-12-e.w-6,b=side>0?e.x+12+e.w+6:e.x+7;
        if(a<PLOT_L-8||b>W-6||rows[r].some(([c,d])=>b>c&&a<d))continue;rows[r].push([a,b]);e.row=r;e.side=side;e.bx=e.x;break;}});
    return {items:vis,rows:Math.max(1,rows.filter(r=>r&&r.length).length)};
  }

  function layoutBands(need){
    const on=ORDER.filter(k=>state.on[k]),free=BODY-(ORDER.length-on.length)*COLL,sw=on.reduce((a,k)=>a+META[k].w,0),h={};
    ORDER.forEach(k=>h[k]=state.on[k]?Math.min(META[k].max,free*META[k].w/sw):COLL);
    ORDER.forEach(k=>{if(state.on[k]&&need[k]!=null)h[k]=k==='people'?Math.max(h[k],need[k]):need[k];});
    if(state.on.people)h.people=Math.max(h.people,h.people+BODY-ORDER.reduce((a,k)=>a+h[k],0));
    let y=TOP;const b={};ORDER.forEach(k=>{b[k]={key:k,top:y,bot:y+h[k],collapsed:!state.on[k],...META[k]};y+=h[k];});return b;
  }

  function draw(){
    const ae=document.activeElement,focusId=ae&&ae.dataset?(ae.dataset.person||ae.dataset.entity):null;
    svg.innerHTML='';
    const cw=Math.round(svg.getBoundingClientRect().width)||1160;W=Math.max(900,cw);PLOT_R=W-26;
    const AXIS_H=dense?84:46;
    const top=svg.getBoundingClientRect().top+scrollY;BODY=Math.round(Math.min(760,Math.max(440,innerHeight-top-AXIS_H-TOP-96)));
    if(gutter)gutter.style.width=PLOT_L+'px';
    const R=related();

    const LANES=packPeople(dense?4:22),laneMin=dense?27:56;
    const wp=planWorks(R,dense?(R?4:3):2),ep=planEvents(R,dense?4:2);
    const need={people:LANES*laneMin+34,works:22+Math.max(wp.rows,1)*W_ROW+6,events:12+Math.max(ep.rows,1)*E_ROW+4};
    const bands=layoutBands(need),H=bands.works.bot+AXIS_H;
    svg.setAttribute('viewBox',`0 0 ${W} ${H}`);

    const defs=S('defs',{});
    const duo=S('filter',{id:'duo'});duo.append(S('feColorMatrix',{type:'saturate',values:'0'}));
    const ct=S('feComponentTransfer',{});[['R','.16 .95'],['G','.13 .92'],['B','.10 .84']].forEach(([c,v])=>ct.append(S('feFunc'+c,{type:'table',tableValues:v})));duo.append(ct);defs.append(duo);
    const glow=S('filter',{id:'glow',x:'-60%',y:'-60%',width:'220%',height:'220%'});
    glow.append(S('feGaussianBlur',{in:'SourceGraphic',stdDeviation:'2.2',result:'b'}));
    const fm=S('feMerge',{});fm.append(S('feMergeNode',{in:'b'}));fm.append(S('feMergeNode',{in:'SourceGraphic'}));glow.append(fm);defs.append(glow);
    svg.append(defs);
    const L={};['grid','bands','eras','events','threads','works','people','axis'].forEach(k=>{L[k]=S('g',{});svg.append(L[k]);});
    const hit=(g,id,label)=>{g.setAttribute('data-entity',id);g.setAttribute('tabindex','0');g.setAttribute('role','button');g.setAttribute('aria-label',label);g.setAttribute('aria-pressed',String(state.sel===id));g.classList.add('entity');};

    /* шаг шкалы: подписи не ближе ~70 px */
    const pxYear=(PLOT_R-PLOT_L)/(Y1-Y0),step=[5,10,25,50,100].find(s=>s*pxYear>=70)||100;
    const ticks=[];for(let y=Math.ceil(Y0/step)*step;y<=Y1;y+=step)ticks.push(y);
    ticks.forEach(y=>L.grid.append(S('line',{x1:X(y),y1:TOP,x2:X(y),y2:bands.works.bot,class:'time-grid'})));
    ORDER.forEach(k=>{const b=bands[k];L.bands.append(S('line',{x1:PLOT_L-6,y1:b.top,x2:PLOT_R,y2:b.top,class:'band-sep'}));
      if(b.collapsed)L.bands.append(S('text',{x:PLOT_L+4,y:b.top+18,class:'collapsed-note'},`${b.count} · линза свёрнута`));});

    /* люди: геометрия */
    const bp=bands.people,laneH=(bp.bot-bp.top-30)/LANES;
    const RY=dense?4:Math.min(27,laneH*.4),RX=dense?4:RY*.82,BAND=dense?Math.min(18,laneH*.66):Math.min(24,Math.max(14,laneH*.46));
    V.people.forEach(p=>{p.y=bp.top+20+(p.lane+.5)*laneH;});

    /* эпохи — заливка и подпись; кликабельны */
    const be=bands.eras;
    if(!be.collapsed)V.eras.forEach(e=>{const x1=clampX(X(e.from)),x2=clampX(X(e.to)),act=R&&R.era===e,g=S('g',{class:R&&!act?'era-dim':''});L.eras.append(g);
      hit(g,e.id,`Эпоха: ${e.label}, ${e.from}–${e.to}`);
      g.append(S('rect',{x:x1,y:be.top+1,width:Math.max(0,x2-x1-1),height:be.bot-be.top-2,class:'era-fill',opacity:act?.17:.06}));
      const t=S('text',{x:(x1+x2)/2,y:(be.top+be.bot)/2+5,class:'era-text'+(act?' era-active':'')},e.label);g.append(t);
      if(t.getComputedTextLength()>x2-x1-12)t.remove();});

    /* события: булавки — кольцо и «год событие» одним блоком */
    const bv=bands.events;
    if(!bv.collapsed){
      ep.items.forEach(e=>{const act=!R||!R.events||R.events.has(e.id),g=S('g',{class:act?'':'dim-soft'});L.events.append(g);hit(g,e.id,`Событие: ${e.year}, ${e.label}`);
        g.append(S('title',{},`${e.year} — ${e.label}`));
        const ry=bv.top+12+Math.max(0,e.row)*E_ROW;
        if(e.row<0){g.append(S('circle',{cx:e.x,cy:ry,r:3.5,class:'event-ring'}));g.append(S('rect',{x:e.x-7,y:ry-7,width:14,height:14,fill:'transparent'}));return;}
        g.append(S('circle',{cx:e.bx,cy:ry,r:5,class:'event-ring'+(state.sel===e.id?' on':'')}));g.append(S('circle',{cx:e.bx,cy:ry,r:1.8,fill:'var(--history)'}));
        const t=S('text',{x:e.side>0?e.bx+12:e.bx-12,y:ry+4.5,class:'event-text','text-anchor':e.side>0?'start':'end'});t.append(S('tspan',{class:'event-year'},e.year+' '));t.append(document.createTextNode(e.label));g.append(t);});}
    else V.events.forEach(e=>L.events.append(S('rect',{x:X(e.year)-.75,y:bv.top+COLL/2-4,width:1.5,height:8,class:'event-tick'})));

    /* люди: ленты Пристли; цвет — роль в выборе */
    if(bp.collapsed)V.people.forEach(p=>L.people.append(S('rect',{x:p.bx,y:bp.top+COLL-7,width:p.dx-p.bx,height:3,rx:1.5,fill:'var(--people)',opacity:.35})));
    else V.people.forEach(p=>{
      const col=R&&R.people.get(p.id),sel=state.sel===p.id||(R&&R.type==='work'&&R.obj.author===p.id),on=!R||!!col;
      const g=S('g',{class:'person'+(on?'':' dim'),'data-person':p.id,tabindex:0,role:'button','aria-pressed':String(state.sel===p.id),'aria-label':`${p.name}, ${p.birth}–${p.death}`});L.people.append(g);
      g.append(S('title',{},`${p.name}, ${p.birth}–${p.death}`));
      g.append(S('rect',{x:p.bx,y:p.y-BAND/2,width:Math.max(BAND,p.dx-p.bx),height:BAND,rx:BAND/2,class:'lifeline',fill:col||'var(--graph-ink-secondary)','fill-opacity':col?(col===C.neutral?.14:.2):(dense?.17:.09)}));
      const name=S('text',{x:p.bx+(dense?10:RX+8),y:p.y+(dense?4.6:5.4),class:(col&&col!==C.neutral?'sel-name':'person-name'),...(col&&col!==C.neutral?{style:`fill:${col}`}:{})},p.label);g.append(name);
      const yr=S('text',{y:p.y+4.3,class:'person-years'},`${p.birth}–${p.death}`);if(!dense)g.append(yr);
      if(p.yearsIn){yr.setAttribute('x',p.dx-BAND/2);yr.setAttribute('text-anchor','end');}else yr.setAttribute('x',Math.max(p.dx,p.bx+RX+8+name.getComputedTextLength())+8);
      if(dense){g.append(S('circle',{cx:p.bx+BAND/2,cy:p.y,r:2.2,class:'life-dot',...(col?{style:`fill:${col}`}:{})}));
        if(sel){const r=13;g.append(S('circle',{cx:p.bx,cy:p.y,r:r+3,fill:'none',stroke:C.sel,'stroke-width':1.6,filter:'url(#glow)'}));
          g.append(S('circle',{cx:p.bx,cy:p.y,r,class:'medallion-ring'}));
          if(p.portrait){const cp=S('clipPath',{id:'clip-'+p.id});cp.append(S('circle',{cx:p.bx,cy:p.y,r}));defs.append(cp);
            g.append(S('image',{href:'../graph-f02/assets/'+p.portrait,x:p.bx-r,y:p.y-r,width:r*2,height:r*2,preserveAspectRatio:'xMidYMid slice','clip-path':`url(#clip-${p.id})`,filter:'url(#duo)'}));}
          else g.append(S('text',{x:p.bx,y:p.y+3.5,class:'monogram',style:'font-size:10px'},mono(p)));
          name.setAttribute('x',p.bx+r+7);}
        g.append(S('rect',{x:p.bx-6,y:p.y-BAND/2-3,width:p.dx-p.bx+12,height:BAND+6,rx:4,class:'focus-ring'}));
        p.labelEnd=+name.getAttribute('x')+name.getComputedTextLength();return;}
      if(sel)g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX+4,ry:RY+4,fill:'none',stroke:C.sel,'stroke-width':1.8,'stroke-opacity':.85,filter:'url(#glow)'}));
      g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX+7,ry:RY+7,class:'focus-ring'}));
      g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX,ry:RY,class:'medallion-ring',...(col&&col!==C.neutral&&!sel?{style:`stroke:${col};stroke-width:1.6`}:{})}));
      if(p.portrait){const cp=S('clipPath',{id:'clip-'+p.id});cp.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX,ry:RY}));defs.append(cp);
        g.append(S('image',{href:'../graph-f02/assets/'+p.portrait,x:p.bx-RX,y:p.y-RY,width:RX*2,height:RY*2,preserveAspectRatio:'xMidYMid slice','clip-path':`url(#clip-${p.id})`,filter:'url(#duo)'}));
        g.append(S('ellipse',{cx:p.bx,cy:p.y,rx:RX,ry:RY,fill:'none',stroke:col&&col!==C.neutral?col:'var(--graph-ink-secondary)','stroke-opacity':.85,'stroke-width':col&&col!==C.neutral?1.6:1}));}
      else g.append(S('text',{x:p.bx,y:p.y+RY*.27,class:'monogram',style:`font-size:${(RY*.72).toFixed(1)}px`},mono(p)));
      p.labelEnd=p.bx+RX+8+name.getComputedTextLength();
    });

    /* влияния: только линии между людьми. Без выбора — тонкие, если их немного; при выборе — его прямые связи цветом роли */
    const mids={},pv=new Set(V.people.map(p=>p.id));
    const shown=bp.collapsed?[]:R?R.edges:(V.influences.length>15?[]:V.influences.map(e=>({e,color:null})));
    const slot={};const order=(key,arr)=>arr.forEach((x,k)=>slot[key(x)]=k);
    V.people.forEach(p=>{order(x=>'in'+x.e.a+'-'+x.e.b,shown.filter(x=>x.e.b===p.id).sort((a,b)=>byId[a.e.a].y-byId[b.e.a].y));
      order(x=>'out'+x.e.a+'-'+x.e.b,shown.filter(x=>x.e.a===p.id).sort((a,b)=>byId[a.e.b].y-byId[b.e.b].y));});
    shown.forEach(({e,color})=>{if(!pv.has(e.a)||!pv.has(e.b))return;
      const s=byId[e.a],t=byId[e.b],si=slot['out'+e.a+'-'+e.b]*9,ti=slot['in'+e.a+'-'+e.b]*9,down=t.y>s.y,via=e.via||Math.min(s.death-5,s.birth+40);
      const A={x:Math.min(Math.max(X(via),s.labelEnd+10)+si,s.dx-8),y:s.y+(down?BAND/2:-BAND/2)},bx0=Math.max(X(t.birth+22),t.labelEnd+14)+ti;
      const B=bx0>t.dx-8?{x:t.dx-3,y:t.y+(down?-BAND/2+5:BAND/2-5)}:{x:bx0,y:t.y+(down?-BAND/2:BAND/2)};
      const dx=B.x-A.x,dy=B.y-A.y,P=[A,{x:A.x+dx*.5,y:A.y+dy*.15},{x:B.x-dx*.15,y:B.y-dy*.65},B];mids[e.a+'-'+e.b]=cub(P,.5);
      const d=`M${A.x},${A.y} C${P[1].x},${P[1].y} ${P[2].x},${P[2].y} ${B.x},${B.y}`;
      L.threads.append(S('path',{d,class:color?'thread-on':'thread-quiet',...(color?{stroke:color}:{}),...(e.verified===false?{'stroke-dasharray':'4 3'}:{})}));
      if(color)L.threads.append(S('circle',{cx:B.x,cy:B.y,r:2.4,fill:color}));
    });

    /* труды: булавки; цвет — цвет автора в выборе */
    const bw=bands.works;
    if(bw.collapsed)wp.items.forEach(it=>L.works.append(S('rect',{x:it.x-.75,y:bw.top+COLL/2-4,width:1.5,height:8,class:'work-tick'})));
    else{const rail=bw.top+9;
      wp.items.forEach(it=>{
        const col=R?(R.people.get(it.author)||C.neutral):null,g=S('g',{});L.works.append(g);
        hit(g,it.id,`${KIND[it.kind]}: «${it.title}», ${it.year}${byId[it.author]?' — '+byId[it.author].name:''}`);
        g.append(S('title',{},`${it.title}, ${it.year} — ${byId[it.author]?byId[it.author].name:''}`));
        g.append(S('rect',{x:it.x-.75,y:rail-4,width:1.5,height:8,class:'work-tick',...(col?{style:`fill:${col}`}:{})}));
        if(it.row<0){g.append(S('rect',{x:it.x-5,y:rail-7,width:10,height:14,fill:'transparent'}));return;}
        const x=it.bx,iy=bw.top+22+it.row*W_ROW,cy=iy+10,c=col||'var(--texts)';
        g.append(S('path',{d:`M${it.x} ${rail+4} L${x} ${rail+9} V${iy-2}`,class:'stem',...(col?{style:`stroke:${col}`}:{})}));
        if(it.kind==='work'){g.append(S('rect',{x:x-8,y:iy,width:16,height:20,rx:1.5,class:'work-mark',style:`stroke:${c}`}));
          g.append(S('rect',{x:x-8,y:iy,width:4,height:20,rx:1.2,fill:c,'fill-opacity':.55}));}
        else if(it.kind==='position')g.append(S('path',{d:`M${x} ${cy-9} L${x+9} ${cy+7} L${x-9} ${cy+7} Z`,class:'concept-mark',style:`stroke:${col||'var(--ideas)'}`}));
        else if(it.kind==='argument')g.append(S('path',{d:`M${x-8} ${cy-8} H${x+8} V${cy+8} H${x-8} Z M${x-4} ${cy} H${x+4} M${x+1} ${cy-3} L${x+4} ${cy} L${x+1} ${cy+3}`,class:'concept-mark',style:`stroke:${col||'var(--ideas)'}`}));
        else{g.append(S('path',{d:`M${x} ${cy-9} L${x+9} ${cy} L${x} ${cy+9} L${x-9} ${cy} Z`,class:'concept-mark',style:`stroke:${col||'var(--ideas)'}`}));g.append(S('circle',{cx:x,cy,r:1.8,fill:col||'var(--ideas)'}));}
        if(R&&R.primary===it.id)g.append(S('circle',{cx:x,cy,r:15,fill:'none',stroke:c,'stroke-width':1.6,'stroke-opacity':.6,filter:'url(#glow)'}));
        const t=S('text',{x,y:iy+36,class:(col?'work-active-title':(it.kind==='work'?'work-title':'concept-title')),'text-anchor':'middle',...(col?{style:`fill:${col}`}:{})});
        it.lines.forEach((ln,k)=>t.append(S('tspan',{x,dy:k?15:0},ln.t)));g.append(t);
      });}

    /* ось: линия, деления, годы */
    const ay=bw.bot;
    L.axis.append(S('line',{x1:PLOT_L-6,y1:ay,x2:PLOT_R,y2:ay,stroke:'var(--graph-ink)','stroke-opacity':.5,'stroke-width':.8}));
    ticks.forEach(y=>{const x=X(y);L.axis.append(S('line',{x1:x,y1:ay,x2:x,y2:ay+6,stroke:'var(--graph-ink)','stroke-opacity':.5,'stroke-width':.8}));L.axis.append(S('text',{x,y:ay+24,class:'axis-year'},y));});
    /* обзорная шкала — окно времени (фильтр «Время»): весь период и выбранная рамка */
    if(dense){const oy=ay+56,[A0,A1]=DS.range,OX=y=>PLOT_L+(y-A0)/(A1-A0)*(PLOT_R-PLOT_L),g=S('g',{class:'overview'});L.axis.append(g);
      g.append(S('text',{x:PLOT_L-10,y:oy+4,class:'overview-label','text-anchor':'end'},'Окно времени'));
      g.append(S('line',{x1:PLOT_L,y1:oy,x2:PLOT_R,y2:oy,class:'overview-rail'}));
      for(let y=Math.ceil(A0/50)*50;y<=A1;y+=50){g.append(S('line',{x1:OX(y),y1:oy-3,x2:OX(y),y2:oy+3,class:'overview-rail'}));g.append(S('text',{x:OX(y),y:oy+16,class:'overview-year'},y));}
      ALL.people.forEach(p=>g.append(S('line',{x1:OX(p.birth),y1:oy-1.5,x2:OX(p.death),y2:oy-1.5,class:'overview-life'})));
      const w0=OX(Y0),w1=OX(Y1);g.append(S('rect',{x:w0,y:oy-8,width:w1-w0,height:16,rx:3,class:'overview-window'}));
      [w0,w1].forEach(x=>g.append(S('rect',{x:x-3,y:oy-10,width:6,height:20,rx:2,class:'overview-handle'})));}

    renderGutter(bands,H);renderNote(R);renderDesk(R);renderTools();
    window.deskLayout={bands,H,people:byId,mids,state,BODY,svgTop:top,lanes:LANES,labeledWorks:wp.items.filter(i=>i.row>=0).length,labeledEvents:ep.items.filter(i=>i.row>=0).length};
    if(focusId){const f=svg.querySelector(`[data-person="${focusId}"],[data-entity="${focusId}"]`);if(f)f.focus();}
    if(!reduce&&svg.animate)svg.animate([{opacity:.55},{opacity:1}],{duration:180,easing:'ease-out'});
  }

  // карточки на столе: цитата автора (с источником) и труды «к чтению» — для философа и труда
  function renderDesk(R){
    const top=document.getElementById('card-top'),under=document.getElementById('card-under');
    const lines=(el,arr)=>{if(!el)return;el.querySelectorAll('.t').forEach(t=>t.remove());arr.forEach((x,i)=>{const d=document.createElement('div');d.className='t'+(i===0?' big':'');d.textContent=x;if(i===0&&el===top)d.style.marginTop='6px';el.append(d);});el.hidden=!arr.length;};
    const author=R&&(R.type==='person'?R.obj.id:R.type==='work'?R.obj.author:null),n=author&&notes.find(x=>x.about===author);
    lines(top,n?[...n.lines,'— '+n.cite]:[]);
    const ws=author?ALL.works.filter(w=>w.author===author&&w.kind==='work').sort((a,b)=>b.key-a.key).slice(0,3):[];
    lines(under,ws.length?['К чтению:',...ws.map(w=>`«${w.title}», ${w.year}`)]:[]);
    const ed=document.querySelector('.edition-note');
    if(ed)ed.textContent=dense?`Синтетический набор для проверки плотности · ${plural(ALL.people.length,F.people)} · ${plural(ALL.works.length,F.works)} · ${plural(ALL.influences.length,F.links)}`:'Демонстрационные данные';
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

  /* сноска «Выбрано» — словами объясняет подсветку и служит легендой цветов */
  function renderNote(R){
    if(!selnote)return;
    const h1=document.querySelector('.scene h1');
    if(!R){const more=V.influences.length>15?` Связей ${V.influences.length} — они показываются по выбору.`:'';
      selnote.innerHTML=`<div class="kicker">Как читать</div><p class="hint">Нажмите на философа, труд, событие или эпоху — проявится всё, что с ними связано.${more} Esc или клик по полю — снять выбор.</p>`;
      if(h1)h1.textContent=DS.title;return;}
    const sw=c=>`<i class="sw" style="background:${c}"></i>`,cut=(a,n)=>a.length>n?a.slice(0,n).join(', ')+` и ещё ${a.length-n}`:a.join(', ');
    const names=col=>[...R.people].filter(([,c])=>c===col).map(([id])=>byId[id]).sort((a,b)=>a.birth-b.birth).map(p=>p.short);
    const nw=R.works?R.works.size:0,li=[];let kicker,title,sub='';
    if(R.type==='person'){const p=R.obj;kicker='Философ';title=p.name;sub=`${p.birth}–${p.death}`;
      const t=names(C.teacher),s=names(C.student),ws=ALL.works.filter(w=>R.works.has(w.id)&&w.kind==='work');
      if(t.length)li.push(`${sw(C.teacher)}<span>Учителя: ${cut(t,3)}</span>`);
      if(s.length)li.push(`${sw(C.student)}<span>Ученики: ${cut(s,3)}</span>`);
      li.push(`${sw(C.sel)}<span>${nw?`Его труды и идеи: ${nw}${ws.length?`, главный — «${(ws.find(w=>w.key)||ws[0]).title}»`:''}`:'Трудов в выборке нет'}</span>`);
      if(R.era)li.push(`<i class="k k-era"></i><span>Эпоха: ${R.era.label}</span>`);
      if(R.edges.some(x=>x.e.verified===false))li.push(`<i class="k k-unv"></i><span>Пунктир — связь достроена LLM, не проверена</span>`);}
    else if(R.type==='work'){const w=R.obj,p=byId[w.author];kicker=KIND[w.kind];title=`«${w.title}»`;sub=String(w.year);
      li.push(`${sw(C.sel)}<span>Автор: ${p.name}, ${p.birth}–${p.death}</span>`);
      if(nw>1)li.push(`${sw(C.sel)}<span>Ещё у автора: ${plural(nw-1,F.works)}</span>`);
      if(R.era)li.push(`<i class="k k-era"></i><span>Эпоха: ${R.era.label}</span>`);}
    else{const o=R.obj;kicker=R.type==='era'?'Эпоха':R.type==='event'?'Событие':(o.kind==='school'?'Школа':'Направление');
      title=o.label;sub=R.type==='era'?`${o.from}–${o.to}`:R.type==='event'?String(o.year):'';
      li.push(`<span class="legend-names">${R.legend.map(([c,n])=>`<b>${sw(c)}${n}</b>`).join(' ')}</span>`);
      li.push(`<i class="k k-works"></i><span>${R.type==='event'?'Труды ±10 лет':'Их труды'}: ${nw} · цвет — автор</span>`);}
    selnote.innerHTML=`<div class="kicker">Выбрано · ${kicker}</div><div class="selname">${title} <span>${sub}</span></div><ul>${li.map(x=>`<li>${x}</li>`).join('')}</ul>`;
    if(h1)h1.textContent=title.replace(/[«»]/g,'');
  }

  /* панель поиска и фильтров — пока кадр: состояние берётся из адреса (?q= &open= &groups= &from= &to= …) */
  function renderTools(){
    const host=document.querySelector('.tools');if(!host)return;
    const q=(Q.get('q')||'').trim(),open=Q.get('open');
    const gsel=k=>ALL.groups.filter(g=>g.kind===k&&filter.groups.includes(g.id)).map(g=>g.label);
    const chip=(key,label,val)=>`<button type="button" class="chip${val?' on':''}${open===key?' open':''}" data-filter="${key}">${label}${val?`: <b>${val}</b><span class="x" aria-label="Снять">×</span>`:' <span class="caret">▾</span>'}</button>`;
    const time=filter.from||filter.to?`${Y0}–${Y1}`:'';
    const kinds=(lbl,arr)=>arr.map(k=>lbl[k]).join(', ');
    let html=`<label class="search${q?' active':''}"><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.6"/><path d="M10.4 10.4 L14 14"/></svg><input type="search" placeholder="Найти философа, труд, понятие, событие" value="${q}" aria-label="Поиск по карте"><kbd>/</kbd></label>`;
    html+=`<div class="chips" role="group" aria-label="Фильтры">${chip('time','Время',time)}${chip('dir','Направление',gsel('direction').join(', '))}${chip('school','Школа',gsel('school').join(', '))}${chip('role','Роль',kinds(DS.roleLabels||{},filter.roles))}${chip('kind','Вид',kinds(DS.kindLabels||{},filter.kinds))}${chip('ekind','События',kinds(DS.eventKindLabels||{},filter.ekinds))}${chip('verified','Связи',filter.verified?'только проверенные':'')}</div>`;
    html+=`<div class="shown">${filtered?`Показано ${V.people.length} из ${plural(ALL.people.length,['философа','философов','философов'])} · ${V.works.length} из ${plural(ALL.works.length,['труда','трудов','трудов'])}`:`${plural(ALL.people.length,F.people)} · ${plural(ALL.works.length,F.works)} · ${plural(ALL.influences.length,F.links)}`}</div>`;
    // выпадающий список поиска: по типам; найденное вне фильтра — пометка
    if(q){const m=s=>s.toLowerCase().includes(q.toLowerCase()),inV=new Set([...V.people,...V.works].map(x=>x.id));
      const grp=(title,arr,fmt)=>arr.length?`<div class="dd-group">${title}</div>${arr.slice(0,4).map(fmt).join('')}`:'';
      const row=(icon,main,sub,id)=>`<div class="dd-row${inV.has(id)||!id?'':' out'}"><span class="dd-ico">${icon}</span><span class="dd-main">${main}</span><span class="dd-sub">${sub}${id&&!inV.has(id)?' · скрыт фильтром':''}</span></div>`;
      const hl=s=>s.replace(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')})`,'i'),'<mark>$1</mark>');
      html+=`<div class="dropdown search-dd" role="listbox">${
        grp('Философы',ALL.people.filter(p=>m(p.name)),p=>row('●',hl(p.name),`${p.birth}–${p.death}`,p.id))+
        grp('Труды',ALL.works.filter(w=>w.kind==='work'&&m(w.title)),w=>row('▯',hl(`«${w.title}»`),`${byId[w.author].short}, ${w.year}`,w.id))+
        grp('Понятия, позиции, аргументы',ALL.works.filter(w=>w.kind!=='work'&&m(w.title)),w=>row('◇',hl(w.title),`${KIND[w.kind]} · ${byId[w.author].short}`,w.id))+
        grp('События',ALL.events.filter(e=>m(e.label)),e=>row('◉',hl(e.label),String(e.year),null))+
        grp('Эпохи и направления',[...ALL.eras.filter(e=>m(e.label)),...ALL.groups.filter(g=>m(g.label))],o=>row('▭',hl(o.label),o.from?`${o.from}–${o.to}`:(o.kind==='school'?'школа':'направление'),null))
      }<div class="dd-foot">↑↓ — выбрать · Enter — показать на карте</div></div>`;}
    // открытое меню фильтра: варианты с количеством
    if(open==='dir'||open==='school'){const kind=open==='dir'?'direction':'school';
      html+=`<div class="dropdown filter-dd" data-for="${open}">${ALL.groups.filter(g=>g.kind===kind).map(g=>`<label class="dd-check"><input type="checkbox"${filter.groups.includes(g.id)?' checked':''}><span>${g.label}</span><span class="dd-count">${g.members.length}</span></label>`).join('')}<div class="dd-foot">Несколько значений — «или»</div></div>`;}
    host.innerHTML=html;
    const dd=host.querySelector('.filter-dd');if(dd){const c=host.querySelector(`.chip[data-filter="${open}"]`),hb=host.getBoundingClientRect(),cb=c.getBoundingClientRect();dd.style.left=(cb.left-hb.left)+'px';dd.style.top=(cb.bottom-hb.top+6)+'px';}
  }

  /* выбор: клик/Enter по философу, труду, событию, эпохе; клик по полю или Esc — снять */
  const pick=t=>{const g=t.closest&&t.closest('[data-person],[data-entity]');return g?(g.dataset.person||g.dataset.entity):null;};
  svg.addEventListener('click',ev=>{state.sel=pick(ev.target);draw();});
  svg.addEventListener('keydown',ev=>{const id=pick(ev.target);if(id&&(ev.key==='Enter'||ev.key===' ')){ev.preventDefault();state.sel=id;draw();}});
  document.addEventListener('keydown',ev=>{if(ev.key==='Escape'&&state.sel){state.sel=null;draw();}});
  window.desk={state,draw,select:id=>{state.sel=id;draw();},toggleLens:k=>{state.on[k]=!state.on[k];draw();},visible:V};
  let rz;addEventListener('resize',()=>{clearTimeout(rz);rz=setTimeout(draw,120);});
  document.fonts.ready.then(draw);
  draw();
})();
