// Раскладка экрана чтения K1–K4 (docs/design/features/reader-panels.md, 2.2 и 2.4).
// Чистая функция: вход — размеры окна и токенов в px, выход — выбранная раскладка и точные
// ширины колонок. Так раскладку можно проверять юнит-тестом, не поднимая браузер.

export type LayoutMode = "K1" | "K2" | "K3" | "K4";

export type Layout = {
  mode: LayoutMode;
  navWidth: number; // фактическая ширина навигации (с временным сворачиванием)
  tempCollapse: boolean; // закреплённая навигация временно свёрнута, чтобы панель поместилась
  text: number; // ширина колонки текста, px
  toc: number; // ширина оглавления, px; 0 — оглавления нет
  field: number; // ширина поля сносок, px; 0 — поля нет
  offsetLeft: number; // внешний отступ слева, px
  offsetRight: number; // внешний отступ справа, px
};

export type LayoutMetrics = {
  root: number; // корневой кегль, px
  ch: number; // ширина 1ch шрифта чтения, px
  width: number; // ширина окна, px
  pinned: boolean; // выбор «закрепить» в хранилище
  panelOpen: boolean; // открыта ли правая панель
};

// Токены в rem; 1rem = корневой кегль. До 1920px кегль 16px, дальше растёт (9.7).
const NAV_COLLAPSED = 3.5;
const NAV_PINNED = 17.5;
const PANEL = 28; // наименьшая ширина правой панели и ширина для правила сворачивания навигации
const PANEL_MAX = 36;
const PANEL_STEP = 0.5; // округление вниз
const PANEL_STRIP = 3;
const STRIP_GAP = 2; // развёрнутая полоска не доходит до навигации на 2rem
const TOC_MIN = 13;
const TOC_MAX = 17;
const FIELD = 18;
const RAIL = 3.5;
const GAP_FULL = 3; // оглавление → текст, полное оглавление (48px)
const GAP_RAIL = 2.5; // полоса → текст (40px)
const GAP_FIELD = 2.5; // текст → поле (40px)
const OFF_MIN = 2; // внешний отступ (32px)
const TEXT_MIN_CH = 62;
const TEXT_MAX_CH = 68;
// Минимальная свободная ширина A, при которой закреплённая навигация не сворачивается.
const PIN_A_MIN = 46.5; // 744px

// Сколько свободной ширины нужно каждой раскладке (px), по порядку K1–K4.
function needs(root: number, ch: number): [number, number, number, number] {
  const textMin = TEXT_MIN_CH * ch;
  return [
    OFF_MIN * 2 * root + TOC_MIN * root + GAP_FULL * root + textMin + GAP_FIELD * root + FIELD * root,
    OFF_MIN * 2 * root + TOC_MIN * root + GAP_FULL * root + textMin,
    OFF_MIN * 2 * root + RAIL * root + GAP_RAIL * root + textMin,
    2.5 * root + textMin + 1.5 * root,
  ];
}

// Навигация с учётом временного сворачивания: оно решается при наименьшей панели (28rem),
// иначе правило зависело бы от ширины, которую само определяет.
function navigation(m: LayoutMetrics): { navW: number; tempCollapse: boolean } {
  const wide = m.width >= 1280;
  let navPinned = m.pinned && wide;
  const tempCollapse =
    navPinned && m.panelOpen && m.width - NAV_PINNED * m.root - PANEL * m.root < PIN_A_MIN * m.root;
  if (tempCollapse) navPinned = false;
  return { navW: navPinned ? NAV_PINNED * m.root : NAV_COLLAPSED * m.root, tempCollapse };
}

// Ширина правой панели, px (redesign-entity-cards, visual-design «Раскладка экрана чтения»).
// Единственное место правила: раскладка K1–K4 и CSS-переменная --panel берут её отсюда.
// - полоска (окно 1024–1279): min(36rem, окно − навигация − 2rem), поверх текста;
// - 1280–1439: clamp(28rem, окно − навигация − потребность K4, 36rem);
// - от 1440: clamp(28rem, окно − навигация − потребность раскладки при 28rem, 36rem) —
//   раскладка при открытой панели та же, что при 28rem.
// Округление вниз до 0.5rem.
export function panelWidth(m: Omit<LayoutMetrics, "panelOpen">): number {
  const step = PANEL_STEP * m.root;
  const floor = (px: number) => Math.floor(px / step + 1e-6) * step;
  const min = PANEL * m.root;
  const max = PANEL_MAX * m.root;
  if (m.width < 1280) return floor(Math.max(min, Math.min(max, m.width - NAV_COLLAPSED * m.root - STRIP_GAP * m.root)));
  const { navW } = navigation({ ...m, panelOpen: true });
  const all = needs(m.root, m.ch);
  let need = all[3];
  if (m.width >= 1440) {
    const free = m.width - navW - min;
    need = all.find((n) => free >= n) ?? all[3];
  }
  return floor(Math.max(min, Math.min(max, m.width - navW - need)));
}

export function computeLayout(m: LayoutMetrics): Layout {
  const wide = m.width >= 1280;
  const panelW = !m.panelOpen ? 0 : wide ? panelWidth(m) : PANEL_STRIP * m.root;
  const textMin = TEXT_MIN_CH * m.ch;
  const textMax = TEXT_MAX_CH * m.ch;

  const { navW, tempCollapse } = navigation(m);
  const A = m.width - navW - panelW;

  const [k1Need, k2Need, k3Need, k4Need] = needs(m.root, m.ch);

  // Лишняя ширина: сначала колонка текста до 68ch, затем оглавление до 17rem, остаток — отступы.
  const distribute = (need: number, withToc: boolean, withField: boolean) => {
    let text = textMin;
    let toc = TOC_MIN * m.root;
    let extra = A - need;
    const grow = Math.min(extra, textMax - textMin);
    text += grow;
    extra -= grow;
    if (withToc) {
      const tocGrow = Math.min(extra, (TOC_MAX - TOC_MIN) * m.root);
      toc += tocGrow;
      extra -= tocGrow;
    }
    const offset = OFF_MIN * m.root + extra / 2;
    return { text, toc: withToc ? toc : 0, field: withField ? FIELD * m.root : 0, offsetLeft: offset, offsetRight: offset };
  };

  if (A >= k1Need) return { mode: "K1", navWidth: navW, tempCollapse, ...distribute(k1Need, true, true) };
  if (A >= k2Need) return { mode: "K2", navWidth: navW, tempCollapse, ...distribute(k2Need, true, false) };
  if (A >= k3Need) return { mode: "K3", navWidth: navW, tempCollapse, ...distribute(k3Need, false, false) };

  // K4: без оглавления и поля, отступы 40px слева и 24px справа.
  let text = textMin;
  let extra = A - k4Need;
  const grow = Math.min(extra, textMax - textMin);
  text += grow;
  extra -= grow;
  return {
    mode: "K4",
    navWidth: navW,
    tempCollapse,
    text,
    toc: 0,
    field: 0,
    offsetLeft: 2.5 * m.root + extra / 2,
    offsetRight: 1.5 * m.root + extra / 2,
  };
}
