"""Доступ к Wikidata: загрузка записи, разбор значений и рангов, время → нечёткая дата.

Общий модуль команд оператора (``epoch_dates``, контекст эпох, гео-таймлайн): своего httpx
и разбора времени у них нет. Правила — требование «Доступ к Wikidata» возможности ``epochs``:

- сеть — только ``http_fetch``: один домен (``www.wikidata.org``), адрес строится кодом из
  идентификатора, проверенного ``check_qid`` (``^Q\\d+$``), иначе запрос не делается;
  ``User-Agent`` проекта без сведений об операторе, таймаут, на 429/503 — ожидание по
  ``Retry-After`` (не дольше ``max_wait``) и не больше ``retries`` повторов. Ожидание —
  внедряемой функцией ``wait``: в тестах реального ожидания нет;
- команды получают загрузку как ``Fetch`` (адрес → JSON): ``partial(http_fetch, wait=…)``
  в бою, словарь фикстур в тестах;
- время Wikidata → ``FuzzyDate``: знак — эра (``-0800`` — 800 год до н. э., астрономический
  −799); точность 9 и выше — год, 8 — десятилетие, 7 — век ⌈|год| / 100⌉, 6 — тысячелетие
  (``approx``); ниже 6, год ``0000`` и запись не по формату — ``None``;
- из нескольких значений свойства — «предпочтённое», иначе первое «обычное»; «устаревшее»
  не берётся никогда. Ответ — данные: из него берутся только запрошенные свойства.

Дата, записанная в утверждение (значение ``dating`` или уточнитель ``time``), — ровно
``FuzzyDate.to_json()`` с ``original`` из ``format_original``: одинаковые данные Wikidata
дают одинаковый ключ утверждения, повторный запуск сливается с прежним.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from philograph.knowledge.dates import FuzzyDate, join_original

QID = re.compile(r"^Q\d+$")
HOST = "www.wikidata.org"
USER_AGENT = "PhiloGraph/1.0 (+https://github.com/Alberelloo/ai-history-of-philosophy-platform)"
ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
SEARCH_URL = (
    "https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&type=item"
    "&limit=10&language={lang}&search={label}"
)
PAGE_URL = "https://www.wikidata.org/wiki/{qid}"
RETRY_STATUSES = (429, 503)
MAX_REDIRECTS = 3
DEFAULT_RETRY_AFTER = 1.0  # секунд, если ``Retry-After`` нет или он не число
LANG = re.compile(r"^[a-z]{2,3}(-[a-z]+)?$")

Fetch = Callable[[str], dict[str, Any]]


class WikidataError(Exception):
    """Неверный идентификатор, сбой загрузки или ответ не по форме."""


def check_qid(qid: str) -> str:
    """Идентификатор записи по шаблону ``^Q\\d+$``; иначе ``WikidataError``. Запросов нет."""
    if not isinstance(qid, str) or not QID.fullmatch(qid):
        raise WikidataError(f"неверный идентификатор Wikidata: {qid!r}")
    return qid


def page_url(qid: str) -> str:
    """Ссылка на страницу записи — для «Wikidata ↗» и ``place`` атрибуции."""
    return PAGE_URL.format(qid=check_qid(qid))


def _retry_after(response: httpx.Response, max_wait: float) -> float:
    raw = response.headers.get("Retry-After", "")
    try:
        delay = float(raw)
    except ValueError:
        delay = DEFAULT_RETRY_AFTER  # дата HTTP или мусор: ждём по умолчанию
    if not math.isfinite(delay) or delay < 0:
        delay = DEFAULT_RETRY_AFTER
    return min(delay, max_wait)


def _check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != HOST:
        raise WikidataError("адрес вне Wikidata")


def http_fetch(
    url: str,
    *,
    wait: Callable[[float], None] = time.sleep,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 10.0,
    retries: int = 3,
    max_wait: float = 30.0,
) -> dict[str, Any]:
    """Единственная функция модуля, которая ходит в сеть: GET ``url`` → JSON.

    Адрес — только ``https://www.wikidata.org/…`` (его строит код). На 429 и 503 ждёт
    ``Retry-After`` (не больше ``max_wait``) и повторяет не больше ``retries`` раз; прочие
    сбои (статус, транспорт, не JSON) — ``WikidataError``."""
    _check_url(url)

    def before_send(request: httpx.Request) -> None:
        # Каждый запрос, в том числе переход по перенаправлению, — только на Wikidata:
        # проверка до отправки.
        _check_url(str(request.url))

    with httpx.Client(
        transport=transport,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        event_hooks={"request": [before_send]},
    ) as client:
        attempt = 0
        while True:
            try:
                response = client.get(url)
            except httpx.HTTPError as exc:
                raise WikidataError(f"сбой загрузки: {type(exc).__name__}") from exc
            if response.status_code in RETRY_STATUSES:
                if attempt >= retries:
                    raise WikidataError(
                        f"сбой загрузки: {response.status_code} после {retries} повторов"
                    )
                wait(_retry_after(response, max_wait))
                attempt += 1
                continue
            if response.status_code != 200:
                raise WikidataError(f"сбой загрузки: {response.status_code}")
            try:
                data = response.json()
            except ValueError as exc:
                raise WikidataError("ответ не JSON") from exc
            if not isinstance(data, dict):
                raise WikidataError("ответ не по форме")
            return data


# --- запись ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Claim:
    value: Any  # {"time","precision"} | {"id"} | {"latitude","longitude"} | str | None
    rank: str  # preferred | normal | deprecated
    qualifiers: dict[str, list[Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class WikidataRecord:
    qid: str
    labels: dict[str, str]
    descriptions: dict[str, str]
    claims: dict[str, list[Claim]]

    def best(self, prop: str) -> Claim | None:
        """Значение свойства: «предпочтённое», иначе первое «обычное»; «устаревшее» — никогда."""
        claims = self.claims.get(prop, [])
        for rank in ("preferred", "normal"):
            for claim in claims:
                if claim.rank == rank:
                    return claim
        return None

    def items(self, prop: str) -> list[str]:
        """QID-значения свойства (кроме «устаревших»), только по шаблону ``^Q\\d+$``."""
        found = []
        for claim in self.claims.get(prop, []):
            if claim.rank == "deprecated" or not isinstance(claim.value, dict):
                continue
            qid = claim.value.get("id")
            if isinstance(qid, str) and QID.fullmatch(qid) and qid not in found:
                found.append(qid)
        return found


def _snak_value(snak: Any) -> Any:
    """Значение снэка в форме ``Claim.value``; «нет значения» и «неизвестно» — ``None``."""
    if not isinstance(snak, dict) or snak.get("snaktype") != "value":
        return None
    datavalue = snak.get("datavalue")
    if not isinstance(datavalue, dict):
        return None
    kind, value = datavalue.get("type"), datavalue.get("value")
    if kind == "time" and isinstance(value, dict):
        return {"time": value.get("time"), "precision": value.get("precision")}
    if kind == "wikibase-entityid" and isinstance(value, dict):
        return {"id": value.get("id")}
    if kind == "globecoordinate" and isinstance(value, dict):
        return {"latitude": value.get("latitude"), "longitude": value.get("longitude")}
    if kind == "monolingualtext" and isinstance(value, dict):
        return value.get("text")
    if kind == "string" and isinstance(value, str):
        return value
    return None


def _texts(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        lang: item["value"]
        for lang, item in raw.items()
        if isinstance(item, dict) and isinstance(item.get("value"), str)
    }


def parse_entity(qid: str, data: dict[str, Any]) -> WikidataRecord:
    """Запись из ответа ``Special:EntityData``; перенаправленная запись — единственная."""
    entities = data.get("entities")
    if not isinstance(entities, dict) or not entities:
        raise WikidataError("ответ не по форме")
    raw = entities.get(qid)
    if raw is None and len(entities) == 1:
        raw = next(iter(entities.values()))  # запись перенаправлена на другой QID
    if not isinstance(raw, dict):
        raise WikidataError("ответ не по форме")
    claims: dict[str, list[Claim]] = {}
    for prop, items in (raw.get("claims") or {}).items():
        if not isinstance(items, list):
            continue
        parsed = []
        for item in items:
            if not isinstance(item, dict):
                continue
            rank = item.get("rank") if item.get("rank") in ("preferred", "deprecated") else "normal"
            qualifiers = {
                q: [_snak_value(snak) for snak in snaks]
                for q, snaks in (item.get("qualifiers") or {}).items()
                if isinstance(snaks, list)
            }
            parsed.append(Claim(_snak_value(item.get("mainsnak")), rank, qualifiers))
        claims[prop] = parsed
    record_id = raw.get("id") if isinstance(raw.get("id"), str) else qid
    return WikidataRecord(
        qid=check_qid(record_id),
        labels=_texts(raw.get("labels")),
        descriptions=_texts(raw.get("descriptions")),
        claims=claims,
    )


def fetch_entity(qid: str, fetch: Fetch) -> WikidataRecord:
    """Запись Wikidata. Неверный идентификатор — ``WikidataError`` без вызова ``fetch``."""
    url = ENTITY_URL.format(qid=check_qid(qid))
    return parse_entity(qid, fetch(url))


def search(label: str, lang: str, fetch: Fetch) -> list[dict[str, Any]]:
    """Кандидаты по названию: ``[{id, label, description}]``, только QID по шаблону."""
    if not LANG.fullmatch(lang):
        raise WikidataError(f"неверный язык: {lang!r}")
    url = SEARCH_URL.format(lang=lang, label=quote(label, safe=""))
    data = fetch(url)
    found = []
    for item in data.get("search") or []:
        if not isinstance(item, dict) or not QID.fullmatch(str(item.get("id", ""))):
            continue
        found.append(
            {
                "id": item["id"],
                "label": item.get("label") if isinstance(item.get("label"), str) else None,
                "description": item.get("description")
                if isinstance(item.get("description"), str)
                else None,
            }
        )
    return found


# --- время ----------------------------------------------------------------------------

TIME = re.compile(r"^([+-])(\d+)-(\d{2})-(\d{2})T\d{2}:\d{2}:\d{2}Z$")


def _astro(year: int, bce: bool) -> int:
    return 1 - year if bce else year


def _bounds(year: int, bce: bool, precision: int) -> tuple[int, int, str] | None:
    """Самый ранний и самый поздний год (астрономический счёт) и точность ``FuzzyDate``."""
    if precision >= 9:
        y = _astro(year, bce)
        return y, y, "year"
    if precision == 8:  # десятилетие: «1680» — 1680–1689
        a, b = _astro(year, bce), _astro(year + 9, bce)
        return min(a, b), max(a, b), "decade"
    if precision == 7:  # век: номер — ⌈|год| / 100⌉, «+1800» и «+1701» — XVIII век
        n = math.ceil(year / 100)
        a, b = _astro((n - 1) * 100 + 1, bce), _astro(n * 100, bce)
        return min(a, b), max(a, b), "century"
    if precision == 6:  # тысячелетие
        m = math.ceil(year / 1000)
        a, b = _astro((m - 1) * 1000 + 1, bce), _astro(m * 1000, bce)
        return min(a, b), max(a, b), "approx"
    return None


def wikidata_time(value: str, precision: int) -> FuzzyDate | None:
    """Значение времени Wikidata → нечёткая дата; без даты — ``None`` (см. модуль)."""
    if not isinstance(value, str) or isinstance(precision, bool) or not isinstance(precision, int):
        return None
    match = TIME.fullmatch(value)
    if not match:
        return None
    year = int(match.group(2))
    if year == 0:
        return None
    bounds = _bounds(year, match.group(1) == "-", precision)
    if bounds is None:
        return None
    lo, hi, kind = bounds
    draft = FuzzyDate(lo, hi, lo, hi, kind, "")
    return FuzzyDate(lo, hi, lo, hi, kind, _render(draft))


def claim_date(claim: Claim | None) -> FuzzyDate | None:
    """Дата значения свойства (``Claim.value`` вида ``{"time","precision"}``) или ``None``."""
    if claim is None or not isinstance(claim.value, dict):
        return None
    return wikidata_time(claim.value.get("time"), claim.value.get("precision"))


_ROMAN = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)


def _roman(n: int) -> str:
    out = []
    for value, digits in _ROMAN:
        while n >= value:
            out.append(digits)
            n -= value
    return "".join(out)


BCE = " до н. э."


def _render(d: FuzzyDate) -> str:
    """Запись одной даты Wikidata: «1685», «1680-е», «XVIII в.», «II тыс.», «… до н. э.»."""
    lo, hi = d.earliest_start, d.latest_start
    bce = hi <= 0
    if d.precision == "year":
        return f"{1 - lo}{BCE}" if bce else str(lo)
    if d.precision == "decade":
        return f"{1 - hi}-е{BCE}" if bce else f"{lo}-е"
    if d.precision == "century":
        return f"{_roman((1 - lo) // 100)} в.{BCE}" if bce else f"{_roman(hi // 100)} в."
    return f"{_roman((1 - lo) // 1000)} тыс.{BCE}" if bce else f"{_roman(hi // 1000)} тыс."


def format_original(start: FuzzyDate, end: FuzzyDate | None = None) -> str:
    """Исходная запись даты или интервала из дат Wikidata: «1685–1815»,
    «VIII в. до н. э. – 476». Детерминирована: зависит только от границ и точности."""
    first = _render(start)
    return first if end is None else join_original(first, _render(end))
