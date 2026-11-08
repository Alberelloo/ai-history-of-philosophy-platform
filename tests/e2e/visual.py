"""Визуальная проверка в браузере: проверки оформления по DOM и сравнение снимков с эталонами.

Проверки по DOM работают везде (в том числе в CI на Linux): цвета равны токенам, шрифты
загружены, нет горизонтальной прокрутки, области не пересекаются, текст не обрезан, контраст
не ниже 4.5:1, у фокуса с клавиатуры есть кольцо.

Снимки сравниваются с эталонами ``tests/e2e/visual/baselines/<sys.platform>/<имя>.png``: шрифты
и сглаживание различаются между системами, поэтому эталоны свои для каждой платформы. Если
эталонов текущей платформы нет, сравнение пропускается. Эталоны пишутся только явной командой:
``PHILOGRAPH_UPDATE_SNAPSHOTS=1``. При расхождении в ``tests/e2e/visual/results/`` остаются
фактический снимок, эталон и карта различий.
"""

from __future__ import annotations

import itertools
import os
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent / "visual"
BASELINES = HERE / "baselines" / sys.platform
RESULTS = HERE / "results"
UPDATE = os.environ.get("PHILOGRAPH_UPDATE_SNAPSHOTS") == "1"
# Доля отличающихся пикселей, выше которой снимок считается изменившимся.
MAX_DIFF_RATIO = 0.005
# Разница канала, которую ещё списываем на сглаживание шрифтов и краёв.
CHANNEL_TOLERANCE = 40

# 2560 — плавный масштаб (9.7): корневой кегль растёт, и всё в rem растёт вместе с ним.
WIDTHS = (1024, 1280, 1440, 1920, 2560)
# Ширины проверки боковой панели: свёрнутая и закреплённая не закрывают текст главы.
SIDEBAR_WIDTHS = (1024, 1280, 1440, 1920)


# --- подготовка страницы -------------------------------------------------------------


def settle(page, *, network: bool = True) -> None:
    """Ждёт шрифтов и конца перестроек: снимок и измерения стабильны. ``network=False`` — не
    ждать тишины в сети (снимок состояния, где запрос намеренно висит: «загружается»)."""
    # Наведение после клика меняло бы вид кнопок; угол — справа внизу: слева боковая панель,
    # и указатель над ней раскрыл бы её.
    size = page.viewport_size or {"width": 1280, "height": 800}
    page.mouse.move(size["width"] - 1, size["height"] - 1)
    if network:
        page.wait_for_load_state("networkidle")
    page.evaluate("document.fonts.ready.then(() => true)")
    page.evaluate(
        "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))"
    )


def token(page, name: str) -> str:
    """Значение токена на странице (с учётом темы): ``#eff1ec``."""
    return page.evaluate(
        "n => getComputedStyle(document.documentElement).getPropertyValue('--' + n).trim()", name
    )


# Перевод любого цвета CSS в [r, g, b, a] через холст: так понимаются и rgb(), и color-mix.
_RGBA_JS = """
const ctx = (() => {
  const c = document.createElement('canvas'); c.width = c.height = 1;
  return c.getContext('2d', { willReadFrequently: true });
})();
function rgba(color) {
  ctx.clearRect(0, 0, 1, 1);
  ctx.fillStyle = '#000'; ctx.fillStyle = color;
  ctx.fillRect(0, 0, 1, 1);
  const d = ctx.getImageData(0, 0, 1, 1).data;
  return [d[0], d[1], d[2], d[3] / 255];
}
"""


def rgba(page, color: str) -> list[float]:
    return page.evaluate(f"c => {{ {_RGBA_JS} return rgba(c); }}", color)


def computed(page, selector: str, prop: str) -> list[float]:
    """Вычисленный цвет свойства у первого элемента: [r, g, b, a]."""
    return page.evaluate(
        f"""([sel, prop]) => {{ {_RGBA_JS}
        return rgba(getComputedStyle(document.querySelector(sel))[prop]); }}""",
        [selector, prop],
    )


def assert_color(page, selector: str, prop: str, token_name: str) -> None:
    actual = computed(page, selector, prop)
    expected = rgba(page, token(page, token_name))
    assert actual[:3] == expected[:3], (selector, prop, token_name, actual, expected)


# --- шрифты ---------------------------------------------------------------------------


def loaded_families(page) -> set[str]:
    return set(
        page.evaluate(
            "[...document.fonts].filter(f => f.status === 'loaded')"
            ".map(f => f.family.replace(/[\"']/g, ''))"
        )
    )


def font_family(page, selector: str) -> str:
    return page.evaluate("s => getComputedStyle(document.querySelector(s)).fontFamily", selector)


# --- раскладка ------------------------------------------------------------------------


def assert_no_horizontal_scroll(page) -> None:
    sizes = page.evaluate(
        "({scroll: document.documentElement.scrollWidth,"
        " client: document.documentElement.clientWidth})"
    )
    assert sizes["scroll"] <= sizes["client"], f"горизонтальная прокрутка: {sizes}"


@dataclass
class Box:
    name: str
    left: float
    top: float
    right: float
    bottom: float

    def intersects(self, other: Box, slack: float = 0.5) -> bool:
        return (
            self.left < other.right - slack
            and other.left < self.right - slack
            and self.top < other.bottom - slack
            and other.top < self.bottom - slack
        )


def boxes(page, selectors: list[str]) -> list[Box]:
    """Прямоугольники первых видимых элементов (без прокрутки внутри областей)."""
    found = page.evaluate(
        """sels => sels.map(s => {
            const el = [...document.querySelectorAll(s)].find(e => e.getClientRects().length);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {name: s, left: r.left, top: r.top, right: r.right, bottom: r.bottom};
        })""",
        selectors,
    )
    missing = [s for s, b in zip(selectors, found, strict=True) if b is None]
    assert not missing, f"нет областей: {missing}"
    return [Box(**b) for b in found]


def assert_no_overlap(page, selectors: list[str]) -> None:
    """Заданные области не накладываются друг на друга."""
    items = boxes(page, selectors)
    clashes = [
        (a.name, b.name) for i, a in enumerate(items) for b in items[i + 1 :] if a.intersects(b)
    ]
    assert not clashes, f"области перекрываются: {clashes} {items}"


def assert_separated(page, selector: str, min_gap: float = 4.0) -> None:
    """Соседние элементы в строке разделены промежутком и не перекрываются."""
    rects = page.evaluate(
        """s => [...document.querySelectorAll(s)].filter(e => e.getClientRects().length)
            .map(e => { const r = e.getBoundingClientRect();
                        return [e.textContent.trim(), r.left, r.right]; })
            .sort((a, b) => a[1] - b[1])""",
        selector,
    )
    assert len(rects) >= 2, rects
    for (name_a, _, right_a), (name_b, left_b, _) in itertools.pairwise(rects):
        assert left_b - right_a >= min_gap, f"слиплись: {name_a!r} и {name_b!r} ({rects})"


def assert_stacked(page, selector: str, min_gap: float = 0.0) -> None:
    """Видимые элементы в колонке идут друг под другом и не перекрываются по высоте."""
    rects = page.evaluate(
        """s => [...document.querySelectorAll(s)].filter(e => e.getClientRects().length)
            .map(e => { const r = e.getBoundingClientRect();
                        return [e.textContent.trim().slice(0, 30), r.top, r.bottom]; })
            .sort((a, b) => a[1] - b[1])""",
        selector,
    )
    assert len(rects) >= 2, rects
    for (name_a, _, bottom_a), (name_b, top_b, _) in itertools.pairwise(rects):
        assert top_b - bottom_a >= min_gap - 0.5, f"наложились: {name_a!r} и {name_b!r} ({rects})"


# --- боковая панель -------------------------------------------------------------------


def sidebar_state(page) -> str:
    return page.locator(".sidebar").get_attribute("data-state")


def sidebar_width(page) -> float:
    return page.evaluate("document.querySelector('.sidebar').getBoundingClientRect().width")


def expand_sidebar(page) -> None:
    """Раскрывает боковую панель наведением и ждёт конца анимации ширины."""
    page.locator(".sidebar__brand").hover()
    page.wait_for_function(
        """() => { const s = document.querySelector('.sidebar');
            const root = parseFloat(getComputedStyle(document.documentElement).fontSize);
            const toPx = v => v.endsWith('rem') ? parseFloat(v) * root : parseFloat(v);
            return s.dataset.state !== 'collapsed'
            && Math.abs(s.getBoundingClientRect().width
            - toPx(getComputedStyle(document.documentElement).getPropertyValue(
            s.dataset.state === 'pinned' ? '--sidebar-pinned' : '--sidebar-open'))) < 1; }"""
    )


def collapse_sidebar(page) -> None:
    """Указатель уходит с панели: она сворачивается (если не закреплена)."""
    size = page.viewport_size or {"width": 1280, "height": 800}
    page.mouse.move(size["width"] - 5, size["height"] - 5)
    page.wait_for_function(
        "() => { const s = document.querySelector('.sidebar');"
        " return s.dataset.state !== 'expanded' && (s.dataset.state === 'pinned'"
        " || s.getBoundingClientRect().width <= 57); }"
    )


def assert_fills_width(page, selector: str) -> None:
    """Первый ряд сетки доходит до её правого края: справа нет пустой дорожки."""
    edges = page.evaluate(
        """s => { const grid = document.querySelector(s);
            const items = [...grid.children].filter(e => e.getClientRects().length);
            const top = items[0].getBoundingClientRect().top;
            const row = items.filter(e => Math.abs(e.getBoundingClientRect().top - top) < 1);
            return {grid: grid.getBoundingClientRect().right,
                    last: row[row.length - 1].getBoundingClientRect().right}; }""",
        selector,
    )
    assert abs(edges["grid"] - edges["last"]) <= 1, f"сетка не заполняет ширину: {edges}"


def clipped_text(page) -> list[str]:
    """Видимые элементы, у которых текст не помещается и обрезан: по ширине (overflow
    hidden/clip, многоточие) или по высоте (overflow-y hidden/clip, ограничение строк)."""
    return page.evaluate(
        """() => [...document.querySelectorAll('body *')].filter(el => {
            if (!el.getClientRects().length || el.closest('svg')) return false;
            const st = getComputedStyle(el);
            if (st.visibility === 'hidden') return false;
            const clipsX = ['hidden', 'clip'].includes(st.overflowX)
                || st.textOverflow === 'ellipsis';
            const clamp = st.webkitLineClamp && st.webkitLineClamp !== 'none';
            const clipsY = ['hidden', 'clip'].includes(st.overflowY) || clamp;
            if (!clipsX && !clipsY) return false;
            const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
            return hasText && ((clipsX && el.scrollWidth > el.clientWidth + 1)
                || (clipsY && el.scrollHeight > el.clientHeight + 1));
        }).map(el => el.className + ': ' + el.textContent.trim().slice(0, 60))"""
    )


def assert_no_clipped_text(page) -> None:
    clipped = clipped_text(page)
    assert not clipped, f"обрезанный текст: {clipped}"


# --- доступность ----------------------------------------------------------------------


def low_contrast(page, minimum: float = 4.5) -> list[dict]:
    """Видимый текст с контрастом ниже порога к фактическому фону (с учётом прозрачности)."""
    return page.evaluate(
        f"""min => {{ {_RGBA_JS}
        const lum = c => {{
            const f = v => {{ v /= 255;
                return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }};
            return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
        }};
        const over = (top, bottom) => {{
            const a = top[3];
            return [0, 1, 2].map(i => top[i] * a + bottom[i] * (1 - a)).concat(1);
        }};
        const background = el => {{
            const layers = [];
            for (let e = el; e; e = e.parentElement) {{
                const c = rgba(getComputedStyle(e).backgroundColor);
                if (c[3] > 0) layers.push(c);
                if (c[3] >= 1) break;
            }}
            let result = rgba(getComputedStyle(document.documentElement).backgroundColor);
            if (result[3] < 1) result = [255, 255, 255, 1];
            for (const layer of layers.reverse()) result = over(layer, result);
            return result;
        }};
        const faded = el => {{
            for (let e = el; e; e = e.parentElement) {{
                if (parseFloat(getComputedStyle(e).opacity) < 1) return true;
                if (e.matches && e.matches(':disabled, [aria-disabled=true]')) return true;
            }}
            return false;
        }};
        const out = [];
        for (const el of document.querySelectorAll('body *')) {{
            if (!el.getClientRects().length || el.closest('svg')) continue;
            const text = [...el.childNodes].filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim()).join('');
            if (!text) continue;
            const st = getComputedStyle(el);
            if (st.visibility === 'hidden' || faded(el)) continue;
            const r = el.getBoundingClientRect();
            if (r.bottom < 0 || r.top > innerHeight) continue;
            const bg = background(el);
            const fg = over(rgba(st.color), bg);
            const [hi, lo] = [lum(fg), lum(bg)].sort((a, b) => b - a);
            const ratio = (hi + 0.05) / (lo + 0.05);
            if (ratio < min) out.push({{text: text.slice(0, 40), ratio: +ratio.toFixed(2),
                cls: String(el.className)}});
        }}
        return out;
    }}""",
        minimum,
    )


def assert_contrast(page, minimum: float = 4.5) -> None:
    bad = low_contrast(page, minimum)
    assert not bad, f"контраст ниже {minimum}: {bad}"


def unstyled_buttons(page) -> list[str]:
    """Видимые кнопки без оформления дизайн-системы (стандартные серые кнопки браузера)."""
    return page.evaluate(
        """() => [...document.querySelectorAll('button')]
            .filter(b => b.getClientRects().length)
            .filter(b => ![...b.classList].some(c => c.startsWith('pg-')))
            .map(b => b.outerHTML.slice(0, 80))"""
    )


def focus_ring(page) -> dict:
    """Оформление элемента в фокусе: есть ли видимое кольцо."""
    return page.evaluate(
        """() => { const el = document.activeElement;
            // Флажок или радиокнопка внутри подписи-метки: кольцо рисуется на подписи.
            const own = getComputedStyle(el);
            const bare = own.boxShadow === 'none' && own.outlineStyle === 'none';
            const st = bare && el.closest('label') ? getComputedStyle(el.closest('label')) : own;
            return {tag: el.tagName, cls: String(el.className),
                    text: el.textContent.trim().slice(0, 30),
                    shadow: st.boxShadow, outline: st.outlineStyle,
                    visible: el.matches(':focus-visible')}; }"""
    )


def assert_focus_ring(page, presses: int = 1) -> dict:
    for _ in range(presses):
        page.keyboard.press("Tab")
    state = focus_ring(page)
    assert state["tag"] != "BODY", "фокус не попал на элемент"
    assert state["visible"], state
    assert state["shadow"] != "none" or state["outline"] != "none", f"нет кольца фокуса: {state}"
    return state


# --- снимки ---------------------------------------------------------------------------


def reader_name(state: str, theme: str, lang: str, width: int) -> str:
    """Имя снимка экрана чтения по 14.3: ``reader-<состояние>-<тема>-<язык>-<ширина>``."""
    return f"reader-{state}-{theme}-{lang}-{width}"


# Меняется от запуска к запуску: дата и время последнего обмена в строках сессий, время с
# отправки в строке стадий, секунды в итоге ответа.
UNSTABLE = (".assistant__session-meta", ".assistant__stage-meta", ".assistant__summary")


class SnapshotMismatch(AssertionError):
    pass


def compare(actual: Path, expected: Path, name: str) -> float:
    """Доля отличающихся пикселей; при превышении порога — файлы для разбора и ошибка."""
    from PIL import Image, ImageChops

    a = Image.open(actual).convert("RGB")
    b = Image.open(expected).convert("RGB")
    RESULTS.mkdir(parents=True, exist_ok=True)
    if a.size != b.size:
        a.save(RESULTS / f"{name}-actual.png")
        b.save(RESULTS / f"{name}-expected.png")
        raise SnapshotMismatch(f"{name}: размер {a.size} вместо {b.size}")
    diff = ImageChops.difference(a, b)
    channels = diff.split()
    worst = channels[0]
    for channel in channels[1:]:
        worst = ImageChops.lighter(worst, channel)
    mask = worst.point(lambda v: 255 if v > CHANNEL_TOLERANCE else 0)
    changed = mask.histogram()[255]
    ratio = changed / (a.size[0] * a.size[1])
    if ratio > MAX_DIFF_RATIO:
        a.save(RESULTS / f"{name}-actual.png")
        b.save(RESULTS / f"{name}-expected.png")
        overlay = Image.blend(b, Image.new("RGB", b.size, (255, 255, 255)), 0.7)
        overlay.paste(Image.new("RGB", b.size, (220, 0, 60)), mask=mask)
        overlay.save(RESULTS / f"{name}-diff.png")
        raise SnapshotMismatch(
            f"{name}: отличается {ratio:.2%} пикселей (порог {MAX_DIFF_RATIO:.2%}); "
            f"снимок, эталон и карта различий в {RESULTS}"
        )
    return ratio


def snap(
    page, name: str, *, mask: list | None = None, full_page: bool = False, network: bool = True
) -> float | None:
    """Снимает экран и сравнивает с эталоном; возвращает долю различий или None без эталона."""
    settle(page, network=network)
    RESULTS.mkdir(parents=True, exist_ok=True)
    actual = RESULTS / f"{name}.png"
    page.screenshot(
        path=str(actual),
        animations="disabled",
        caret="hide",
        mask=[*(mask or []), *(page.locator(s) for s in UNSTABLE)],
        full_page=full_page,
    )
    expected = BASELINES / f"{name}.png"
    if UPDATE:
        BASELINES.mkdir(parents=True, exist_ok=True)
        expected.write_bytes(actual.read_bytes())
        actual.unlink()
        return 0.0
    if not expected.exists():
        # Эталона нет: остаются проверки по DOM, а снимок — в results/ для просмотра.
        return None
    ratio = compare(actual, expected, name)
    actual.unlink()
    return ratio


class Snaps:
    """Снимки нескольких экранов в одном тесте: сравниваются все, падение — в конце списком."""

    def __init__(self) -> None:
        self.failed: list[str] = []

    def __call__(self, page, name: str, **options) -> None:
        try:
            snap(page, name, **options)
        except SnapshotMismatch as error:
            self.failed.append(str(error))

    def check(self) -> None:
        if self.failed:
            raise SnapshotMismatch("; ".join(self.failed))
