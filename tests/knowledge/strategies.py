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
    max_words, max_chars = limits(type_)
    clean = name_of(text)
    if len(clean.split()) > max_words or len(clean) > max_chars:
        return (type_, text), "sentence"  # разделитель « - » добавил слова: предел раньше
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


@st.composite
def person_edge_names(draw) -> tuple[tuple[str, str], None]:
    """Границы правила ``not_a_name`` — названия без причины.

    ``particle_swapcase`` — частица с первой строчной и остальными заглавными («dE», «дЕ»):
    сравнение частиц без учёта регистра; ``glue_lower_right`` — союз перед словом со строчной
    («Кант и юм»): склейка — только между двумя словами с заглавной; ``glue_nonperson`` и
    ``pattern_nonperson`` — склейка и шаблон «the … of …» у типа не «персона»: ``not_a_name``
    только для персоны."""
    kind = draw(
        st.sampled_from(
            ["particle_swapcase", "glue_lower_right", "glue_nonperson", "pattern_nonperson"]
        )
    )
    from hypothesis import assume

    conj = draw(st.sampled_from(["and", "и", "&"]))
    if kind == "particle_swapcase":
        particle = draw(st.sampled_from([p for p in PARTICLES if len(p) > 1]))
        text = particle[0] + particle[1:].upper() + " " + draw(_cap_word())
        return (PERSON, text), None
    if kind == "glue_lower_right":
        left = draw(_cap_word())
        alphabet = draw(st.sampled_from([LATIN_LOWER, CYR_LOWER]))
        right = draw(_word(alphabet, 2, 9, capital=False))
        return (PERSON, f"{left} {conj} {right}"), None
    type_ = draw(st.sampled_from(NON_PERSON))
    tail = draw(_cap_word())
    if kind == "glue_nonperson":
        text = f"{draw(_cap_word())} {conj} {tail}"
    else:
        text = draw(
            st.sampled_from(
                [
                    f"The author of {tail}",
                    f"author of {tail}",
                    f"the author {tail}",
                    f"The x of {tail}",
                ]
            )
        )
    assume(_ok_name(text.split()) and search_form(text) not in STOP_FORMS)
    return (type_, text), None


@st.composite
def rule_order(draw) -> tuple[tuple[str, str], str]:
    """Порядок правил: ``empty`` и ``number`` раньше ``sentence`` (длинное без букв), а
    ``sentence`` раньше ``not_a_name`` (длинное строчное описание персоны)."""
    kind = draw(st.sampled_from(["number_long", "empty_long", "person_long_lower"]))
    if kind == "person_long_lower":
        max_words, _ = limits(PERSON)
        n = draw(st.integers(max_words + 1, max_words + 5))
        words = [draw(_word(LATIN_LOWER, 2, 5, capital=False)) for _ in range(n)]
        return (PERSON, " ".join(words)), "sentence"
    type_ = draw(st.sampled_from(CHECKED_TYPES))
    max_words, _ = limits(type_)
    n = draw(st.integers(max_words + 1, max_words + 4))
    if kind == "number_long":
        words = [draw(st.text("0123456789", min_size=1, max_size=2)) for _ in range(n)]
        return (type_, " ".join(words)), "number"
    words = [draw(st.sampled_from(list("-—.,;:!"))) for _ in range(n)]
    return (type_, " ".join(words)), "empty"


def names_with_reason():
    """Все классы названий вместе: ((тип, сырое название), ожидаемая причина или None)."""
    return st.one_of(
        person_edge_names(),
        rule_order(),
        numbers(),
        blank(),
        long_phrases(),
        at_limit(),
        stopwords_perturbed(),
        proper_names(),
        not_names(),
    )


# --- письменность и язык --------------------------------------------------------------------

# Границы диапазонов письменностей (entity-naming, п. 2): кириллица U+0400–U+052F (``ԯ`` —
# последняя), греческая U+0370–U+03FF и U+1F00–U+1FFF (``ῳ``), армянская ``Ա`` (U+0531) — прочая.
_ALPHABETS = {
    "cyrillic": CYR_LOWER + "ԁԯ",
    "latin": LATIN_LOWER,
    "greek": GREEK_LOWER + "ͱῳ",
    "other": OTHER_LETTERS + "աԱ",
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
        kind = draw(
            st.sampled_from(
                [
                    "cyrillic",
                    "latin",
                    "greek",
                    "other",
                    "mixed",
                    "roman",
                    "roman_letters",
                    "digits",
                ]
            )
        )
        if kind == "roman":
            word = draw(st.sampled_from(ROMAN))
        elif kind == "digits":
            # Цифры — не буквы (категория не ``L*``): письменности не добавляют.
            word = draw(st.sampled_from(["1781", "20.1", "§3", "1724–1804", "2"]))
        elif kind == "roman_letters":
            # Слово из букв IVXLCDM не целиком заглавными («Mill», «Civil», «Xiv») — латиница,
            # не римское число: римские — только заглавные (entity-naming).
            body = draw(st.text("ivxlcdm", min_size=2, max_size=6))
            word = draw(st.sampled_from([body.capitalize(), body]))
            counts["latin"] += len(body)
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
    "XXII в.",
    "XXX в.",
    "IIII в.",
    "0 в.",
    "I – V в.",
    "1 января 1724",
    "1724 – 1804 до н. э. – 3",
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
            [
                "ok",
                "ok",
                "century",
                "paragraph",
                "quote",
                "unparsed",
                "not_in_quote",
                "era",
                # две несработавшие проверки сразу: причина — первая по порядку
                "m_paragraph_quote",
                "m_quote_unparsed",
                "m_unparsed_numbers",
                "m_numbers_era",
                "m_era_single",
                "m_numbers_single",
            ]
        )
    )
    if target in ("m_era_single", "m_numbers_single"):
        person = True  # «один год у персоны» — только для персоны
    d = draw(
        _valid_dating(
            person,
            "century"
            if target == "century"
            else (
                draw(st.sampled_from(["year", "approx", "century"]))
                if target in ("m_era_single", "m_numbers_single")
                else None
            ),
        )
    )
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
        if draw(st.booleans()):
            text = draw(st.sampled_from(UNPARSED))
        else:
            # Обратный интервал нашей эры (Г1 > Г2), в том числе с «ок.»: формата нет в таблице.
            end = draw(st.integers(1, 2099))
            start = draw(st.integers(end + 1, 2100))
            approx = draw(st.sampled_from(["", "ок. ", "около "]))
            text = f"{approx}{start}{draw(st.sampled_from(DASHES))}{end}"
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
    elif target == "m_paragraph_quote":  # абзац вне фрагмента и цитаты в абзаце нет → paragraph
        paragraph = draw(st.sampled_from([0, n + 1, -1, n + 7]))
        quote = quote + " " + sentinel()
        reason = "dating:paragraph"
    elif target == "m_quote_unparsed":  # цитаты нет в абзаце и текст не из таблицы → quote
        text = draw(st.sampled_from(UNPARSED))
        quote = f"{draw(st.sampled_from(CONTEXT_WORDS))} {text} {sentinel()}"
        reason = "dating:quote"
    elif target == "m_unparsed_numbers":  # текст не из таблицы и чисел нет в цитате → unparsed
        text = draw(st.sampled_from(UNPARSED))
        quote = f"{draw(st.sampled_from(CONTEXT_WORDS))} {draw(st.sampled_from(CONTEXT_WORDS))}"
        reason = "dating:unparsed"
    elif target in ("m_numbers_era", "m_numbers_single"):
        # чисел текста нет в цитате (и эра другая / один год у персоны) → not_in_quote
        if d["roman"]:
            other = draw(st.sampled_from([c for c in CENTURIES if c != d["roman"]]))
            quote = quote.replace(d["roman"], other)
        else:
            missing = draw(st.sampled_from(d["numbers"]))
            replacement = str(draw(st.integers(1, 2100).filter(lambda v: v not in d["numbers"])))
            quote = _replace_number(quote, missing, replacement)
        if target == "m_numbers_era":
            quote = (
                quote.replace(" до нашей эры", "").replace(" до н. э.", "").replace(" до н.э.", "")
            )
            if not d["era"]:
                quote = quote + " до н. э."
        reason = "dating:not_in_quote"
    elif target == "m_era_single":  # другая эра у одного года персоны → era, не single_year
        quote = _quote_for(draw, d, era=not d["era"])
        reason = "dating:era"
    elif person and d["single"]:
        reason = "dating:single_year"
    paragraphs = [f"{sentinel()} Абзац {i} без цитаты." for i in range(1, n + 1)]
    home = paragraph if 1 <= paragraph <= n else 1
    if target in ("quote", "m_paragraph_quote", "m_quote_unparsed"):
        paragraphs[home - 1] = _paragraph_with(draw, quote.rsplit(" ", 1)[0], token)
    else:
        paragraphs[home - 1] = _paragraph_with(draw, quote, token)
    if reason is None and person and d["single"]:
        reason = "dating:single_year"
    return {
        "dating": {"text": text, "paragraph": paragraph, "quote": quote},
        "paragraphs": paragraphs,
        "type": PERSON
        if person
        else draw(st.sampled_from(["work", "event", "phenomenon", "idea_event", "epoch"])),
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


# --- персоны: качество и слияние вариантов (improve-person-quality) ------------------------


def not_persons():
    """Предложения персон, которые правило названий отклоняет, с ожидаемой причиной:
    строчные описания, «the … of …», склейки (``not_a_name``), обращения и группы
    из стоп-списка с заглавной (``stopword``), фразы длиннее предела (``sentence``)."""
    persons_only = st.one_of(not_names(), stopwords_perturbed(), long_phrases())
    return persons_only.map(_as_person).filter(_person_reason_kept)


def _as_person(case):
    """Вход другого типа как персона: предел персоны (6 слов, 80 знаков) может быть меньше
    предела исходного типа — тогда по порядку правил раньше срабатывает ``sentence``."""
    (_type, raw), reason = case
    max_words, max_chars = limits(PERSON)
    clean = name_of(raw)
    if reason == "stopword" and (len(clean.split()) > max_words or len(clean) > max_chars):
        reason = "sentence"
    return (PERSON, raw), reason


def _person_reason_kept(case) -> bool:
    """Стоп-слово, сгенерированное для другого типа, у персоны может дать ``not_a_name``
    (строчная первая буква, шаблон) — такие входы отбрасываются, а не переобъясняются."""
    (_type, raw), reason = case
    if reason != "stopword":
        return True
    text = raw.strip()
    first = next((ch for ch in text if ch.isalpha()), "")
    form = search_form(text)
    return first.isupper() and not form.startswith(("the author ", "author of "))


DATE_BASE = (1685, 1753)
FACE_KINDS = (
    "plain",
    "plain",
    "plain",
    "two_qids",
    "dates",
    "qids_distinct",
    "confirmed",
    "decided",
    "decided3",
    "variant_single",
    "variant_multi",
    "date_chain",
    "model_pair",
    "mixed_type",
    "review_inside",
)
_TAGS = "бвгджзклмн"
_LTAGS = "bcdfghklmn"


def _face_word(draw, index: int, cyrillic: bool) -> str:
    base = draw(_word(CYR_LOWER if cyrillic else LATIN_LOWER, 3, 6))
    tag = (_TAGS if cyrillic else _LTAGS)[index % 10] * (index // 10 + 2)
    return base + tag


@st.composite
def persons_with_variants(draw, max_faces: int = 4) -> dict[str, Any]:
    """Персоны по «лицам» и ожидаемый итог слияния вариантов по правилу ``person-quality``.

    Запись: ``{"key": (лицо, номер), "names": [(lang, text, kind)], "qid", "dates"}``.
    Лицо: вид, записи, ожидаемые блоки слияния (``merge``: [ключи], ``reason``) и пары
    очереди (``queue``: {frozenset(ключ1, ключ2): причина}). Названия разных лиц не
    пересекаются (уникальный хвост на лицо)."""
    faces = []
    confirmed, decided, model = [], [], []
    qid_counter = iter(range(900100, 999999))
    for f in range(draw(st.integers(1, max_faces))):
        kind = draw(st.sampled_from(FACE_KINDS))
        cyr = draw(st.booleans())
        lang = "ru" if cyr else "en"
        word = _face_word(draw, f, cyr)
        records: list[dict[str, Any]] = []
        face: dict[str, Any] = {"kind": kind, "records": records, "merge": [], "queue": {}}

        def rec(i, names, qid=None, dates=None, f=f, records=records):
            records.append({"key": (f, i), "names": names, "qid": qid, "dates": dates})

        if kind == "plain":
            n = draw(st.integers(1, 4))
            with_qid = draw(st.sampled_from([None, *range(n)]))
            dated = draw(st.sampled_from(["none", "equal", "within", "one_side"]))
            for i in range(n):
                text = word if draw(st.booleans()) else word.upper() if i else word
                if dated == "none" or (dated == "one_side" and i > 0):
                    dates = None
                elif dated == "equal" or dated == "one_side":
                    dates = DATE_BASE
                else:
                    s = draw(st.integers(0, 4))
                    dates = (DATE_BASE[0] + s, DATE_BASE[1] + s)
                qid = f"Q{next(qid_counter)}" if with_qid == i else None
                rec(i, [(lang, text, "primary")], qid, dates)
            if n > 1:
                face["merge"] = [[(f, i) for i in range(n)]]
                face["reason"] = "merge:name"
        elif kind == "two_qids":
            rec(0, [(lang, word, "primary")], f"Q{next(qid_counter)}")
            rec(1, [(lang, word, "primary")])
            rec(2, [(lang, word, "primary")], f"Q{next(qid_counter)}")
            face["queue"] = {
                frozenset({(f, 0), (f, 1)}): "review:qid_cluster",
                frozenset({(f, 1), (f, 2)}): "review:qid_cluster",
            }
        elif kind == "dates":
            gap = draw(st.integers(5, 200))
            rec(0, [(lang, word, "primary")], None, DATE_BASE)
            rec(1, [(lang, word, "primary")], None, (DATE_BASE[0] + gap, DATE_BASE[1] + gap))
            face["queue"] = {frozenset({(f, 0), (f, 1)}): "review:dates"}
        elif kind == "date_chain":
            # Компонента «даты A — без дат — противоречащие даты C»: рёбра merge:name через
            # среднюю, у крайних review:dates → слияний нет, все пары в очередь review:dates.
            gap = draw(st.integers(5, 200))
            rec(0, [(lang, word, "primary")], None, DATE_BASE)
            rec(1, [(lang, word, "primary")])
            rec(2, [(lang, word, "primary")], None, (DATE_BASE[0] + gap, DATE_BASE[1] + gap))
            face["queue"] = {
                frozenset({(f, a), (f, b)}): "review:dates" for a, b in ((0, 1), (1, 2), (0, 2))
            }
        elif kind == "model_pair":
            # Шаг 7: один элемент ответа модели дал оба написания → merge:model_pair (только с
            # парами модели; без них — apart:none: ни слияния, ни очереди).
            other = _face_word(draw, f, not cyr)
            rec(0, [(lang, word, "primary")])
            rec(1, [("en" if cyr else "ru", other, "primary")])
            model.append(((f, 0), (f, 1)))
            face["merge"] = [[(f, 0), (f, 1)]]
            face["reason"] = "merge:model_pair"
            face["needs_model"] = True
        elif kind == "mixed_type":
            # Шаг 1: модель связала персону с понятием того же названия → apart:type; две
            # персоны с общим основным сливаются, понятие остаётся.
            rec(0, [(lang, word, "primary")])
            rec(1, [(lang, word, "primary")])
            records.append(
                {
                    "key": (f, 2),
                    "names": [(lang, word, "primary")],
                    "qid": None,
                    "dates": None,
                    "type": "concept",
                }
            )
            model.append(((f, 0), (f, 2)))
            face["merge"] = [[(f, 0), (f, 1)]]
            face["reason"] = "merge:name"
        elif kind == "review_inside":
            # Пара review:single_name (основное B = вариант C), обе стороны которой в одной
            # сливаемой компоненте (B и C подтверждены человеком для QID A) — в очередь не идёт.
            holder = _face_word(draw, f + 30, not cyr)
            third = _face_word(draw, f + 60, cyr)
            rec(0, [("en" if cyr else "ru", holder, "primary")], f"Q{next(qid_counter)}")
            rec(1, [(lang, word, "primary")])
            rec(2, [(lang, third, "primary"), (lang, word, "variant")])
            confirmed += [((f, 1), (f, 0)), ((f, 2), (f, 0))]
            face["merge"] = [[(f, 0), (f, 1), (f, 2)]]
            face["reason"] = "merge:qid_confirmed"
        elif kind == "qids_distinct":
            rec(0, [(lang, word, "primary")], f"Q{next(qid_counter)}")
            rec(1, [(lang, word, "primary")], f"Q{next(qid_counter)}")
        elif kind == "confirmed":
            other = _face_word(draw, f, not cyr)
            rec(0, [("en" if cyr else "ru", other, "primary")], f"Q{next(qid_counter)}")
            rec(1, [(lang, word, "primary")])
            confirmed.append(((f, 1), (f, 0)))
            face["merge"] = [[(f, 0), (f, 1)]]
            face["reason"] = "merge:qid_confirmed"
        elif kind == "decided":
            rec(0, [(lang, word, "primary")])
            rec(1, [(lang, word, "primary")])
            decided.append(((f, 0), (f, 1)))
        elif kind == "decided3":
            for i in range(3):
                rec(i, [(lang, word, "primary")])
            decided.append(((f, 0), (f, 1)))
            face["queue"] = {
                frozenset({(f, 0), (f, 2)}): "review:decided_conflict",
                frozenset({(f, 1), (f, 2)}): "review:decided_conflict",
            }
        elif kind == "variant_single":
            first = _face_word(draw, f + 50, cyr)
            rec(0, [(lang, f"{first.capitalize()} {word}", "primary"), (lang, word, "variant")])
            rec(1, [(lang, word, "primary")])
            face["queue"] = {frozenset({(f, 0), (f, 1)}): "review:single_name"}
        else:  # variant_multi
            first = _face_word(draw, f + 50, cyr)
            two = f"{first.capitalize()} {word}"
            alien = _face_word(draw, f + 70, not cyr)
            rec(0, [("en" if cyr else "ru", alien, "primary"), (lang, two, "variant")])
            rec(1, [(lang, two, "primary")])
            face["queue"] = {frozenset({(f, 0), (f, 1)}): "review:variant"}
        faces.append(face)
    return {"faces": faces, "confirmed": confirmed, "decided": decided, "model": model}


def expected_kept(face_records: list[dict[str, Any]], ids: dict, links: dict | None = None):
    """Оставшаяся по правилу: с QID; иначе больше ссылок; иначе меньший идентификатор."""
    with_qid = [r for r in face_records if r["qid"]]
    if with_qid:
        return ids[with_qid[0]["key"]]
    links = links or {}
    return min((ids[r["key"]] for r in face_records), key=lambda i: (-links.get(i, 0), i))


# --- онтология с дублями: слияние с перенаправлением (ontology-entities, MODIFIED) ---------

REL_TYPES = ("influenced_by", "criticizes")  # персона → персона, несимметричные
SOURCES = ("s_a", "s_b", "s_c")


@st.composite
def ontology_with_duplicates(draw) -> dict[str, Any]:
    """5–30 сущностей и пара персон ``K`` (оставшаяся, индекс 0) и ``R`` (удалённая, 1).

    Утверждения задаются индексами концов; генератор нарочно строит повторы, которые
    совпадут после слияния (одно и то же у K и у R), петли R → K, атрибуции на R,
    точные повторы атрибуции, подтверждения, упоминания и портреты с общим признаком.
    Ожидание считается в тесте из этих данных: отображение R → K и множества."""
    n_persons = draw(st.integers(3, 12))
    n_positions = draw(st.integers(max(0, 5 - n_persons), 30 - n_persons))
    kept_lang, removed_lang = draw(
        st.sampled_from([("en", "ru"), ("ru", "en"), ("en", "en"), ("ru", "ru")])
    )
    entities = [
        {
            "type": "person",
            "names": [(kept_lang, "Hume" if kept_lang == "en" else "Юм", "primary")],
        },
        {
            "type": "person",
            "names": [(removed_lang, "Юм" if removed_lang == "ru" else "Hume", "primary")],
        },
    ]
    if draw(st.booleans()):
        entities[0]["names"].append(("en", "David Hume", "variant"))
    if draw(st.booleans()):
        entities[1]["names"].append(("ru", "Давид Юм", "variant"))
    entities += [
        {"type": "person", "names": [("ru", f"Персона {i}", "primary")]}
        for i in range(2, n_persons)
    ]
    entities += [
        {"type": "position", "names": [("ru", f"Позиция {i}", "primary")]}
        for i in range(n_positions)
    ]
    qid_side = draw(st.sampled_from([None, 0, 1]))
    persons_ix = list(range(n_persons))
    positions_ix = list(range(n_persons, n_persons + n_positions))

    attribution = st.one_of(
        st.tuples(
            st.just("source"), st.sampled_from(SOURCES), st.sampled_from(["asserts", "supports"])
        ),
        st.tuples(
            st.just("entity"), st.sampled_from(persons_ix), st.sampled_from(["asserts", "supports"])
        ),
    )
    evidence = st.tuples(st.sampled_from(["p1", "p2", "p3"]), st.sampled_from(SOURCES))

    def statement(subject, type_, obj=None, value=None):
        return {
            "subject": subject,
            "type": type_,
            "object": obj,
            "value": value,
            "attributions": draw(st.lists(attribution, min_size=1, max_size=3, unique=True)),
            "evidence": draw(st.lists(evidence, max_size=2, unique=True)),
        }

    statements = []
    for _ in range(draw(st.integers(0, 12))):
        kind = draw(st.sampled_from(["rel", "holds", "description"]))
        subject = draw(st.sampled_from(persons_ix))
        if kind == "rel":
            obj = draw(st.sampled_from([i for i in persons_ix if i != subject]))
            statements.append(statement(subject, draw(st.sampled_from(REL_TYPES)), obj))
        elif kind == "holds" and positions_ix:
            statements.append(statement(subject, "holds", draw(st.sampled_from(positions_ix))))
        else:
            statements.append(
                statement(subject, "description", value=draw(st.sampled_from(["один", "два"])))
            )
    # повторы: то же у K и у R (совпадут после слияния), иногда с той же атрибуцией
    for _ in range(draw(st.integers(0, 3))):
        type_ = draw(st.sampled_from(REL_TYPES))
        other = draw(st.sampled_from(persons_ix[2:]))
        first = statement(0, type_, other)
        second = statement(1, type_, other)
        if draw(st.booleans()):
            second["attributions"] = list(first["attributions"])  # точный повтор
        statements += [first, second]
    # петли R → K
    for type_ in draw(st.lists(st.sampled_from(REL_TYPES), max_size=2, unique=True)):
        statements.append(statement(1, type_, 0))
    mentions = draw(st.lists(st.sampled_from([0, 1]), max_size=4))
    portraits = draw(
        st.lists(
            st.tuples(st.sampled_from([0, 1]), st.sampled_from(["aaaa", "bbbb", "cccc"])),
            max_size=4,
            unique=True,  # признак изображения уникален в пределах сущности
        )
    )
    return {
        "entities": entities,
        "qid_side": qid_side,
        "statements": statements,
        "mentions": mentions,
        "portraits": portraits,
    }


NAME_POOL = (
    "Berkeley",
    "Беркли",
    "Локк",
    "Джон Локк",
    "Бэкон",
    "Фрэнсис Бэкон",
    "Платон",
)


@st.composite
def ontology_names(draw) -> list[dict[str, Any]]:
    """Сущности разных типов с названиями из малого пула (много совпадений по форме поиска)."""
    out = []
    for _ in range(draw(st.integers(2, 10))):
        type_ = draw(st.sampled_from(["person", "person", "work", "concept"]))
        primary = draw(st.sampled_from(NAME_POOL))
        if type_ != "person" and draw(st.booleans()):
            primary = primary.lower()  # регистр; строчное имя персоны отклонит правило названий
        variants = draw(st.lists(st.sampled_from(NAME_POOL), max_size=2, unique=True))
        variants = [v for v in variants if search_form(v) != search_form(primary)]
        out.append({"type": type_, "primary": primary, "variants": variants})
    return out


def expected_candidates(entities: list[dict[str, Any]]) -> set[frozenset[int]]:
    """Пары одного типа: основное одной совпало (по форме поиска) с любым названием другой."""
    out = set()
    for i, a in enumerate(entities):
        for j, b in enumerate(entities):
            if i == j or a["type"] != b["type"]:
                continue
            names_b = {search_form(x) for x in [b["primary"], *b["variants"]]}
            if search_form(a["primary"]) in names_b:
                out.add(frozenset({i, j}))
    return out


# --- время Wikidata и манифест QID (add-wikidata-life-dates) -------------------------------
# Оракул — таблица точностей спецификации ``entity-dating`` «Даты жизни из Wikidata»;
# модули ``wikidata`` и ``dates`` не импортируются.

WD_ROLES = {  # таблица соответствия ролей P106 (данные реестра, не код разбора)
    "Q4964182": "philosopher",
    "Q170790": "scientist",
    "Q36180": "writer",
    "Q1234713": "theologian",
}
WD_NOT_ROLES = ("Q193391", "Q40348", "Q1622272")  # дипломат, юрист, преподаватель — вне таблицы


def wd_astro(year: int, bce: bool) -> int:
    return 1 - year if bce else year


def wd_bounds(sign: str, year: int, precision: int) -> tuple[int, int, str] | None:
    """Границы и ``precision`` по таблице точностей; ``None`` — пропуск ``bad_value``."""
    bce = sign == "-"
    if year == 0 or precision < 6 or precision > 11:
        return None
    if precision >= 9:
        y = wd_astro(year, bce)
        return y, y, "year"
    if precision == 8:
        a, b = wd_astro(year, bce), wd_astro(year + 9, bce)
        return min(a, b), max(a, b), "decade"
    unit = 100 if precision == 7 else 1000
    n = -(-year // unit)
    a, b = wd_astro((n - 1) * unit + 1, bce), wd_astro(n * unit, bce)
    return min(a, b), max(a, b), "century" if precision == 7 else "approx"


def wd_value(sign: str, year: int, month: int = 0, day: int = 0) -> str:
    return f"{sign}{year:04d}-{month:02d}-{day:02d}T00:00:00Z"


@st.composite
def wd_times(draw) -> tuple[tuple[str, int], tuple[int, int, str] | None]:
    """(значение и точность Wikidata, ожидаемые границы и ``precision`` или ``None``)."""
    kind = draw(st.sampled_from(["ok", "ok", "ok", "ok", "zero", "low", "garbage"]))
    sign = draw(st.sampled_from("+-"))
    year = draw(st.integers(1, 3000))
    precision = draw(st.integers(6, 11))
    if kind == "zero":
        return (wd_value(sign, 0), draw(st.integers(6, 11))), None
    if kind == "low":
        return (wd_value(sign, year), draw(st.integers(0, 5))), None
    if kind == "garbage":
        value = draw(
            st.sampled_from(
                [f"{year:04d}-00-00", f"{sign}{year:04d}", f"{sign}17x4-00-00T00:00:00Z", "", "Q5"]
            )
        )
        return (value, precision), None
    month = draw(st.integers(1, 12)) if precision >= 10 else 0
    day = draw(st.integers(1, 28)) if precision >= 11 else 0
    return (wd_value(sign, year, month, day), precision), wd_bounds(sign, year, precision)


def wd_width(bounds: tuple[int, int, str]) -> int:
    return bounds[1] - bounds[0]


def expected_lifespan(birth, death) -> dict[str, Any]:
    """Годы жизни: начало — из рождения, конец — из смерти; ``precision`` — ``year`` при
    обеих «год», иначе точность той, у которой неопределённость шире."""
    wider = max((birth, death), key=wd_width)[2]
    precision = "year" if birth[2] == death[2] == "year" else wider
    return {
        "earliest_start": birth[0],
        "latest_start": birth[1],
        "earliest_end": death[0],
        "latest_end": death[1],
        "precision": precision,
    }


RANKS = ("normal", "preferred", "deprecated")


@st.composite
def wd_claim_values(draw, present: bool) -> tuple[list[tuple[str, int, str]], Any]:
    """Значения одного свойства с рангами и выбранное по правилу: предпочтённое, иначе
    первое обычное, устаревшее — никогда. Ожидание: ``None`` — свойства нет, иначе
    (границы или ``None`` для ``bad_value``)."""
    if not present:
        if draw(st.booleans()):  # только устаревшие — как будто свойства нет
            (value, precision), _ = draw(wd_times())
            return [(value, precision, "deprecated")], None
        return [], None
    values = []
    for _ in range(draw(st.integers(1, 3))):
        (value, precision), bounds = draw(wd_times())
        values.append(((value, precision, draw(st.sampled_from(RANKS))), bounds))
    if not any(v[0][2] != "deprecated" for v in values):
        (value, precision, _), bounds = values[0]
        values[0] = ((value, precision, "normal"), bounds)
    preferred = [b for v, b in values if v[2] == "preferred"]
    normal = [b for v, b in values if v[2] == "normal"]
    chosen = (preferred or normal)[0]
    return [v for v, _ in values], ("value", chosen)


@st.composite
def wd_person_records(draw, index: int) -> dict[str, Any]:
    """Персона или произведение с QID и записью Wikidata; ожидание датировки и ролей."""
    qid = f"Q{700000 + index}"
    kind = draw(st.sampled_from(["person", "person", "person", "work"]))
    props = ("P569", "P570") if kind == "person" else ("P577",)
    times, chosen = {}, {}
    for prop in props:
        values, pick = draw(wd_claim_values(draw(st.booleans()) or draw(st.booleans())))
        if values:
            times[prop] = values
        chosen[prop] = pick
    occupations = (
        draw(st.lists(st.sampled_from([*WD_ROLES, *WD_NOT_ROLES]), max_size=3))
        if kind == "person"
        else []
    )
    existing = draw(st.sampled_from([None, None, "1600–1650", "1724–1804"]))
    return {
        "qid": qid,
        "type": kind,
        "name": f"Лицо {index}" if kind == "person" else f"Труд {index}",
        "times": times,
        "chosen": chosen,
        "occupations": occupations,
        "roles": {WD_ROLES[q] for q in occupations if q in WD_ROLES},
        "existing": existing,
    }


def expected_dating(case: dict[str, Any]) -> tuple[str, Any]:
    """Ожидаемый исход датировки записи: ("write", границы) или ("skip", {причины})."""
    if case["type"] == "work":
        pick = case["chosen"]["P577"]
        if pick is None:
            return "skip", {("P577", "no_dates")}
        bounds = pick[1]
        if bounds is None:
            return "skip", {("P577", "bad_value")}
        return "write", {
            "earliest_start": bounds[0],
            "latest_start": bounds[1],
            "earliest_end": bounds[0],
            "latest_end": bounds[1],
            "precision": bounds[2],
        }
    birth, death = case["chosen"]["P569"], case["chosen"]["P570"]
    if birth is None and death is None:
        return "skip", {("P569", "no_dates"), ("P570", "no_dates"), ("item", "no_dates")}
    bad = {p for p, pick in case["chosen"].items() if pick is not None and pick[1] is None}
    if birth is None or death is None:
        missing = "P569" if birth is None else "P570"
        return "skip", {(missing, "partial"), *((p, "bad_value") for p in bad)}
    if bad:
        return "skip", {(p, "bad_value") for p in bad}
    return "write", expected_lifespan(birth[1], death[1])


QID_POOL = ("Q11", "Q12", "Q13", "Q14")
DECISIONS = ("pending", "accepted", "auto", "rejected")


@st.composite
def manifests(draw) -> dict[str, Any]:
    """Персоны (часть с QID из малого пула) и записи манифеста в порядке обхода.

    Ожидание — обход по правилу 1–4 «Подтверждение QID»: какие QID записаны, у каких
    записей ``qid_conflict``/``qid_taken`` (два подтверждения одного QID — первое)."""
    n = draw(st.integers(2, 5))
    pool = list(QID_POOL)
    held = {}
    for i in range(n):
        if draw(st.integers(0, 2)) == 0:
            free = [q for q in pool if q not in held.values()]
            if free:
                held[i] = draw(st.sampled_from(free))
    order = draw(st.permutations(range(n)))
    entries = []
    for i in order[: draw(st.integers(1, n))]:
        decision = draw(st.sampled_from(DECISIONS))
        qid = draw(st.sampled_from([None, *pool]))
        if decision in ("accepted", "auto") and qid is None:
            qid = draw(st.sampled_from(pool))
        entries.append({"index": i, "wikidata": qid, "decision": decision})
    # оракул правила
    owner = {q: i for i, q in held.items()}
    own = dict(held)
    written, skipped = {}, []
    for e in entries:
        if e["decision"] not in ("accepted", "auto"):
            continue
        i, q = e["index"], e["wikidata"]
        if i in own and own[i] != q:
            skipped.append((i, "qid_conflict"))
            continue
        if i in own:
            continue
        if q in owner and owner[q] != i:
            skipped.append((i, "qid_taken"))
            continue
        owner[q], own[i] = i, q
        written[i] = q
    return {"n": n, "held": held, "entries": entries, "written": written, "skipped": skipped}


# --- коды причин knowledge.extraction.dropped (О17, О18) -----------------------------------

DATING_CODES = {
    f"dating:{c}"
    for c in (
        "paragraph",
        "quote",
        "unparsed",
        "not_in_quote",
        "era",
        "single_year",
        "type",
        "unresolved",
    )
}
ENTITY_CODES = {"entity:type", "entity:no_type", "entity:ambiguous"} | {
    f"entity:{r}" for r in ("empty", "number", "sentence", "not_a_name", "stopword")
}
DROPPED_CODES = DATING_CODES | ENTITY_CODES


def assert_dropped_codes(events) -> None:
    """Каждая причина ``knowledge.extraction.dropped`` — код из перечня спецификаций, без
    названий и текста (``entity-naming`` «Отказ», ``ontology-extraction``, ``entity-dating``)."""
    for e in events.of("knowledge.extraction.dropped"):
        assert e["reason"] in DROPPED_CODES, e.fields
