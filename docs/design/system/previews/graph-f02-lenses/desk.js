/* Предметы на столе философа + рукописные пометки на листе. Статичный кадр, всё декоративно (aria-hidden). */
(function(){
  const NS='http://www.w3.org/2000/svg';
  const S=(t,a,txt)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(txt!=null)e.textContent=txt;return e;};
  const mount=(id,vb,build)=>{const host=document.getElementById(id);if(!host)return;const svg=S('svg',{viewBox:vb});build(svg);host.append(svg);};
  // детерминированный «случай» — кадр одинаков при каждом рендере
  let seed=7;const rnd=()=>{seed=(seed*16807)%2147483647;return (seed-1)/2147483646;};

  /* ---------- Стопка книг с лентами ---------- */
  function book(g,{cx,cy,w,h,rot,cover,spine,gilt=true,plaque=false}){
    const b=S('g',{transform:`translate(${cx} ${cy}) rotate(${rot})`});
    const x=-w/2,y=-h/2;
    b.append(S('rect',{x:x+7,y:y+11,width:w,height:h,rx:4,fill:'#24140a'}));           // задняя крышка
    b.append(S('rect',{x:x+4,y:y+7,width:w-1,height:h-1,rx:2,fill:'#e6d8b6'}));          // блок страниц
    for(let i=0;i<4;i++){b.append(S('path',{d:`M${x+8} ${y+h+1.6+i*1.5} H${x+w+3}`,stroke:'#b39f78','stroke-width':.55}));
                         b.append(S('path',{d:`M${x+w+1.4+i*1.5} ${y+10} V${y+h+4}`,stroke:'#b39f78','stroke-width':.55}));}
    b.append(S('rect',{x,y,width:w,height:h,rx:4,fill:cover,filter:'url(#leather)'}));    // крышка
    b.append(S('rect',{x,y,width:20,height:h,rx:3,fill:spine,filter:'url(#leather)'}));   // корешок
    [.18,.38,.62,.82].forEach(t=>b.append(S('path',{d:`M${x} ${y+h*t} h20`,stroke:'#c79a4a','stroke-opacity':.7,'stroke-width':1.3})));
    if(gilt)b.append(S('rect',{x:x+30,y:y+10,width:w-42,height:h-20,rx:2,fill:'none',stroke:'#c79a4a','stroke-opacity':.42,'stroke-width':1}));
    if(plaque){b.append(S('rect',{x:x+w/2-30,y:y+h/2-16,width:72,height:30,rx:2,fill:'#8a4a2a',filter:'url(#leather)'}));
               b.append(S('path',{d:`M${x+w/2-22} ${y+h/2-3} h56 M${x+w/2-16} ${y+h/2+5} h44`,stroke:'#e2c27a','stroke-opacity':.8,'stroke-width':1.2}));}
    // мягкий блик от лампы (верхний левый угол крышки)
    b.append(S('rect',{x,y,width:w,height:h,rx:4,fill:'url(#coverSheen)',opacity:.55}));
    g.append(b);
  }
  mount('books','0 0 350 300',svg=>{
    const d=S('defs',{});const lg=S('linearGradient',{id:'coverSheen',x1:'0',y1:'0',x2:'1',y2:'1'});
    lg.append(S('stop',{offset:'0%','stop-color':'#ffd9a0','stop-opacity':.35}));lg.append(S('stop',{offset:'55%','stop-color':'#ffd9a0','stop-opacity':0}));d.append(lg);svg.append(d);
    // ленты-закладки — выходят из книг и тянутся к листу
    svg.append(S('path',{d:'M238 208 C262 236 280 250 318 262',stroke:'#2f5a3c','stroke-width':8,fill:'none'}));
    book(svg,{cx:168,cy:158,w:258,h:182,rot:5,cover:'#4d2e1b',spine:'#3a2213'});
    book(svg,{cx:176,cy:146,w:222,h:162,rot:-7,cover:'#2f402f',spine:'#223024'});
    svg.append(S('path',{d:'M206 214 C236 246 262 262 300 286',stroke:'#a8371f','stroke-width':8.5,fill:'none'}));
    book(svg,{cx:158,cy:132,w:198,h:144,rot:10,cover:'#6e2a1e',spine:'#511d14',plaque:true});
  });

  /* ---------- Чернильница и перо ---------- */
  mount('inkwell','0 0 300 290',svg=>{
    // перо лежит по диагонали и указывает кончиком на лист (влево-вниз)
    const P0={x:16,y:270},P1={x:196,y:36},dx=P1.x-P0.x,dy=P1.y-P0.y,L=Math.hypot(dx,dy),u={x:dx/L,y:dy/L},n={x:-u.y,y:u.x};
    const at=(t,o)=>({x:P0.x+dx*t+n.x*o,y:P0.y+dy*t+n.y*o});
    const a=at(.3,0),c1=at(.56,-27),c2=at(.86,-22),tip=at(1,0),c3=at(.86,15),c4=at(.56,17);
    const g=S('g',{});
    g.append(S('path',{d:`M${a.x},${a.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${tip.x},${tip.y} C${c3.x},${c3.y} ${c4.x},${c4.y} ${a.x},${a.y} Z`,fill:'#efe6d3',stroke:'#b9a985','stroke-width':.8}));
    for(let t=.33;t<.97;t+=.022){const w1=-(t<.6?27*(t-.3)/.3:27-15*(t-.6)/.4)*.92,w2=(t<.6?17*(t-.3)/.3:17-9*(t-.6)/.4)*.92;
      const s=at(t,0),e1=at(t+.05,w1),e2=at(t+.05,w2);
      g.append(S('path',{d:`M${s.x},${s.y} L${e1.x},${e1.y} M${s.x},${s.y} L${e2.x},${e2.y}`,stroke:'#b8a687','stroke-width':.5,'stroke-opacity':.75}));}
    const s0=at(0,0),s9=at(.98,0);
    g.append(S('path',{d:`M${s0.x},${s0.y} L${s9.x},${s9.y}`,stroke:'#cdb88e','stroke-width':2.2,'stroke-linecap':'round'}));
    const nib=at(.07,0);
    g.append(S('path',{d:`M${s0.x},${s0.y} L${nib.x+n.x*2.6},${nib.y+n.y*2.6} L${nib.x-n.x*2.6},${nib.y-n.y*2.6} Z`,fill:'#2a1d12'}));
    svg.append(g);
    // чернильница: гранёное стекло + латунный ворот + чернила с бликом
    const ink=S('g',{transform:'translate(208 92) rotate(9)'});
    ink.append(S('rect',{x:-56,y:-56,width:112,height:112,rx:14,fill:'#1f2e2c','fill-opacity':.72,stroke:'#cfe0da','stroke-opacity':.32,'stroke-width':1.2}));
    ink.append(S('path',{d:'M-44 -56 L-30 -42 H30 L44 -56 M-56 -44 L-42 -30 V30 L-56 44',stroke:'#cfe0da','stroke-opacity':.22,fill:'none'}));
    ink.append(S('path',{d:'M-50 -54 H40',stroke:'#ffffff','stroke-opacity':.42,'stroke-width':2,'stroke-linecap':'round'}));
    ink.append(S('circle',{r:31,fill:'url(#brass)'}));
    ink.append(S('circle',{r:31,fill:'none',stroke:'#4a3212','stroke-opacity':.6}));
    ink.append(S('circle',{r:20,fill:'#120b06'}));
    ink.append(S('ellipse',{cx:-7,cy:-7,rx:6.5,ry:3,fill:'#ffffff','fill-opacity':.5,transform:'rotate(-35 -7 -7)'}));
    svg.append(ink);
  });

  /* ---------- Раскрытая книга ---------- */
  mount('openbook','0 0 480 336',svg=>{
    const g=S('g',{transform:'rotate(6 240 170)'});
    g.append(S('path',{d:'M16 46 Q128 20 240 38 Q352 20 464 46 L460 322 Q352 302 240 316 Q128 302 20 322 Z',fill:'#3e2414',filter:'url(#leather)'}));
    g.append(S('path',{d:'M30 54 Q130 30 238 46 L238 304 Q130 290 34 308 Z',fill:'#efe3c6',filter:'url(#paper)'}));
    g.append(S('path',{d:'M242 46 Q350 30 450 54 L446 308 Q350 290 242 304 Z',fill:'#f2e7cc',filter:'url(#paper)'}));
    g.append(S('rect',{x:206,y:40,width:68,height:270,fill:'url(#gutter)'}));
    // текст — серые строки, не читаемые (иначе шум)
    for(let y=82;y<286;y+=12.5){const len=150+rnd()*30-(y>270?80:0);g.append(S('path',{d:`M58 ${y} h${len}`,stroke:'#6e5638','stroke-opacity':.32,'stroke-width':2.1,'stroke-linecap':'round'}));}
    g.append(S('path',{d:'M300 76 h96',stroke:'#4a3626','stroke-opacity':.55,'stroke-width':3,'stroke-linecap':'round'}));
    g.append(S('circle',{cx:346,cy:128,r:32,fill:'none',stroke:'#6e5638','stroke-opacity':.45,'stroke-width':1.2}));
    for(let k=-28;k<=28;k+=4){const hh=Math.sqrt(Math.max(0,30*30-k*k));g.append(S('path',{d:`M${346+k} ${128-hh} V${128+hh*0.2}`,stroke:'#6e5638','stroke-opacity':.22,'stroke-width':.8}));}
    for(let y=178;y<286;y+=12.5){const len=140+rnd()*30;g.append(S('path',{d:`M272 ${y} h${len}`,stroke:'#6e5638','stroke-opacity':.32,'stroke-width':2.1,'stroke-linecap':'round'}));}
    g.append(S('path',{d:'M244 40 C250 120 246 250 262 336',stroke:'#2f5a3c','stroke-width':7,fill:'none'}));
    svg.append(g);
  });

  /* ---------- Очки ---------- */
  mount('glasses','0 0 230 120',svg=>{
    const g=S('g',{transform:'rotate(-8 115 60)'});
    g.append(S('path',{d:'M24 50 L118 26 M206 52 L112 30',stroke:'#8f6f3c','stroke-width':2.4,'stroke-opacity':.85,fill:'none','stroke-linecap':'round'}));
    [[62,62],[168,64]].forEach(([x,y])=>{
      g.append(S('ellipse',{cx:x,cy:y,rx:44,ry:35,fill:'#fff6e2','fill-opacity':.1,stroke:'#9a7a45','stroke-width':3}));
      g.append(S('path',{d:`M${x-30} ${y-18} Q${x-16} ${y-30} ${x+2} ${y-31}`,stroke:'#ffffff','stroke-opacity':.55,'stroke-width':2,fill:'none','stroke-linecap':'round'}));
    });
    g.append(S('path',{d:'M106 58 Q115 44 124 59',stroke:'#9a7a45','stroke-width':3,fill:'none'}));
    svg.append(g);
  });

  /* ---------- Письмо с сургучной печатью ---------- */
  mount('letter','0 0 300 230',svg=>{
    const g=S('g',{transform:'rotate(-9 150 115)'});
    g.append(S('rect',{x:22,y:24,width:256,height:176,fill:'#eee2c4',filter:'url(#paper)'}));
    g.append(S('path',{d:'M22 24 L150 116 L278 24 M22 200 L124 110 M278 200 L176 110',stroke:'#8a6a3a','stroke-opacity':.35,fill:'none'}));
    g.append(S('path',{d:'M60 160 q20 -8 40 0 t40 0 t40 0',stroke:'#4a3626','stroke-opacity':.4,fill:'none','stroke-width':1.2}));
    g.append(S('circle',{cx:150,cy:118,r:24,fill:'#a8341f',filter:'url(#wax)'}));
    g.append(S('circle',{cx:150,cy:118,r:15,fill:'none',stroke:'#5e140a','stroke-opacity':.45,'stroke-width':1.5}));
    g.append(S('text',{x:150,y:125,'text-anchor':'middle','font-family':'Literata, Georgia, serif','font-size':20,fill:'#5e140a','fill-opacity':.6},'φ'));
    g.append(S('path',{d:'M136 104 Q146 97 158 99',stroke:'#ffd2b8','stroke-opacity':.55,'stroke-width':2,fill:'none','stroke-linecap':'round'}));
    svg.append(g);
  });

  /* ---------- Рукописные пометки поверх графа (та же система координат, что #svg) ---------- */
  const chart=document.querySelector('.chart');
  if(chart){
    const notes=S('svg',{class:'chart-notes',viewBox:'0 0 1160 560','aria-hidden':'true'});
    const T=(x,y,s,txt,rot)=>notes.append(S('text',{x,y,class:'hand','font-size':s,transform:rot?`rotate(${rot} ${x} ${y})`:''},txt));
    T(828,178,19,'«Юм пробудил меня',-3);
    T(842,203,19,'от догматического сна»',-3);
    T(940,226,14,'— Кант, 1783',-3);
    notes.append(S('path',{d:'M884 236 C876 262 852 290 816 318',class:'hand-stroke'}));
    notes.append(S('path',{d:'M823 306 L815 319 L829 317',class:'hand-stroke'}));
    T(596,214,15,'а Спиноза?',-4);
    T(178,444,18,'Опыт или разум?',-2);
    T(196,468,16,'— вот спор целой эпохи',-2);
    notes.append(S('path',{d:'M932 473 Q1004 479 1078 469',class:'hand-stroke'}));
    chart.append(notes);
  }
})();
