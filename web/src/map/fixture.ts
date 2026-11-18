// Плотный синтетический набор карты — набор dense макета (desk-data.js) в типах ответа
// GET /api/knowledge/v1/map. Для UI-тестов и страницы без сервиса.
// Годы — по общим справочникам; связи влияния упрощены, для проверки плотности, не для цитирования.

import type { EventKind, MapData, MapLink, MapPerson, MapWork, PersonRole, WorkKind } from "./types";

const PEOPLE: [string, string, string, number, number][] = [
  ["montaigne", "Мишель Монтень", "Монтень", 1533, 1592], ["bacon", "Фрэнсис Бэкон", "Бэкон", 1561, 1626],
  ["galileo", "Галилео Галилей", "Галилей", 1564, 1642], ["mersenne", "Марен Мерсенн", "Мерсенн", 1588, 1648],
  ["hobbes", "Томас Гоббс", "Гоббс", 1588, 1679], ["gassendi", "Пьер Гассенди", "Гассенди", 1592, 1655],
  ["descartes", "Рене Декарт", "Декарт", 1596, 1650], ["arnauld", "Антуан Арно", "Арно", 1612, 1694],
  ["pascal", "Блез Паскаль", "Паскаль", 1623, 1662], ["spinoza", "Бенедикт Спиноза", "Спиноза", 1632, 1677],
  ["locke", "Джон Локк", "Локк", 1632, 1704], ["malebranche", "Никола Мальбранш", "Мальбранш", 1638, 1715],
  ["newton", "Исаак Ньютон", "Ньютон", 1643, 1727], ["leibniz", "Готфрид Лейбниц", "Лейбниц", 1646, 1716],
  ["bayle", "Пьер Бейль", "Бейль", 1647, 1706], ["vico", "Джамбаттиста Вико", "Вико", 1668, 1744],
  ["shaftesbury", "Энтони Шефтсбери", "Шефтсбери", 1671, 1713], ["wolff", "Христиан Вольф", "Вольф", 1679, 1754],
  ["berkeley", "Джордж Беркли", "Беркли", 1685, 1753], ["montesquieu", "Шарль Монтескьё", "Монтескьё", 1689, 1755],
  ["voltaire", "Вольтер", "Вольтер", 1694, 1778], ["hutcheson", "Фрэнсис Хатчесон", "Хатчесон", 1694, 1746],
  ["lamettrie", "Жюльен Ламетри", "Ламетри", 1709, 1751], ["reid", "Томас Рид", "Рид", 1710, 1796],
  ["hume", "Дэвид Юм", "Юм", 1711, 1776], ["rousseau", "Жан-Жак Руссо", "Руссо", 1712, 1778],
  ["diderot", "Дени Дидро", "Дидро", 1713, 1784], ["condillac", "Этьен Кондильяк", "Кондильяк", 1714, 1780],
  ["baumgarten", "Александр Баумгартен", "Баумгартен", 1714, 1762], ["helvetius", "Клод Гельвеций", "Гельвеций", 1715, 1771],
  ["dalembert", "Жан д’Аламбер", "д’Аламбер", 1717, 1783], ["kant", "Иммануил Кант", "Кант", 1724, 1804],
  ["mendelssohn", "Мозес Мендельсон", "Мендельсон", 1729, 1786], ["hamann", "Иоганн Гаман", "Гаман", 1730, 1788],
  ["jacobi", "Фридрих Якоби", "Якоби", 1743, 1819], ["herder", "Иоганн Гердер", "Гердер", 1744, 1803],
  ["fichte", "Иоганн Фихте", "Фихте", 1762, 1814], ["biran", "Мен де Биран", "Мен де Биран", 1766, 1824],
  ["hegel", "Георг Гегель", "Гегель", 1770, 1831], ["schelling", "Фридрих Шеллинг", "Шеллинг", 1775, 1854],
  ["schopenhauer", "Артур Шопенгауэр", "Шопенгауэр", 1788, 1860],
];

// [учитель, ученик]: в ответе — subject (ученик) испытал влияние object (учителя)
const INFLUENCES: [string, string][] = [
  ["montaigne", "pascal"], ["montaigne", "descartes"], ["bacon", "hobbes"], ["bacon", "locke"],
  ["galileo", "hobbes"], ["mersenne", "descartes"], ["descartes", "spinoza"], ["descartes", "malebranche"],
  ["descartes", "locke"], ["descartes", "arnauld"], ["descartes", "leibniz"], ["gassendi", "locke"],
  ["hobbes", "spinoza"], ["hobbes", "locke"], ["arnauld", "leibniz"], ["malebranche", "berkeley"],
  ["locke", "berkeley"], ["locke", "hume"], ["locke", "condillac"], ["locke", "voltaire"],
  ["locke", "leibniz"], ["spinoza", "leibniz"], ["spinoza", "jacobi"], ["spinoza", "schelling"],
  ["spinoza", "hegel"], ["leibniz", "wolff"], ["wolff", "kant"], ["wolff", "baumgarten"],
  ["baumgarten", "kant"], ["newton", "voltaire"], ["newton", "kant"], ["bayle", "hume"],
  ["berkeley", "hume"], ["shaftesbury", "hutcheson"], ["hutcheson", "hume"], ["hume", "kant"],
  ["hume", "reid"], ["hume", "hamann"], ["rousseau", "kant"], ["condillac", "biran"],
  ["condillac", "helvetius"], ["voltaire", "diderot"], ["kant", "fichte"], ["kant", "schopenhauer"],
  ["kant", "herder"], ["hamann", "herder"], ["hamann", "jacobi"], ["fichte", "schelling"],
  ["fichte", "hegel"], ["schelling", "hegel"],
];
// достроены моделью и не проверены человеком — пунктир
const GENERATED = new Set(["montaigne-descartes", "galileo-hobbes", "bayle-hume", "rousseau-kant", "condillac-biran", "locke-leibniz", "spinoza-hegel"]);

// [автор, название, год, ключевой, вид]
const WORKS: [string, string, number, 0 | 1, WorkKind?][] = [
  ["montaigne", "Опыты", 1580, 1], ["bacon", "Новый органон", 1620, 1], ["bacon", "О достоинстве и приумножении наук", 1623, 0],
  ["galileo", "Пробирных дел мастер", 1623, 0], ["galileo", "Диалог о двух главнейших системах мира", 1632, 1],
  ["descartes", "Рассуждение о методе", 1637, 1], ["descartes", "Cogito", 1637, 1, "argument"], ["descartes", "Размышления о первой философии", 1641, 1],
  ["descartes", "Начала философии", 1644, 0], ["hobbes", "Левиафан", 1651, 1], ["hobbes", "О теле", 1655, 0], ["gassendi", "Свод философии", 1658, 0],
  ["arnauld", "Логика Пор-Рояля", 1662, 0], ["pascal", "Мысли", 1670, 1], ["spinoza", "Богословско-политический трактат", 1670, 0],
  ["malebranche", "О разыскании истины", 1674, 0], ["spinoza", "Этика", 1677, 1], ["leibniz", "Рассуждение о метафизике", 1686, 0],
  ["locke", "Два трактата о правлении", 1689, 0], ["locke", "Опыт о человеческом разумении", 1690, 1], ["locke", "Tabula rasa", 1690, 0, "position"],
  ["leibniz", "Предустановленная гармония", 1695, 0, "concept"], ["bayle", "Исторический и критический словарь", 1697, 0],
  ["newton", "Оптика", 1704, 0], ["leibniz", "Новые опыты о человеческом разумении", 1704, 1], ["berkeley", "Трактат о принципах человеческого знания", 1710, 1],
  ["berkeley", "Esse est percipi", 1710, 0, "position"], ["leibniz", "Теодицея", 1710, 0], ["shaftesbury", "Характеристики", 1711, 0],
  ["berkeley", "Три разговора", 1713, 0], ["leibniz", "Монадология", 1714, 1], ["wolff", "Разумные мысли о Боге, мире и душе", 1720, 0],
  ["vico", "Новая наука", 1725, 0], ["hutcheson", "Исследование о происхождении наших идей красоты и добродетели", 1725, 0],
  ["voltaire", "Философские письма", 1734, 0], ["hume", "Трактат о человеческой природе", 1739, 1], ["hume", "Причинность", 1739, 1, "concept"],
  ["condillac", "Опыт о происхождении человеческих знаний", 1746, 0], ["lamettrie", "Человек-машина", 1747, 0],
  ["montesquieu", "О духе законов", 1748, 0], ["hume", "Исследование о человеческом познании", 1748, 1], ["diderot", "Письмо о слепых", 1749, 0],
  ["baumgarten", "Эстетика", 1750, 0], ["condillac", "Трактат об ощущениях", 1754, 1], ["helvetius", "Об уме", 1758, 0],
  ["rousseau", "Эмиль", 1762, 0], ["rousseau", "Об общественном договоре", 1762, 0], ["reid", "Исследование человеческого ума", 1764, 1],
  ["reid", "Здравый смысл", 1764, 0, "concept"], ["voltaire", "Философский словарь", 1764, 0], ["mendelssohn", "Федон", 1767, 0],
  ["kant", "Критика чистого разума", 1781, 1], ["kant", "Синтетическое априори", 1781, 0, "position"], ["kant", "Пролегомены", 1783, 0],
  ["hamann", "Метакритика", 1784, 0], ["herder", "Идеи к философии истории человечества", 1784, 0], ["jacobi", "Давид Юм о вере", 1787, 0],
  ["kant", "Критика практического разума", 1788, 0], ["kant", "Критика способности суждения", 1790, 0], ["fichte", "Наукоучение", 1794, 1],
  ["schelling", "Система трансцендентального идеализма", 1800, 0], ["hegel", "Феноменология духа", 1807, 1], ["hegel", "Наука логики", 1812, 0],
  ["schopenhauer", "Мир как воля и представление", 1819, 1],
];

const EVENTS: [number, string, EventKind][] = [
  [1572, "Варфоломеевская ночь", "political"], [1618, "Тридцатилетняя война", "political"], [1633, "Суд над Галилеем", "scientific"],
  [1648, "Вестфальский мир", "political"], [1660, "Королевское общество", "scientific"], [1687, "«Начала» Ньютона", "scientific"],
  [1688, "Славная революция", "political"], [1700, "Берлинская академия", "scientific"], [1751, "Энциклопедия", "intellectual"],
  [1755, "Лиссабонское землетрясение", "intellectual"], [1776, "Независимость США", "political"], [1789, "Французская революция", "political"],
  [1806, "Конец Священной Римской империи", "political"], [1815, "Венский конгресс", "political"],
];

const ROLES: Partial<Record<PersonRole, string[]>> = {
  scientist: ["galileo", "mersenne", "pascal", "newton", "leibniz", "dalembert"],
  writer: ["montaigne", "voltaire", "rousseau", "diderot", "montesquieu"],
  theologian: ["mersenne", "malebranche", "arnauld", "berkeley", "hamann"],
};

const links: MapLink[] = INFLUENCES.map(([a, b], i) => {
  const generated = GENERATED.has(`${a}-${b}`);
  return {
    id: `l${i}`,
    subject: b,
    object: a,
    type: "influenced_by",
    status: generated ? "generated" : "verified",
    generated,
    in_textbook: generated ? null : true,
  };
});

const works: MapWork[] = WORKS.map(([author, label, year, key, kind = "work"], i) => ({
  id: `w${i}`,
  label,
  type: kind,
  kind,
  year,
  author,
  weight: key ? 8 : 3,
}));

// значимость персоны: утверждения о ней — труды и связи
const people: MapPerson[] = PEOPLE.map(([id, label, short, birth, death]) => ({
  id,
  label,
  short,
  birth,
  death,
  precision: "year",
  roles: ["philosopher", ...Object.entries(ROLES).flatMap(([r, ids]) => (ids.includes(id) ? [r] : []))],
  weight:
    works.filter((w) => w.author === id).reduce((n, w) => n + w.weight, 0) + links.filter((l) => l.subject === id || l.object === id).length,
}));

export const DENSE_MAP: MapData = {
  range: [1525, 1865],
  truncated: false,
  limit: 400,
  people,
  works,
  events: EVENTS.map(([year, label, kind], i) => ({ id: `e${i}`, label, year, kind })),
  eras: [
    { id: "era0", label: "Поздний Ренессанс", from: 1530, to: 1600 },
    { id: "era1", label: "Научная революция", from: 1600, to: 1687 },
    { id: "era2", label: "Просвещение", from: 1687, to: 1789 },
    { id: "era3", label: "Идеализм и романтизм", from: 1789, to: 1860 },
  ],
  groups: [
    { id: "g-emp", kind: "direction", label: "Эмпиризм", members: ["bacon", "hobbes", "gassendi", "locke", "berkeley", "hume", "condillac"] },
    { id: "g-rat", kind: "direction", label: "Рационализм", members: ["descartes", "spinoza", "malebranche", "leibniz", "wolff", "arnauld", "baumgarten"] },
    { id: "g-skep", kind: "direction", label: "Скептицизм", members: ["montaigne", "bayle", "hume"] },
    { id: "g-enl", kind: "direction", label: "Французское Просвещение", members: ["voltaire", "diderot", "dalembert", "helvetius", "lamettrie", "montesquieu", "rousseau", "condillac"] },
    { id: "g-crit", kind: "direction", label: "Критицизм и идеализм", members: ["kant", "fichte", "schelling", "hegel", "schopenhauer"] },
    { id: "g-faith", kind: "direction", label: "Философия веры и чувства", members: ["hamann", "jacobi", "herder"] },
    { id: "g-moral", kind: "direction", label: "Философия морального чувства", members: ["shaftesbury", "hutcheson"] },
    { id: "s-cart", kind: "school", label: "Картезианство", members: ["descartes", "malebranche", "arnauld"] },
    { id: "s-lw", kind: "school", label: "Лейбнице-вольфовская школа", members: ["leibniz", "wolff", "baumgarten", "mendelssohn"] },
    { id: "s-scot", kind: "school", label: "Шотландская школа здравого смысла", members: ["reid"] },
    { id: "s-enc", kind: "school", label: "Энциклопедисты", members: ["diderot", "dalembert", "helvetius", "voltaire", "montesquieu", "rousseau"] },
    { id: "s-jena", kind: "school", label: "Йенский кружок", members: ["fichte", "schelling", "hegel"] },
  ],
  links,
  // без даты: не стоят на оси, находятся поиском с пометкой
  undated: [
    { id: "u-innate", label: "Врождённые идеи", type: "concept" },
    { id: "u-induction", label: "Проблема индукции", type: "problem" },
  ],
};
