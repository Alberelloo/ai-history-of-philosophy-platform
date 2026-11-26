"""Названия сущностей: письменность и язык, проверка валидности (спецификация entity-naming).

Одна реализация правил для всех путей записи названия: извлечение, ядро, импорт Wikidata,
источник библиотеки, обогащения, миграция. Код решает сам; модель только подсказывает
написания. Стоп-список, пределы, частицы и шаблоны — данные ``naming_rules.yaml``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from philograph.platform import events

events.define(
    "knowledge.entity.rejected",
    "warning",
    "Название сущности не прошло проверку",
    required=("type", "label", "reason"),
)

RULES_PATH = Path(__file__).with_name("naming_rules.yaml")

REASONS = ("empty", "number", "sentence", "not_a_name", "stopword")
LABEL_LIMIT = 80

_EDGE = ".,;:!?()[]«»\"'„“”"
_ROMAN_WORD = re.compile(r"^[IVXLCDM]+$")
_APOSTROPHES = ("-", "'", "’")

# Письменность языка: язык, переданный вызывающим, сохраняется только при совпадении.
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


class RulesError(ValueError):
    """Данные правил названий не той формы — сервис не запускается."""


class InvalidName(Exception):
    def __init__(self, type_: str, label: str, reason: str) -> None:
        super().__init__(f"название «{event_label(label)}» ({type_}) отклонено: {reason}")
        self.type_ = type_
        self.label = label
        self.reason = reason


@dataclass(frozen=True)
class Limits:
    max_words: int
    max_chars: int


@dataclass(frozen=True)
class Rules:
    exempt: frozenset[str]
    limits: dict[str, Limits]
    person_types: frozenset[str]
    particles: frozenset[str]
    patterns: tuple[re.Pattern[str], ...]
    conjunctions: frozenset[str]
    stopwords: frozenset[str]

    def limits_for(self, type_: str) -> Limits:
        return self.limits.get(type_, self.limits["default"])


def _positive(value: Any, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RulesError(f"{where}: нужно положительное целое, а не {value!r}")
    return value


def _strings(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise RulesError(f"{where}: нужен список непустых строк")
    return value


def parse_rules(data: Any) -> Rules:
    """Проверка формы данных правил: пределы — положительные целые, шаблоны компилируются."""
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RulesError("правила названий: нужен словарь с version: 1")
    limits_raw = data.get("limits")
    if not isinstance(limits_raw, dict) or "default" not in limits_raw:
        raise RulesError("limits: нужен словарь с ключом default")
    limits = {}
    for type_, spec in limits_raw.items():
        if not isinstance(spec, dict):
            raise RulesError(f"limits.{type_}: нужен словарь")
        limits[type_] = Limits(
            _positive(spec.get("max_words"), f"limits.{type_}.max_words"),
            _positive(spec.get("max_chars"), f"limits.{type_}.max_chars"),
        )
    person = data.get("person")
    if not isinstance(person, dict):
        raise RulesError("person: нужен словарь")
    patterns = []
    for raw in _strings(person.get("patterns"), "person.patterns"):
        try:
            patterns.append(re.compile(raw, re.IGNORECASE))
        except re.error as exc:
            raise RulesError(f"person.patterns: {raw!r} не компилируется: {exc}") from exc
    return Rules(
        exempt=frozenset(_strings(data.get("exempt") or [], "exempt")),
        limits=limits,
        person_types=frozenset(_strings(person.get("types"), "person.types")),
        particles=frozenset(
            p.lower() for p in _strings(person.get("particles"), "person.particles")
        ),
        patterns=tuple(patterns),
        conjunctions=frozenset(
            c.lower() for c in _strings(person.get("conjunctions"), "person.conjunctions")
        ),
        stopwords=frozenset(normalize(s) for s in _strings(data.get("stopwords"), "stopwords")),
    )


@cache
def load_rules(path: Path = RULES_PATH) -> Rules:
    """Правила из данных, кэш на процесс."""
    with path.open(encoding="utf-8") as fh:
        return parse_rules(yaml.safe_load(fh))


# --- нормализация и письменность ---


def clean(text: str) -> str:
    """*Название* по определению ``entity-naming``: ``strip`` и NFC. Так оно хранится и
    проверяется (О22)."""
    return unicodedata.normalize("NFC", text.strip())


def normalize(name: str) -> str:
    """Правило поиска сущностей: NFC, нижний регистр, «ё» → «е», всё, кроме букв, цифр и
    пробелов, — пробел; пробелы схлопываются, края обрезаются."""
    name = unicodedata.normalize("NFC", name).lower().replace("ё", "е")
    name = re.sub(r"[^\w\s]|_", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _words(text: str) -> list[str]:
    return [w.strip(_EDGE) for w in text.split()]


def _letter_script(ch: str) -> str:
    code = ord(ch)
    if 0x0400 <= code <= 0x052F:
        return "cyrillic"
    if 0x0370 <= code <= 0x03FF or 0x1F00 <= code <= 0x1FFF:
        return "greek"
    if unicodedata.name(ch, "").startswith("LATIN"):
        return "latin"
    return "other"


def _script_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for word in _words(text):
        if _ROMAN_WORD.match(word):
            continue
        for ch in word:
            if unicodedata.category(ch).startswith("L"):
                script = _letter_script(ch)
                counts[script] = counts.get(script, 0) + 1
    return counts


def script_of(text: str) -> str | None:
    """Письменность, букв которой строго больше всего; при равенстве или без букв — ``None``."""
    counts = _script_counts(text)
    if not counts:
        return None
    top = max(counts.values())
    leaders = [s for s, n in counts.items() if n == top]
    return leaders[0] if len(leaders) == 1 else None


def lang_for(text: str, given: str | None = None) -> str:
    """Язык названия: переданный — если его письменность совпадает с письменностью текста,
    иначе язык по письменности (кириллица — ru, латиница — en, греческая — el, иначе und)."""
    script = script_of(text)
    if given is not None and script is not None and LANG_SCRIPT.get(given) == script:
        return given
    return SCRIPT_LANG.get(script or "", "und")


def is_russian(text: str) -> bool:
    """Есть кириллическая буква и нет латинских (слова из римских цифр не считаются)."""
    counts = _script_counts(text)
    return counts.get("cyrillic", 0) > 0 and counts.get("latin", 0) == 0


# --- валидность ---


def _first_letter(text: str) -> str | None:
    return next((ch for ch in text if unicodedata.category(ch).startswith("L")), None)


def _starts_with_particle(word: str, particles: frozenset[str]) -> bool:
    lowered = word.lower()
    if lowered in particles:
        return True
    return any(
        lowered[: len(p)] == p and lowered[len(p) : len(p) + 1] in _APOSTROPHES for p in particles
    )


def _not_a_name(label: str, rules: Rules) -> bool:
    words = label.split()
    first = _first_letter(label)
    if (
        first is not None
        and first.islower()
        and not _starts_with_particle(words[0].lstrip(_EDGE), rules.particles)
    ):
        return True
    normalized = normalize(label)
    if any(p.search(normalized) for p in rules.patterns):
        return True
    stripped = _words(label)
    for i in range(1, len(stripped) - 1):
        if stripped[i].lower() in rules.conjunctions:
            left, right = _first_letter(stripped[i - 1]), _first_letter(stripped[i + 1])
            if left and right and left.isupper() and right.isupper():
                return True
    return False


def check_name(type_: str, label: str, rules: Rules | None = None) -> str | None:
    """Причина отказа (первая по порядку правил) или ``None``, если название годится."""
    rules = rules or load_rules()
    if type_ in rules.exempt:
        return None
    label = clean(label)
    has_letter = any(unicodedata.category(ch).startswith("L") for ch in label)
    has_digit = any(ch.isdigit() for ch in label)
    if not has_letter and not has_digit:
        return "empty"
    if not has_letter:
        return "number"
    limits = rules.limits_for(type_)
    if len(label.split()) > limits.max_words or len(label) > limits.max_chars:
        return "sentence"
    if type_ in rules.person_types and _not_a_name(label, rules):
        return "not_a_name"
    if normalize(label) in rules.stopwords:
        return "stopword"
    return None


def event_label(label: str) -> str:
    """Название для журнала: не длиннее 80 знаков, длиннее — 79 знаков и «…»."""
    return label if len(label) <= LABEL_LIMIT else label[: LABEL_LIMIT - 1] + "…"


def reject(type_: str, label: str, reason: str) -> InvalidName:
    """Событие отказа ровно с полями type, label, reason; возвращает исключение для вызова.
    ``label`` события — название после ``strip`` и NFC (как его проверяет ``check_name``),
    обрезка — по нему же."""
    label = clean(label)
    events.emit("knowledge.entity.rejected", type=type_, label=event_label(label), reason=reason)
    return InvalidName(type_, label, reason)


def invalid_primary(type_: str, names: list[tuple[str, str, str]]) -> tuple[str, str] | None:
    """Первое основное название, не прошедшее проверку, и причина — до записи, без события.
    Нужна путям, которые создают несколько сущностей сразу и не должны писать половину."""
    for _, text, kind in names:
        if kind == "primary":
            reason = check_name(type_, text)
            if reason is not None:
                return text, reason
    return None


def names_for(type_: str, item: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Названия новой сущности из элемента ``entities`` ответа модели.

    Основное — русское написание ``ru``, если оно русское и прошло проверку, иначе ``name``.
    Остальные написания — варианты; не прошедшее проверку не записывается (событие отказа).
    Основное здесь не проверяется: это делает ``Entities.create``."""
    spellings: list[tuple[str, str | None]] = []
    if item.get("ru"):
        spellings.append((item["ru"], "ru"))
    spellings.append((item["name"], None))
    if item.get("en"):
        spellings.append((item["en"], "en"))
    original = item.get("original") or {}
    if original.get("text"):
        spellings.append((original["text"], original.get("lang")))
    ru = item.get("ru")
    if ru and is_russian(ru) and check_name(type_, ru) is None:
        names = [(lang_for(ru, "ru"), ru, "primary")]
    else:
        names = [(lang_for(item["name"]), item["name"], "primary")]
    primary = names[0][1]
    seen = {normalize(primary)}
    for text, given in spellings:
        key = normalize(text)
        if key in seen:
            continue
        seen.add(key)
        reason = check_name(type_, text)
        if reason is not None:
            reject(type_, text, reason)
            continue
        names.append((lang_for(text, given), text, "variant"))
    return names
