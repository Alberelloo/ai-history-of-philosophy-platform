/* Фиксированные демонстрационные данные. Не исторический датасет и не вывод модели. */
(() => {
  const node=(id,type,label,labelEn,year,dates,x,y,portrait=null,datesEn=null)=>({id,type,label,labelEn,year,dates,datesEn,x,y,portrait});
  const edge=(id,subject,object,type,title,families,status,extra={})=>({id,subject,object,type,title,titleEn:({influenced_by:'was influenced by',develops:'develops',criticizes:'criticizes',authored:'authored',related_to:'is related to'})[type]||'is related to',families,status,qualifiers:{aspect:'Демонстрационный аспект'},attributions:[{who:'Демонстрационный учебник',kind:'source',stance:'supports',place:'§ 1'}],evidence:status==='generated'?[]:[{quote:'Демонстрационная цитата: пример того, как источник обосновывает связь.',link:'#demo-source'}],...extra});
  const genesis={start:'kant',order:'time',recipeFamilies:['genesis','consequences'],nodes:[
    node('descartes','person','Рене Декарт','René Descartes',1596,'1596–1650',100,220,'assets/descartes.jpg'),
    node('locke','person','Джон Локк','John Locke',1632,'1632–1704',295,110,'assets/locke.jpg'),
    node('hume','person','Дэвид Юм','David Hume',1711,'1711–1776',720,170,'assets/hume.jpg'),
    node('kant','person','Иммануил Кант','Immanuel Kant',1724,'1724–1804',790,380,'assets/kant.jpg'),
    node('reason','concept','Разум','Reason',1632,null,295,380),
    node('causality','concept','Причинность','Causality',null,null,970,170),
    node('enquiry','work','Исследование о человеческом познании','An Enquiry Concerning Human Understanding',1748,'1748',920,80),
    node('critique','work','Критика чистого разума','Critique of Pure Reason',1781,'1781',1100,350)
  ],edges:[
    edge('kant-hume','kant','hume','influenced_by','испытал влияние',['genesis','consequences'],'verified'),
    edge('hume-locke','hume','locke','influenced_by','испытал влияние',['genesis','consequences'],'sourced'),
    edge('locke-descartes','locke','descartes','influenced_by','испытал влияние',['genesis','consequences'],'verified'),
    edge('reason-descartes','reason','descartes','develops','развивает',['genesis','consequences'],'generated'),
    edge('kant-reason','kant','reason','develops','развивает',['genesis','consequences'],'sourced'),
    edge('kant-critique','critique','kant','influenced_by','испытало влияние',['genesis','consequences'],'verified'),
    edge('enquiry-hume','enquiry','hume','influenced_by','испытало влияние',['genesis','consequences'],'sourced'),
    edge('causality-hume','causality','hume','develops','развивает',['genesis','consequences'],'generated'),
    edge('critique-enquiry','critique','enquiry','influenced_by','испытало влияние',['genesis','consequences'],'verified'),
    edge('kant-causality','kant','causality','develops','развивает',['genesis','consequences'],'generated')
  ],clusters:[]};
  const families=['genesis','consequences','polemic','context','structure','biography'];
  const statuses=['verified','sourced','generated'];
  const specimens={start:'s-0',order:null,recipeFamilies:families,nodes:[],edges:[],clusters:[]};
  const types=['person','concept','doctrine','work','event','group','unknown'];
  families.forEach((family,row)=>statuses.forEach((status,col)=>{
    const n=row*3+col, x=100+col*360,y=90+row*185;
    specimens.nodes.push(node(`s-${n*2}`,types[n%types.length],n===2?'Оченьдлинноенеразрывноеназваниефилософскогопонятия'.repeat(3):`Образец ${n+1}`,`Specimen ${n+1}`,n===0?-384:null,n===0?'384–322 до н. э.':null,x,y,null,n===0?'384–322 BCE':null));
    specimens.nodes.push(node(`s-${n*2+1}`,types[(n+1)%types.length],`Связанный объект ${n+1}`,`Related object ${n+1}`,null,null,x+195,y));
    specimens.edges.push(edge(`spec-${n}`,`s-${n*2}`,`s-${n*2+1}`,'related_to','связано с',[family],status,{symmetric:family==='context'}));
  }));
  specimens.edges.push(edge('spec-parallel','s-0','s-1','related_to','параллельная связь',['genesis','biography'],'generated'));
  specimens.edges.push(edge('spec-loop','s-4','s-4','related_to','рефлексивная связь',['structure'],'sourced'));
  const dense={start:'d-0',order:null,recipeFamilies:families,nodes:[],edges:[],clusters:[]};
  for(let g=0;g<3;g++){
    const ids=[];
    for(let i=0;i<16;i++){
      const k=g*16+i, id=`d-${k}`;ids.push(id);
      dense.nodes.push(node(id,types[k%6],k===7?'Длинное название философского учения и его исторических интерпретаций':`Узел ${String(k+1).padStart(2,'0')}`,`Node ${k+1}`,null,null,120+g*580+(i%4)*115,100+Math.floor(i/4)*150));
      if(i) dense.edges.push(edge(`d-e-${k}`,id,`d-${g*16+Math.floor((i-1)/2)}`,'related_to','связано с',[families[k%6]],statuses[k%3]));
    }
    dense.clusters.push({id:`cluster-${g}`,label:`Группа связей ${g+1}`,labelEn:`Related group ${g+1}`,nodeIds:ids,x:260+g*580,y:300,collapsed:g>0});
    if(g) dense.edges.push(edge(`bridge-${g}`,`d-${g*16}`,'d-0','related_to','связано с',['context'],'sourced'));
  }
  dense.edges.push(edge('dense-parallel','d-0','d-1','related_to','параллельная связь',['polemic'],'generated'));
  dense.edges.push(edge('dense-loop','d-4','d-4','related_to','рефлексивная связь',['structure'],'verified'));
  window.GRAPH_FIXTURES={genesis,specimens,dense};
  window.GRAPH_STATES=['loading','extending','off','unavailable','error','empty','filtered','limited'];
})();
