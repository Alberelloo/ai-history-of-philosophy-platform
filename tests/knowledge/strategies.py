"""Стратегии «вход + ожидание» для property-тестов названий и датировок.

Каждая стратегия собирает вход из частей с известным ответом и возвращает пару
``(вход, ожидание)``. Ожидание выводится из того, как стратегия построила вход, по тексту
спецификаций ``entity-naming`` и ``entity-dating`` (improve-extraction-naming), а не из кода:
модуль намеренно не импортирует ``naming``, ``dating`` и ``dates`` (проверяет
``test_strategies_oracle_independent``). Данные правил (стоп-слова, частицы, пределы)
переписаны сюда из спецификации и design.md, а не прочитаны из ``naming_rules.yaml``: так
расхождение данных со спецификацией тоже ловится.
"""

from __future__ import annotations

import unicodedata
import uuid
from typing import Any

from hypothesis import strategies as st

# --- данные из спецификации ----------------------------------------------------------------

DEFAULT_LIMIT = (6, 80)
LONG_LIMIT_TYPES = ("work", "event", "idea_event", "phenomenon")
LONG_LIMIT = (12, 160)
PERSON = "person"
# Типы реестра, к которым применяется правило названий (``source`` — вне правила).
CHECKED_TYPES = (
    "argument",
    "concept",
    "conception",
    "doctrine",
    "epoch",
    "event",
    "group",
    "idea_event",
    "person",
    "phenomenon",
    "place",
    "position",
    "problem",
    "term",
    "work",
)
NON_PERSON = tuple(t for t in CHECKED_TYPES if t != PERSON)
REGISTRY_TYPES = (*CHECKED_TYPES, "source")

STOPWORDS = (
    "some",
    "every",
    "this author",
    "the author above mentioned",
    "your Lordship",
    "children",
    "logicians",
    "ordinary mind",
    "the perceptive",
    "blind man",
    "blind mathematician",
    "modern philosopher",
    "anatomist of the mind",
    "the mathematical arguer",
    "поэт",
    "мальчик",
    "тот, кто чувствует",
)
PARTICLES = ("de", "d", "van", "von", "ibn", "al", "де", "д", "фон", "ван", "ибн", "аль")
APOSTROPHES = ("-", "'", "’")
EDGE_MARKS = ".,;:!?()[]«»\"'„“”"

LATIN_LOWER = "abcdefghijklmnopqrstuvwxyzäöüéèçñ"
CYR_LOWER = "абвгдежзийклмнопрстуфхцчшщъыьэюяё"
GREEK_LOWER = "αβγδεζηθικλμνξοπρστυφχψωἀἐἰὀὐἠὠ"
OTHER_LETTERS = "אבגדהוזחטابتثجح汉字仮名"
ROMAN = ("I", "II", "III", "IV", "V", "IX", "X", "XI", "XIV", "XVII", "XX", "XXI", "MDC")
LANG_SCRIPT = {
    "ru": "cyrillic",
    "en": "latin",
    "de": "latin",
    "fr": "latin",
    "la": "latin",
    "it": "latin",
    "el": "greek",
    "grc": "greek",
}
SCRIPT_LANG = {"cyrillic": "ru", "latin": "en", "greek": "el"}
GIVEN_LANGS = (None, "ru", "en", "de", "fr", "la", "it", "el", "grc", "und", "zz")


def limits(type_: str) -> tuple[int, int]:
    return LONG_LIMIT if type_ in LONG_LIMIT_TYPES else DEFAULT_LIMIT


def name_of(raw: str) -> str:
    """«Название» спецификации: ``strip()`` и NFC."""
    return unicodedata.normalize("NFC", raw.strip())


def expected_label(raw: str) -> str:
    """``label`` события отказа по правилу обрезки: ≤ 80 знаков — целиком, иначе 79 + «…»."""
    name = name_of(raw)
    return name if len(name) <= 80 else name[:79] + "…"


def search_form(text: str) -> str:
    """Нормализованное название по определению спецификации (для оракула)."""
    text = unicodedata.normalize("NFC", text).lower().replace("ё", "е")
    text = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in text)
    return " ".join(text.split())


STOP_FORMS = {search_form(s) for s in STOPWORDS}
FORBIDDEN_WORDS = {"the", "of", "and", "и", "author", *PARTICLES}


def sentinel() -> str:
    """Уникальный сторожевой токен только из латинских букв: не добавляет чисел в цитату."""
    return "SENTINEL" + uuid.uuid4().hex.translate(str.maketrans("0123456789", "ghijklmnop"))


# --- строительные блоки ---------------------------------------------------------------------


def _word(alphabet: str, min_size: int = 2, max_size: int = 9, capital: bool = True):
    def build(chars: str) -> str:
        return chars[0].upper() + chars[1:] if capital else chars

    return (
        st.text(alphabet=alphabet, min_size=min_size, max_size=max_size)
        .map(build)
        .filter(lambda w: search_form(w) not in FORBIDDEN_WORDS)
    )


def _cap_word(min_size: int = 2, max_size: int = 9):
    return st.one_of(_word(LATIN_LOWER, min_size, max_size), _word(CYR_LOWER, min_size, max_size))


def _ok_name(words: list[str]) -> bool:
    return search_form(" ".join(words)) not in STOP_FORMS


# --- правило названий -----------------------------------------------------------------------


@st.composite
def numbers(draw) -> tuple[tuple[str, str], str]:
    """Цифры со знаками: нет букв, есть цифра → ``number``. Любой тип под правилом."""
    type_ = draw(st.sampled_from(CHECKED_TYPES))
    digits = draw(st.lists(st.text("0123456789", min_size=1, max_size=4), min_size=1, max_size=4))
    seps = draw(
        st.lists(
            st.sampled_from([".", ",", " ", "-", "–", "/", ":"]),
            min_size=len(digits),
            max_size=len(digits),
        )
    )
    body = "".join(d + s for d, s in zip(digits, seps, strict=True)).rstrip()
    prefix = draw(st.sampled_from(["", "§ ", "(", "[", "№ ", "  "]))
    suffix = draw(st.sampled_from(["", ")", "]", ".", "  "]))
    return (type_, prefix + body + suffix), "number"


@st.composite
def blank(draw) -> tuple[tuple[str, str], str]:
    """Пустые, пробелы и знаки: ни буквы, ни цифры → ``empty``."""
    type_ = draw(st.sampled_from(CHECKED_TYPES))
    raw = draw(st.text(alphabet=" \t\n—–-.,;:!?()§«»…*/ ", max_size=12))
    return (type_, raw), "empty"


@st.composite
def long_phrases(draw) -> tuple[tuple[str, str], str]:
    """Больше предела слов или знаков (в т. ч. ровно предел + 1) → ``sentence``."""
    type_ = draw(st.sampled_from(CHECKED_TYPES))
    max_words, max_chars = limits(type_)
    if draw(st.booleans()):  # слов больше предела, знаков в пределе
        n = draw(st.integers(max_words + 1, max_words + 9))
        words = [draw(_cap_word(1, 3)) for _ in range(n)]
        text = " ".join(words)
        if len(text) > max_chars:  # знаков тоже больше — всё равно sentence
            pass
    else:  # слов в пределе, знаков больше
        n = draw(st.integers(1, max_words))
        target = draw(st.integers(max_chars + 1, max_chars + 120))
        base = max(2, target // n)
        words = [draw(_cap_word(base, base + 1)) for _ in range(n)]
        text = " ".join(words)
        if len(text) <= max_chars:
            text = text + draw(
                _word(
                    LATIN_LOWER, max_chars - len(text) + 1, max_chars - len(text) + 2, capital=False
                )
            )
    return (type_, text), "sentence"


@st.composite
def at_limit(draw) -> tuple[tuple[str, str], None]:
    """Ровно предел слов или ровно предел знаков у названия из заглавных слов → без причины."""
    type_ = draw(st.sampled_from(CHECKED_TYPES))
    max_words, max_chars = limits(type_)
    if draw(st.booleans()):
        words = [draw(_cap_word(2, 5)) for _ in range(max_words)]
        text = " ".join(words)
    else:
        n = draw(st.integers(1, max_words))
        # n слов, суммарно ровно max_chars знаков (с пробелами)
        letters = max_chars - (n - 1)
        sizes = [letters // n] * n
        sizes[-1] += letters - sum(sizes)
        alphabet = draw(st.sampled_from([LATIN_LOWER, CYR_LOWER]))
        words = [draw(_word(alphabet, s, s)) for s in sizes]
        text = " ".join(words)
    from hypothesis import assume

    assume(_ok_name(text.split()))
    return (type_, text), None


@st.composite
def stopwords_perturbed(draw) -> tuple[tuple[str, str], str]:
    """Стоп-слово в любом регистре, с лишними пробелами, знаками, ``ё`` и в NFD → ``stopword``.

    Для персоны — только с заглавной первой буквой и без шаблона «the author …»: иначе раньше
    срабатывает ``not_a_name`` (порядок правил), и такое ожидание даёт ``not_names``."""
    word = draw(st.sampled_from(STOPWORDS))
    type_ = draw(st.sampled_from(CHECKED_TYPES))
    chars = list(word)
    for i, ch in enumerate(chars):
        if ch.isalpha() and draw(st.booleans()):
            chars[i] = ch.swapcase()
    text = "".join(chars)
    if draw(st.booleans()):
        text = text.replace("е", "ё").replace("Е", "Ё")
    sep = draw(st.sampled_from([" ", "  ", " \t", " - ", ", "]))
    text = sep.join(text.split(" "))
    text = draw(st.sampled_from(["", " ", "  "])) + text + draw(st.sampled_from(["", " ", "."]))
    if draw(st.booleans()):
        text = unicodedata.normalize("NFD", text)
    if type_ == PERSON:
        text = text.lstrip()
        first = next(i for i, ch in enumerate(text) if ch.isalpha())
        text = text[:first] + text[first].upper() + text[first + 1 :]
        if search_form(text).startswith(("the author ", "author of ")):
            type_ = draw(st.sampled_from(NON_PERSON))
    return (type_, text), "stopword"


@st.composite
def proper_names(draw) -> tuple[tuple[str, str], None]:
    """Имена: заглавные слова, частицы (целым словом, с ``-``, ``'``, ``’``), римские числа.

    Ожидание — причины нет. Для непрерывных типов — также строчные термины."""
    type_ = draw(st.sampled_from(CHECKED_TYPES))
    words = [draw(_cap_word()) for _ in range(draw(st.integers(1, 3)))]
    if type_ == PERSON and draw(st.booleans()):
        particle = draw(st.sampled_from(PARTICLES))
        if draw(st.booleans()):
            particle = particle.capitalize()
        joiner = draw(st.sampled_from([" ", *APOSTROPHES]))
        words[0] = particle + joiner + words[0] if joiner != " " else words[0]
        if joiner == " ":
            words.insert(0, particle)
    if draw(st.booleans()):
        words.append(draw(st.sampled_from(ROMAN)))
    if type_ != PERSON and draw(st.booleans()):
        words = [w.lower() for w in words]
    from hypothesis import assume

    text = " ".join(words)
    max_words, max_chars = limits(type_)
    assume(len(text.split()) <= max_words and len(text) <= max_chars and _ok_name(words))
    return (type_, text), None


@st.composite
def not_names(draw) -> tuple[tuple[str, str], str]:
    """Персона: строчное описание, «the … of …»/«author of …» в любом регистре, склейка двух
    имён через ``and``/``и``/``&`` → ``not_a_name``."""
    kind = draw(st.sampled_from(["lower", "pattern", "glue"]))
    if kind == "lower":
        alphabet = draw(st.sampled_from([LATIN_LOWER, CYR_LOWER]))
        words = [draw(_word(alphabet, 2, 9, capital=False)) for _ in range(draw(st.integers(1, 4)))]
        text = " ".join(words)
    elif kind == "pattern":
        tail = [draw(_cap_word()) for _ in range(draw(st.integers(1, 2)))]
        middle = [
            draw(_word(LATIN_LOWER, 2, 8, capital=False)) for _ in range(draw(st.integers(1, 2)))
        ]
        form = draw(st.sampled_from(["the_of", "author_of", "the_author"]))
        if form == "the_of":
            words = ["the", *middle, "of", *tail]
        elif form == "author_of":
            words = ["author", "of", *tail]
        else:
            words = ["the", "author", *tail]
        words = ["".join(ch.swapcase() if draw(st.booleans()) else ch for ch in w) for w in words]
        text = " ".join(words)
    else:
        left = [draw(_cap_word()) for _ in range(draw(st.integers(1, 2)))]
        right = [draw(_cap_word()) for _ in range(draw(st.integers(1, 2)))]
        text = " ".join([*left, draw(st.sampled_from(["and", "и", "&"])), *right])
    from hypothesis import assume

    assume(len(text.split()) <= 6 and len(text) <= 80)
    return (PERSON, text), "not_a_name"


def names_with_reason():
    """Все классы названий вместе: ((тип, сырое название), ожидаемая причина или None)."""
    return st.one_of(
        numbers(),
        blank(),
        long_phrases(),
        at_limit(),
        stopwords_perturbed(),
        proper_names(),
        not_names(),
    )


# --- письменность и язык --------------------------------------------------------------------

_ALPHABETS = {
    "cyrillic": CYR_LOWER,
    "latin": LATIN_LOWER,
    "greek": GREEK_LOWER,
    "other": OTHER_LETTERS,
}


@st.composite
def scripts_mix(
    draw, max_words: int = 6, max_chars: int = 80
) -> tuple[tuple[str, str | None], str, dict]:
    """Название из букв известных письменностей с заданными числами букв, слова из римских
    цифр и знаки по краям слов → ``((текст, переданный язык), ожидаемый язык, разбор)``.

    Ожидание по пп. 1–5: письменность — та, букв которой строго больше; равенство или нет
    букв — нет письменности; переданный язык остаётся, только если его письменность совпадает."""
    counts = {s: 0 for s in _ALPHABETS}
    words: list[str] = []
    for _ in range(draw(st.integers(1, max_words))):
        kind = draw(st.sampled_from(["cyrillic", "latin", "greek", "other", "mixed", "roman"]))
        if kind == "roman":
            word = draw(st.sampled_from(ROMAN))
        elif kind == "mixed":
            a, b = (
                draw(st.sampled_from(["cyrillic", "latin", "greek"])),
                draw(st.sampled_from(["cyrillic", "latin", "greek"])),
            )
            wa = draw(st.text(_ALPHABETS[a], min_size=1, max_size=4))
            wb = draw(st.text(_ALPHABETS[b], min_size=1, max_size=4))
            join = draw(st.sampled_from(["", "-"]))
            word = wa.capitalize() + join + wb
            counts[a] += len(wa)
            counts[b] += len(wb)
        else:
            body = draw(st.text(_ALPHABETS[kind], min_size=2, max_size=8))
            word = body[0].upper() + body[1:]
            counts[kind] += len(body)
        if kind != "roman" and kind != "mixed":
            pass
        left = draw(st.sampled_from(["", "", "(", "«", '"']))
        right = draw(st.sampled_from(["", "", ")", "»", ".", ",", '"']))
        words.append(left + word + right)
    text = " ".join(words)
    from hypothesis import assume

    assume(len(text) <= max_chars and search_form(text) not in STOP_FORMS)
    assume(any(ch.isalpha() for ch in text))
    top = max(counts.values())
    leaders = [s for s, c in counts.items() if c == top]
    script = leaders[0] if top > 0 and len(leaders) == 1 else None
    given = draw(st.sampled_from(GIVEN_LANGS))
    if given is not None and LANG_SCRIPT.get(given) == script and script is not None:
        lang = given
    else:
        lang = SCRIPT_LANG.get(script, "und") if script else "und"
    return (text, given), lang, {"counts": counts, "script": script, "latin": counts["latin"] > 0}


# --- элементы ответа модели -------------------------------------------------------------------


@st.composite
def fragment_items(draw, tag: str = "") -> dict[str, Any]:
    """Элемент ``entities`` и состояние онтологии с известным ответом.

    ``existing`` — какое написание элемента уже есть в онтологии основным названием (или
    ``None``), ``form`` — в каком виде (регистр, ``ё``, знаки: нормализованное название то же).
    Ожидание: при ``existing`` сущность не создаётся и утверждение привязано к ней; иначе
    создаётся одна сущность с основным ``ru`` (если оно русское) или ``name``."""
    type_ = draw(st.sampled_from(["person", "concept", "work", "term", "doctrine"]))
    ru = draw(_word(CYR_LOWER, 3, 9)) + tag.translate(
        str.maketrans("abcdefghijklmnop", "абвгдежзиклмнопр")
    )
    en = draw(_word(LATIN_LOWER, 3, 9)) + tag
    orig_lang = draw(st.sampled_from(["grc", "la", "de"]))
    orig_text = (
        draw(_word(GREEK_LOWER, 3, 9))
        if orig_lang == "grc"
        else draw(_word(LATIN_LOWER, 3, 9)) + tag + "us"
    )
    spellings = {"ru": ru, "en": en, "original": orig_text}
    present = draw(st.lists(st.sampled_from(["ru", "en", "original"]), unique=True, max_size=3))
    name_key = draw(st.sampled_from(["ru", "en"])) if present else "en"
    if name_key not in present:
        present = [name_key, *present]
    item: dict[str, Any] = {"name": spellings[name_key], "type": type_}
    for key in present:
        if key == "original":
            item["original"] = {"lang": orig_lang, "text": orig_text}
        else:
            item[key] = spellings[key]
    existing = draw(st.one_of(st.none(), st.sampled_from(present)))
    existing_text = None
    if existing is not None:
        text = spellings[existing]
        form = draw(st.sampled_from(["same", "upper", "lower", "yo", "punct"]))
        if form == "upper":
            text = text.upper()
        elif form == "lower" and type_ != PERSON:
            text = text.lower()
        elif form == "yo" and "е" in text:
            text = text.replace("е", "ё", 1)
        elif form == "punct":
            text = text + "."
        existing_text = text
    return {
        "item": item,
        "type": type_,
        "spellings": {k: spellings[k] for k in present},
        "orig_lang": orig_lang,
        "existing": existing,
        "existing_text": existing_text,
    }


# --- датировки ------------------------------------------------------------------------------

DASHES = ("–", "—", "-")
APPROX = ("ок.", "около", "c.", "circa")
ERA_TEXT = ("до н. э.", "до н.э.")
ERA_QUOTE = ("до н. э.", "до н.э.", "до нашей эры")
CENTURIES = (
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI",
    "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX", "XXI",
)  # fmt: skip
CONTEXT_WORDS = ("Кёнигсберге", "учение", "трактат", "философ", "писал", "жил", "эпоха")
UNPARSED = (
    "в эпоху Просвещения",
    "4 до н. э. – 65",
    "XVII в. – XVIII в.",
    "XVII–XVIII вв.",
    "12 мая 1724",
    "март 1724",
    "1724 г.",
    "1724–1804 гг.",
    "0",
    "2101",
    "+1724",
    "около середины века",
    "470 до н. э. – 399",
)


def _bounds_year(y: int, era: bool) -> int:
    return 1 - y if era else y


@st.composite
def _valid_dating(draw, person: bool, force: str | None = None) -> dict[str, Any]:
    """Текст даты по строке таблицы, его числа/век и ожидание (границы, span, precision)."""
    forms = ["interval", "approx_interval"] if person else [
        "year", "interval", "approx", "approx_interval", "century",
    ]  # fmt: skip
    if person and draw(st.integers(0, 3)) == 0:
        forms = ["year", "approx", "century"]  # одиночный год у персоны — single_year
    form = force or draw(st.sampled_from(forms))
    era = draw(st.booleans())
    dash = draw(st.sampled_from(DASHES))
    space = draw(st.sampled_from(["", " "]))
    era_marker = draw(st.sampled_from(ERA_TEXT))
    approx = draw(st.sampled_from(APPROX))
    if draw(st.booleans()):
        approx = approx.upper() if draw(st.booleans()) else approx.capitalize()
    numbers: list[int] = []
    roman = None
    if form == "century":
        r = draw(st.integers(1, 21))
        roman = CENTURIES[r - 1]
        text = f"{roman} в."
        lo, hi = (r - 1) * 100 + 1, r * 100
        if era:
            lo, hi = 1 - r * 100, 1 - ((r - 1) * 100 + 1)
        mid = (lo + hi) // 2
        expect = {"edges": (lo, None, None, hi), "span": (mid, mid), "precision": "century"}
    elif form in ("year", "approx"):
        y = draw(st.integers(1, 2100))
        numbers = [y]
        text = f"{approx} {y}" if form == "approx" else str(y)
        b = _bounds_year(y, era)
        d = 10 if form == "approx" else 0
        expect = {
            "edges": (b - d, b + d, b - d, b + d),
            "span": (b, b),
            "precision": "approx" if form == "approx" else "year",
        }
    else:
        a = draw(st.integers(1, 2100))
        c = draw(st.integers(1, 2100))
        y1, y2 = (max(a, c), min(a, c)) if era else (min(a, c), max(a, c))
        numbers = [y1, y2]
        core = f"{y1}{space}{dash}{space}{y2}"
        text = f"{approx} {core}" if form == "approx_interval" else core
        b1, b2 = sorted((_bounds_year(y1, era), _bounds_year(y2, era)))
        d = 5 if form == "approx_interval" else 0
        expect = {
            "edges": (b1 - d, b1 + d, b2 - d, b2 + d),
            "span": (b1, b2),
            "precision": "approx" if form == "approx_interval" else "year",
        }
    if era:
        text = f"{text} {era_marker}"
    single = form in ("year", "approx", "century")
    return {
        "text": text,
        "numbers": numbers,
        "roman": roman,
        "era": era,
        "form": form,
        "single": single,
        "expect": expect,
    }


def _quote_for(draw, d: dict[str, Any], era: bool | None = None) -> str:
    """Цитата с текстом даты (или теми же числами и эрой в другом окружении)."""
    era = d["era"] if era is None else era
    core = d["text"]
    for marker in ERA_TEXT:
        core = core.replace(" " + marker, "")
    if era:
        core = core + " " + draw(st.sampled_from(ERA_QUOTE))
    before = draw(st.sampled_from(CONTEXT_WORDS))
    after = draw(st.sampled_from(CONTEXT_WORDS))
    shape = draw(st.sampled_from(["paren", "plain", "years"]))
    if shape == "paren":
        return f"{before} ({core})"
    if shape == "years":
        return f"{before} в {core} {after}"
    return f"{before} {core}"


def _paragraph_with(draw, quote: str, token: str) -> str:
    """Абзац, где цитата стоит с иными пробелами, регистром и ``ё``/``е`` (правило поиска
    цитат: пробелы схлопываются, ``ё`` → ``е``, нижний регистр)."""
    variant = quote
    if draw(st.booleans()):
        variant = variant.replace(" ", "  ", 1)
    if draw(st.booleans()):
        variant = variant.replace("ё", "е")
    if draw(st.booleans()):
        variant = variant.replace("Кёнигсберге", "КЕНИГСБЕРГЕ")
    return f"{token} Об этом сказано так: {variant}. Далее речь о другом."


@st.composite
def datings(draw) -> dict[str, Any]:
    """Датировка элемента и фрагмент → ожидание: запись (границы, span, precision) или причина.

    Классы по порядку проверок: ``paragraph``, ``quote``, ``unparsed``, ``not_in_quote``
    (числа и век), ``era``, ``single_year`` и годная датировка."""
    person = draw(st.booleans())
    n = draw(st.integers(1, 4))
    token = sentinel()
    target = draw(
        st.sampled_from(
            ["ok", "ok", "century", "paragraph", "quote", "unparsed", "not_in_quote", "era"]
        )
    )
    d = draw(_valid_dating(person, "century" if target == "century" else None))
    quote = _quote_for(draw, d)
    text = d["text"]
    paragraph = draw(st.integers(1, n))
    reason = None
    if target == "paragraph":
        paragraph = draw(st.sampled_from([0, n + 1, -1, n + 7]))
        reason = "dating:paragraph"
    elif target == "quote":
        quote = quote + " " + sentinel()  # такого текста в абзаце нет
        reason = "dating:quote"
    elif target == "unparsed":
        text = draw(st.sampled_from(UNPARSED))
        quote = f"{draw(st.sampled_from(CONTEXT_WORDS))} {text}"
        reason = "dating:unparsed"
    elif target == "not_in_quote":
        if d["roman"]:
            r = CENTURIES.index(d["roman"]) + 1
            other = draw(st.sampled_from([c for c in CENTURIES if c != d["roman"]]))
            if d["roman"] + "I" in CENTURIES and draw(st.booleans()):
                other = d["roman"] + "I"  # «XVII» внутри «XVIII» — не отдельным словом
            quote = quote.replace(d["roman"], other)
            assert r
        else:
            missing = draw(st.sampled_from(d["numbers"]))
            shape = draw(st.sampled_from(["inside", "other"]))
            if shape == "inside":
                replacement = f"{missing}{draw(st.integers(0, 9))}"
                if draw(st.booleans()):
                    replacement = f"{draw(st.integers(1, 9))}{missing}"
            else:
                replacement = str(
                    draw(st.integers(1, 2100).filter(lambda v: v not in d["numbers"]))
                )
            quote = _replace_number(quote, missing, replacement)
        reason = "dating:not_in_quote"
    elif target == "era":
        quote = _quote_for(draw, d, era=not d["era"])
        reason = "dating:era"
    elif person and d["single"]:
        reason = "dating:single_year"
    paragraphs = [f"{sentinel()} Абзац {i} без цитаты." for i in range(1, n + 1)]
    home = paragraph if 1 <= paragraph <= n else 1
    if target == "quote":
        paragraphs[home - 1] = _paragraph_with(draw, quote.rsplit(" ", 1)[0], token)
    else:
        paragraphs[home - 1] = _paragraph_with(draw, quote, token)
    if reason is None and person and d["single"]:
        reason = "dating:single_year"
    return {
        "dating": {"text": text, "paragraph": paragraph, "quote": quote},
        "paragraphs": paragraphs,
        "type": PERSON if person else draw(st.sampled_from(["work", "event", "concept", "epoch"])),
        "person": person,
        "reason": reason,
        "expect": None if reason else d["expect"],
        "statement": "lifespan" if person else "dating",
        "token": token,
    }


def _replace_number(quote: str, number: int, replacement: str) -> str:
    """Заменяет каждое целое вхождение числа (по границам цифр) — без регулярных выражений
    проверяемого модуля, простым проходом по цифрам."""
    out, i, s = [], 0, str(number)
    while i < len(quote):
        if quote[i].isdigit():
            j = i
            while j < len(quote) and quote[j].isdigit():
                j += 1
            chunk = quote[i:j]
            out.append(replacement if chunk == s else chunk)
            i = j
        else:
            out.append(quote[i])
            i += 1
    return "".join(out)
