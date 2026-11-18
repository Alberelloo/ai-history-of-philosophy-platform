/* Данные для сцены «стол философа». Два набора:
   demo  — 5 философов (исходный кадр);
   dense — синтетический стресс-набор ≈ реального объёма раздела «теория познания» Нового времени:
           41 философ, 60 трудов и понятий, 50 влияний, 14 событий, 4 эпохи.
   Годы жизни и трудов — по общим справочникам; связи влияния — упрощённые, для проверки плотности,
   не для цитирования. Выбор набора: desk.html?data=dense */
window.DESK_SETS={
  demo:{
    title:'От Декарта до Канта',
    sel:'kant',
    people:[
      {id:'descartes',name:'Рене Декарт',short:'Декарт',birth:1596,death:1650,portrait:'descartes.jpg'},
      {id:'locke',name:'Джон Локк',short:'Локк',birth:1632,death:1704,portrait:'locke.jpg'},
      {id:'spinoza',name:'Бенедикт Спиноза',short:'Спиноза',birth:1632,death:1677},
      {id:'hume',name:'Дэвид Юм',short:'Юм',birth:1711,death:1776,portrait:'hume.jpg'},
      {id:'kant',name:'Иммануил Кант',short:'Кант',birth:1724,death:1804,portrait:'kant.jpg'},
    ],
    influences:[{a:'descartes',b:'locke',via:1637},{a:'locke',b:'hume',via:1690},{a:'hume',b:'kant',via:1748},{a:'descartes',b:'spinoza',via:1641}],
    works:[
      {id:'essay',title:'Опыт о человеческом разумении',year:1690,author:'locke',kind:'work',key:1},
      {id:'causality',title:'Причинность',year:1739,author:'hume',kind:'concept',key:1},
      {id:'enquiry',title:'Исследование о человеческом познании',year:1748,author:'hume',kind:'work',key:1},
      {id:'critique',title:'Критика чистого разума',year:1781,author:'kant',kind:'work',key:1},
    ],
    eras:[{label:'Научная революция',from:1600,to:1687},{label:'Просвещение',from:1687,to:1804}],
    events:[{year:1687,label:'«Начала» Ньютона'},{year:1751,label:'Энциклопедия'},{year:1789,label:'Французская революция'}],
    range:[1580,1812],
  },
  dense:{
    title:'Теория познания Нового времени',
    sel:'kant',
    people:[
      ['montaigne','Мишель Монтень','Монтень',1533,1592],['bacon','Фрэнсис Бэкон','Бэкон',1561,1626],
      ['galileo','Галилео Галилей','Галилей',1564,1642],['mersenne','Марен Мерсенн','Мерсенн',1588,1648],
      ['hobbes','Томас Гоббс','Гоббс',1588,1679],['gassendi','Пьер Гассенди','Гассенди',1592,1655],
      ['descartes','Рене Декарт','Декарт',1596,1650,'descartes.jpg'],['arnauld','Антуан Арно','Арно',1612,1694],
      ['pascal','Блез Паскаль','Паскаль',1623,1662],['spinoza','Бенедикт Спиноза','Спиноза',1632,1677],
      ['locke','Джон Локк','Локк',1632,1704,'locke.jpg'],['malebranche','Никола Мальбранш','Мальбранш',1638,1715],
      ['newton','Исаак Ньютон','Ньютон',1643,1727],['leibniz','Готфрид Лейбниц','Лейбниц',1646,1716],
      ['bayle','Пьер Бейль','Бейль',1647,1706],['vico','Джамбаттиста Вико','Вико',1668,1744],
      ['shaftesbury','Энтони Шефтсбери','Шефтсбери',1671,1713],['wolff','Христиан Вольф','Вольф',1679,1754],
      ['berkeley','Джордж Беркли','Беркли',1685,1753],['montesquieu','Шарль Монтескьё','Монтескьё',1689,1755],
      ['voltaire','Вольтер','Вольтер',1694,1778],['hutcheson','Фрэнсис Хатчесон','Хатчесон',1694,1746],
      ['lamettrie','Жюльен Ламетри','Ламетри',1709,1751],['reid','Томас Рид','Рид',1710,1796],
      ['hume','Дэвид Юм','Юм',1711,1776,'hume.jpg'],['rousseau','Жан-Жак Руссо','Руссо',1712,1778],
      ['diderot','Дени Дидро','Дидро',1713,1784],['condillac','Этьен Кондильяк','Кондильяк',1714,1780],
      ['baumgarten','Александр Баумгартен','Баумгартен',1714,1762],['helvetius','Клод Гельвеций','Гельвеций',1715,1771],
      ['dalembert','Жан д’Аламбер','д’Аламбер',1717,1783],['kant','Иммануил Кант','Кант',1724,1804,'kant.jpg'],
      ['mendelssohn','Мозес Мендельсон','Мендельсон',1729,1786],['hamann','Иоганн Гаман','Гаман',1730,1788],
      ['jacobi','Фридрих Якоби','Якоби',1743,1819],['herder','Иоганн Гердер','Гердер',1744,1803],
      ['fichte','Иоганн Фихте','Фихте',1762,1814],['biran','Мен де Биран','Мен де Биран',1766,1824],
      ['hegel','Георг Гегель','Гегель',1770,1831],['schelling','Фридрих Шеллинг','Шеллинг',1775,1854],
      ['schopenhauer','Артур Шопенгауэр','Шопенгауэр',1788,1860],
    ].map(([id,name,short,birth,death,portrait])=>({id,name,short,birth,death,portrait})),
    influences:[
      ['montaigne','pascal',1580],['montaigne','descartes',1580],['bacon','hobbes',1620],['bacon','locke',1620],
      ['galileo','hobbes',1632],['mersenne','descartes'],['descartes','spinoza',1641],['descartes','malebranche',1641],
      ['descartes','locke',1637],['descartes','arnauld',1641],['descartes','leibniz',1644],['gassendi','locke',1658],
      ['hobbes','spinoza',1651],['hobbes','locke',1651],['arnauld','leibniz',1662],['malebranche','berkeley',1674],
      ['locke','berkeley',1690],['locke','hume',1690],['locke','condillac',1690],['locke','voltaire',1690],
      ['locke','leibniz',1690],['spinoza','leibniz',1677],['spinoza','jacobi',1677],['spinoza','schelling',1677],
      ['spinoza','hegel',1677],['leibniz','wolff',1714],['wolff','kant',1720],['wolff','baumgarten',1720],
      ['baumgarten','kant',1750],['newton','voltaire',1704],['newton','kant',1704],['bayle','hume',1697],
      ['berkeley','hume',1710],['shaftesbury','hutcheson',1711],['hutcheson','hume',1725],['hume','kant',1748],
      ['hume','reid',1739],['hume','hamann',1739],['rousseau','kant',1762],['condillac','biran',1754],
      ['condillac','helvetius',1746],['voltaire','diderot',1734],['kant','fichte',1781],['kant','schopenhauer',1781],
      ['kant','herder'],['hamann','herder',1784],['hamann','jacobi',1784],['fichte','schelling',1794],
      ['fichte','hegel',1794],['schelling','hegel',1800],
    ].map(([a,b,via])=>({a,b,via})),
    works:[
      ['montaigne','Опыты',1580,1],['bacon','Новый органон',1620,1],['bacon','О достоинстве и приумножении наук',1623],
      ['galileo','Пробирных дел мастер',1623],['galileo','Диалог о двух главнейших системах мира',1632,1],
      ['descartes','Рассуждение о методе',1637,1],['descartes','Cogito',1637,1,'concept'],['descartes','Размышления о первой философии',1641,1],
      ['descartes','Начала философии',1644],['hobbes','Левиафан',1651,1],['hobbes','О теле',1655],['gassendi','Свод философии',1658],
      ['arnauld','Логика Пор-Рояля',1662],['pascal','Мысли',1670,1],['spinoza','Богословско-политический трактат',1670],
      ['malebranche','О разыскании истины',1674],['spinoza','Этика',1677,1],['leibniz','Рассуждение о метафизике',1686],
      ['locke','Два трактата о правлении',1689],['locke','Опыт о человеческом разумении',1690,1],['locke','Tabula rasa',1690,0,'concept'],
      ['leibniz','Предустановленная гармония',1695,0,'concept'],['bayle','Исторический и критический словарь',1697],
      ['newton','Оптика',1704],['leibniz','Новые опыты о человеческом разумении',1704,1],['berkeley','Трактат о принципах человеческого знания',1710,1],
      ['berkeley','Esse est percipi',1710,0,'concept'],['leibniz','Теодицея',1710],['shaftesbury','Характеристики',1711],
      ['berkeley','Три разговора',1713],['leibniz','Монадология',1714,1],['wolff','Разумные мысли о Боге, мире и душе',1720],
      ['vico','Новая наука',1725],['hutcheson','Исследование о происхождении наших идей красоты и добродетели',1725],
      ['voltaire','Философские письма',1734],['hume','Трактат о человеческой природе',1739,1],['hume','Причинность',1739,1,'concept'],
      ['condillac','Опыт о происхождении человеческих знаний',1746],['lamettrie','Человек-машина',1747],
      ['montesquieu','О духе законов',1748],['hume','Исследование о человеческом познании',1748,1],['diderot','Письмо о слепых',1749],
      ['baumgarten','Эстетика',1750],['condillac','Трактат об ощущениях',1754,1],['helvetius','Об уме',1758],
      ['rousseau','Эмиль',1762],['rousseau','Об общественном договоре',1762],['reid','Исследование человеческого ума',1764,1],
      ['reid','Здравый смысл',1764,0,'concept'],['voltaire','Философский словарь',1764],['mendelssohn','Федон',1767],
      ['kant','Критика чистого разума',1781,1],['kant','Синтетическое априори',1781,0,'concept'],['kant','Пролегомены',1783],
      ['hamann','Метакритика',1784],['herder','Идеи к философии истории человечества',1784],['jacobi','Давид Юм о вере',1787],
      ['kant','Критика практического разума',1788],['kant','Критика способности суждения',1790],['fichte','Наукоучение',1794,1],
      ['schelling','Система трансцендентального идеализма',1800],['hegel','Феноменология духа',1807,1],['hegel','Наука логики',1812],
      ['schopenhauer','Мир как воля и представление',1819,1],
    ].map(([author,title,year,key,kind],i)=>({id:'w'+i,author,title,year,key:!!key,kind:kind||'work'})),
    eras:[{label:'Поздний Ренессанс',from:1530,to:1600},{label:'Научная революция',from:1600,to:1687},
          {label:'Просвещение',from:1687,to:1789},{label:'Идеализм и романтизм',from:1789,to:1860}],
    events:[
      [1572,'Варфоломеевская ночь'],[1618,'Тридцатилетняя война'],[1633,'Суд над Галилеем'],[1648,'Вестфальский мир'],
      [1660,'Королевское общество'],[1687,'«Начала» Ньютона'],[1688,'Славная революция'],[1700,'Берлинская академия'],
      [1751,'Энциклопедия'],[1755,'Лиссабонское землетрясение'],[1776,'Независимость США'],[1789,'Французская революция'],
      [1806,'Конец Священной Римской империи'],[1815,'Венский конгресс'],
    ].map(([year,label])=>({year,label})),
    range:[1525,1865],
  },
};
// Цитаты для карточки на столе (у каждой — источник). В продукте — из онтологии/RAG; непроверенное помечается.
window.DESK_NOTES=[
  {about:'kant',lines:['«…впервые прервало мою','догматическую дремоту»'],cite:'Кант о Юме, «Пролегомены», 1783'},
  {about:'descartes',lines:['«Я мыслю, следовательно,','я существую»'],cite:'«Рассуждение о методе», 1637'},
  {about:'locke',lines:['«…ум есть, так сказать,','белая бумага без всяких знаков»'],cite:'«Опыт…», кн. II, гл. 1'},
  {about:'hume',lines:['«Разум есть и должен быть','лишь рабом аффектов»'],cite:'«Трактат о человеческой природе»'},
  {about:'spinoza',lines:['«Порядок и связь идей те же,','что порядок и связь вещей»'],cite:'«Этика», ч. II, теор. 7'},
];

/* Фасеты для фильтров (синтетика по мотивам онтологии: группы вида «направление» и «школа»,
   роли персон, виды произведений и событий, проверенность связей). */
(function(){
  const D=window.DESK_SETS.dense;
  D.groups=[
    {id:'g-emp',kind:'direction',label:'Эмпиризм',members:['bacon','hobbes','gassendi','locke','berkeley','hume','condillac']},
    {id:'g-rat',kind:'direction',label:'Рационализм',members:['descartes','spinoza','malebranche','leibniz','wolff','arnauld','baumgarten']},
    {id:'g-skep',kind:'direction',label:'Скептицизм',members:['montaigne','bayle','hume']},
    {id:'g-enl',kind:'direction',label:'Французское Просвещение',members:['voltaire','diderot','dalembert','helvetius','lamettrie','montesquieu','rousseau','condillac']},
    {id:'g-crit',kind:'direction',label:'Критицизм и идеализм',members:['kant','fichte','schelling','hegel','schopenhauer']},
    {id:'g-faith',kind:'direction',label:'Философия веры и чувства',members:['hamann','jacobi','herder']},
    {id:'g-moral',kind:'direction',label:'Философия морального чувства',members:['shaftesbury','hutcheson']},
    {id:'s-cart',kind:'school',label:'Картезианство',members:['descartes','malebranche','arnauld']},
    {id:'s-lw',kind:'school',label:'Лейбнице-вольфовская школа',members:['leibniz','wolff','baumgarten','mendelssohn']},
    {id:'s-scot',kind:'school',label:'Шотландская школа здравого смысла',members:['reid']},
    {id:'s-enc',kind:'school',label:'Энциклопедисты',members:['diderot','dalembert','helvetius','voltaire','montesquieu','rousseau']},
    {id:'s-jena',kind:'school',label:'Йенский кружок',members:['fichte','schelling','hegel']},
  ];
  const roles={scientist:['galileo','mersenne','pascal','newton','leibniz','dalembert'],writer:['montaigne','voltaire','rousseau','diderot','montesquieu'],theologian:['mersenne','malebranche','arnauld','berkeley','hamann']};
  D.people.forEach(p=>{p.roles=['philosopher',...Object.keys(roles).filter(r=>roles[r].includes(p.id))];});
  D.roleLabels={philosopher:'Философ',scientist:'Учёный',writer:'Писатель',theologian:'Богослов'};
  const pos={'Синтетическое априори':1,'Esse est percipi':1,'Tabula rasa':1},arg={'Cogito':1};
  D.works.forEach(w=>{if(pos[w.title])w.kind='position';if(arg[w.title])w.kind='argument';});
  D.kindLabels={work:'Произведения',concept:'Понятия',position:'Позиции',argument:'Аргументы'};
  const ek=['political','political','scientific','political','scientific','scientific','political','scientific','intellectual','intellectual','political','political','political','political'];
  D.events.forEach((e,i)=>{e.id='e'+i;e.kind=ek[i];});
  D.eventKindLabels={political:'Политические',scientific:'Научные',religious:'Религиозные',intellectual:'Интеллектуальные'};
  // часть связей достроена LLM и не проверена человеком — в интерфейсе помечается пунктиром
  const unv=['montaigne-descartes','galileo-hobbes','bayle-hume','rousseau-kant','condillac-biran','locke-leibniz','spinoza-hegel'];
  D.influences.forEach(e=>{e.verified=!unv.includes(e.a+'-'+e.b);});
  D.eras.forEach((e,i)=>e.id='era'+i);
  const M=window.DESK_SETS.demo;M.groups=[];M.events.forEach((e,i)=>{e.id='e'+i;e.kind='intellectual';});M.eras.forEach((e,i)=>e.id='era'+i);
  M.influences.forEach(e=>e.verified=true);M.people.forEach(p=>p.roles=['philosopher']);
})();
