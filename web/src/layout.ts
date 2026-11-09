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
const PANEL = 28;
const PANEL_STRIP = 3;
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

export function computeLayout(m: LayoutMetrics): Layout {
  const wide = m.width >= 1280;
  const panelW = !m.panelOpen ? 0 : wide ? PANEL * m.root : PANEL_STRIP * m.root;
  const textMin = TEXT_MIN_CH * m.ch;
  const textMax = TEXT_MAX_CH * m.ch;

  let navPinned = m.pinned && wide;
  const tempCollapse =
    navPinned && m.panelOpen && m.width - NAV_PINNED * m.root - PANEL * m.root < PIN_A_MIN * m.root;
  if (tempCollapse) navPinned = false;
  const navW = navPinned ? NAV_PINNED * m.root : NAV_COLLAPSED * m.root;
  const A = m.width - navW - panelW;

  const k1Need = OFF_MIN * 2 * m.root + TOC_MIN * m.root + GAP_FULL * m.root + textMin + GAP_FIELD * m.root + FIELD * m.root;
  const k2Need = OFF_MIN * 2 * m.root + TOC_MIN * m.root + GAP_FULL * m.root + textMin;
  const k3Need = OFF_MIN * 2 * m.root + RAIL * m.root + GAP_RAIL * m.root + textMin;
  const k4Need = 2.5 * m.root + textMin + 1.5 * m.root;

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
