"""Внешний извлекатель: ответы на фрагменты даёт модель вне шлюза (Claude).

Код выдаёт задание — фрагменты версии тем же делением, что у извлечения через шлюз, с
инструкцией и блоками реестра; извлекатель отвечает по схеме; код проверяет и записывает
ответы тем же путём, что ответы шлюза (``Filling.apply_reply``). Запуск записывается с
моделью, временем, токенами и стоимостью по тарифу.

Команды::

    python -m philograph.knowledge.external_extraction export --version V [--out DIR]
    python -m philograph.knowledge.external_extraction ingest --version V --replies FILE \\
        --model claude-opus-5-5 --input-tokens N --output-tokens N --duration S [--replace]
    python -m philograph.knowledge.external_extraction report --since 2026-11-26 \\
        --out docs/audit/extraction-run-2026-11-26.md

Окружение: ``PHILOGRAPH_DATABASE_URL`` (база знаний), ``PHILOGRAPH_LIBRARY_URL`` (сервис
библиотеки; абзацы — только через его интерфейс). Коды выхода: 0 — готово, 2 — отказ
команды (ничего не записано), 3 — источник без разрешения на внешнюю обработку.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import and_, select
from sqlalchemy.engine import Engine

from philograph.knowledge import extraction_codes as codes
from philograph.knowledge import schema as t
from philograph.knowledge.entities import Entities
from philograph.knowledge.filling import Filling
from philograph.knowledge.registry import OntologyRegistry
from philograph.knowledge.statements import Statements
from philograph.platform import context, events
from philograph.platform.client import ServiceClient, ServiceUnavailable
from philograph.prompts import PROMPTS

events.define(
    "knowledge.extraction.exported",
    "info",
    "Задание внешнего извлекателя выгружено",
    required=("version_id", "fragments"),
)
events.define(
    "knowledge.extraction.report",
    "info",
    "Отчёт о запусках извлечения записан",
    required=("runs", "out"),
)

TEMPLATE = "ontology.extract"
PRICES = Path(__file__).with_name("extraction_prices.yaml")
EXTERNAL = "external"
# Запуск ``running`` моложе этого считается идущей записью (параллельный ingest): повтор
# отказывает. Старше — брошенный (процесс упал), его откатывает ``--replace``.
STALE_RUNNING_HOURS = 6


class CommandError(Exception):
    """Отказ команды до записи: код выхода 2."""


class Forbidden(Exception):
    """Источник без разрешения на внешнюю обработку: код выхода 3."""


@dataclass(frozen=True)
class Price:
    """USD за 1M токенов."""

    input: float
    output: float
    cache_read: float = 0.0

    def cost(self, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0) -> float:
        total = (
            input_tokens * self.input
            + output_tokens * self.output
            + cache_read_tokens * self.cache_read
        )
        return round(total / 1_000_000, 6)


def load_prices(path: Path = PRICES) -> dict[str, Price]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {model: Price(**spec) for model, spec in data.items()}


def price_for(
    model: str,
    price_in: float | None = None,
    price_out: float | None = None,
    price_cache_read: float | None = None,
    prices: dict[str, Price] | None = None,
) -> Price:
    """Цены из аргументов важнее тарифа; без тарифа и без обеих цен — отказ команды."""
    known = (load_prices() if prices is None else prices).get(model)
    if known is None and (price_in is None or price_out is None):
        raise CommandError(f"нет тарифа модели {model}: передайте --price-in и --price-out")
    base = known or Price(0.0, 0.0)
    return Price(
        base.input if price_in is None else price_in,
        base.output if price_out is None else price_out,
        base.cache_read if price_cache_read is None else price_cache_read,
    )


def _instructions() -> str:
    return next(p.instructions for p in PROMPTS if p.name == TEMPLATE)


def _allowed(filling: Filling, data: dict[str, Any]) -> None:
    if not data["permissions"].get("external_processing"):
        events.emit(
            "knowledge.extraction.skipped",
            source_id=data["source_id"],
            reason="external_processing_forbidden",
        )
        raise Forbidden(data["source_id"])


# --- задание ---


def task(filling: Filling, data: dict[str, Any]) -> list[dict[str, Any]]:
    """Строки задания: заголовок и по строке на фрагмент (номера с 1)."""
    _allowed(filling, data)
    schema = filling.registry_schema()
    fragments = filling.version_fragments(data)
    types = schema["properties"]["statements"]["items"]["properties"]["subject_type"]["enum"]
    lines: list[dict[str, Any]] = [
        {
            "kind": "task",
            "version_id": data["version_id"],
            "source_id": data["source_id"],
            "source_title": data.get("source_title") or data["source_id"],
            "template": TEMPLATE,
            "instructions": _instructions(),
            "relations": schema["x-relations"],
            "entity_types": types,
            "output_schema": schema,
            "fragments": len(fragments),
        }
    ]
    for number, window in enumerate(fragments, start=1):
        prompt = filling.prompt_data(window, schema)
        lines.append(
            {
                "kind": "fragment",
                "fragment": number,
                "paragraph_ids": [p["id"] for p in window],
                "language": prompt["language"],
                "section": prompt["section"],
                "passages": prompt["passages"],
            }
        )
    return lines


def export(filling: Filling, data: dict[str, Any], out_dir: Path) -> Path:
    lines = task(filling, data)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{data['version_id']}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    events.emit(
        "knowledge.extraction.exported", version_id=data["version_id"], fragments=len(lines) - 1
    )
    return path


# --- ответы ---


def read_replies(path: Path) -> dict[str, Any]:
    """Ответы по номеру фрагмента: JSON-объект ``{"n": ответ}`` или JSONL со строками
    ``{"fragment": n, "reply": ответ}``. Номер — строкой, как в файле: проверка — в ``ingest``."""
    text = path.read_text(encoding="utf-8")
    try:
        whole = json.loads(text)
    except ValueError:
        whole = None
    if isinstance(whole, dict) and "fragment" not in whole:
        top = json.loads(text, object_pairs_hook=_unique)
        if isinstance(top, _Repeated):  # только номера фрагментов; внутри ответа — как в JSON
            raise CommandError(f"{path}: фрагмент {top.keys_repeated[0]} указан дважды")
        return _distinct(path, [(str(k), v) for k, v in top.items()])
    pairs: list[tuple[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise CommandError(f"{path}: строка {number} — не JSON") from exc
        if not isinstance(row, dict) or "fragment" not in row or "reply" not in row:
            raise CommandError(f"{path}: строка {number} — нужны поля fragment и reply")
        pairs.append((str(row["fragment"]), row["reply"]))
    return _distinct(path, pairs)


def _number(key: str) -> int | None:
    """Номер фрагмента по ключу файла: только цифры ASCII, пробелы по краям допустимы."""
    key = key.strip()
    return int(key) if re.fullmatch(r"[0-9]+", key) else None


def _distinct(path: Path, pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Повтор проверяется по номеру после приведения («1», «01», « 1» — один фрагмент):
    иначе ``ingest`` молча заменил бы один ответ другим. Ключ не номер — как есть (в
    ``ingest`` он даст ``reply_invalid``)."""
    seen: dict[Any, str] = {}
    replies: dict[str, Any] = {}
    for key, reply in pairs:
        number = _number(key)
        canonical = number if number is not None else key
        if canonical in seen:
            raise CommandError(
                f"{path}: фрагмент {canonical} указан дважды ({seen[canonical]!r} и {key!r})"
            )
        seen[canonical] = key
        replies[key] = reply
    return replies


class _Repeated(dict):
    """Объект JSON с повтором ключа (последний выигрывает, как в обычном JSON); повторы —
    в ``keys_repeated``. Для верхнего уровня файла ответов повтор номера — ошибка файла."""

    keys_repeated: list[str]


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    repeated = []
    for key, value in pairs:
        if key in result:
            repeated.append(key)
        result[key] = value
    if not repeated:
        return result
    marked = _Repeated(result)
    marked.keys_repeated = repeated
    return marked


def _previous(engine: Engine, version_id: str) -> list[dict[str, Any]]:
    """Прежние внешние запуски версии, которые не откатаны: ``run_id``, ``status``,
    ``started_at``."""
    runs = t.filling_runs
    with engine.begin() as conn:
        return list(
            conn.execute(
                select(runs.c.run_id, runs.c.status, runs.c.started_at).where(
                    and_(
                        runs.c.kind == "extraction",
                        runs.c.extractor == EXTERNAL,
                        runs.c.target == version_id,
                        # done, failed и брошенный running: у всех могут быть записанные
                        # утверждения — повтор без отката удвоил бы подтверждения.
                        runs.c.status != "rolled_back",
                    )
                )
            ).mappings()
        )


def _age_hours(started: datetime, now: datetime) -> float:
    if started.tzinfo is None:  # SQLite хранит без пояса: время сервиса — UTC
        started = started.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return (now - started).total_seconds() / 3600


def ingest(
    filling: Filling,
    data: dict[str, Any],
    replies: dict[str, Any],
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    duration_seconds: float,
    cost_usd: float,
    replace: bool = False,
) -> dict[str, Any]:
    """Запуск ``extractor=external``: каждый ответ — через ``Filling.apply_reply``; фрагмент
    без ответа — ``reply_missing``; номер вне фрагментов — ``reply_invalid``. Повтор версии —
    только с ``replace``: прежние внешние запуски версии ``done``, ``failed`` и брошенные
    ``running`` (старше ``STALE_RUNNING_HOURS``) откатываются. Идущая запись (``running``
    моложе порога) — отказ «запись идёт» и с ``replace``.

    Риск ``replace``: откат снимает всё, что записал прежний запуск, в том числе
    подтверждения и атрибуции, добавленные к утверждениям, которые уже были (другой учебник,
    шлюз). Проверенные человеком (``verified``) утверждения остаются вместе со своими
    подтверждениями и атрибуциями (``Statements.rollback_run``); новая запись добавит к ним
    подтверждения ещё раз. Перед ``--replace`` на боевой базе — резервная копия
    (docs/operations/runbook.md, «Извлечение связей»)."""
    _allowed(filling, data)
    version_id = data["version_id"]
    previous = _previous(filling.statements.engine, version_id)
    now = filling.clock.now()
    live = [
        r["run_id"]
        for r in previous
        if r["status"] == "running" and _age_hours(r["started_at"], now) < STALE_RUNNING_HOURS
    ]
    if live:
        raise CommandError(
            f"запись идёт: версия {version_id}, запуск {', '.join(live)} (running); "
            f"повтор — после его завершения или через {STALE_RUNNING_HOURS} ч"
        )
    if previous and not replace:
        ids = ", ".join(r["run_id"] for r in previous)
        raise CommandError(f"версия {version_id} уже записана запуском {ids}: повтор — с --replace")
    for row in previous:
        filling.rollback(row["run_id"])
    run_id = filling.start_run(
        "extraction",
        version_id,
        extractor=EXTERNAL,
        source_id=data["source_id"],
        model=model,
        run_id=f"ext_{uuid.uuid4().hex[:12]}",
    )
    try:
        with context.scope(run_id=run_id):
            source = filling.entities.source_entity(
                data["source_id"], data.get("source_title") or data["source_id"]
            )
            fragments = filling.version_fragments(data)
            schema = filling.registry_schema()
            numbered: dict[int, Any] = {}
            for key, reply in replies.items():
                number = _number(key)
                if number is None or not 1 <= number <= len(fragments):
                    filling.drop(run_id, "ответ на фрагмент вне задания", codes.REPLY_INVALID)
                    continue
                numbered[number] = reply
            for number, window in enumerate(fragments, start=1):
                if number in numbered:
                    filling.apply_reply(window, data, source, run_id, numbered[number], schema)
                else:
                    filling.drop_fragment(run_id, "нет ответа на фрагмент", codes.REPLY_MISSING)
    except BaseException as exc:
        filling.fail_run(run_id, exc)
        raise
    return filling.finish_run(
        run_id,
        fragments=len(fragments),
        duration_seconds=duration_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


# --- отчёт ---


def _day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def report_rows(engine: Engine, since: date, until: date | None = None) -> list[dict[str, Any]]:
    runs = t.filling_runs
    query = select(runs).where(
        and_(
            runs.c.kind == "extraction",
            runs.c.status != "rolled_back",
            runs.c.started_at >= _day(since),
        )
    )
    if until is not None:
        query = query.where(runs.c.started_at < _day(until + timedelta(days=1)))
    with engine.begin() as conn:
        rows = [dict(r) for r in conn.execute(query.order_by(runs.c.started_at)).mappings()]
    return rows


def _rate(created: int, dropped: int) -> str:
    total = created + dropped
    return f"{dropped / total:.0%}" if total else "—"


def _top(reasons: Counter) -> str:
    return ", ".join(f"{code} {n}" for code, n in reasons.most_common(3)) or "—"


def _num(value: Any, digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}" if digits else str(int(value))


def report(engine: Engine, entities: Entities, since: date, until: date | None = None) -> str:
    """Markdown-таблица запусков извлечения за период и строка «Итого»."""
    rows = report_rows(engine, since, until)
    head = (
        "| Источник | Модель | Извлекатель | Статус | Время, с | Фрагменты | Токены вход "
        "| Токены выход | Стоимость, $ | Создано | Отброшено | Доля отбраковки | Топ причин |"
    )
    period = f"{since.isoformat()} — {until.isoformat() if until else 'сейчас'}"
    lines = [
        f"# Запуски извлечения: {period}",
        "",
        head,
        "|" + "---|" * 13,
    ]
    total: Counter = Counter()
    reasons_all: Counter = Counter()
    for r in rows:
        reasons = Counter(r.get("drop_reasons") or {})
        reasons_all.update(reasons)
        for key in ("duration_seconds", "fragments", "input_tokens", "output_tokens", "cost_usd"):
            total[key] += float(r.get(key) or 0)
        total["created"] += r["created"]
        total["dropped"] += r["dropped"]
        lines.append(
            "| "
            + " | ".join(
                [
                    _source(entities, r),
                    r.get("model") or "—",
                    r.get("extractor") or "—",
                    r["status"],
                    _num(r.get("duration_seconds"), 1),
                    _num(r.get("fragments")),
                    _num(r.get("input_tokens")),
                    _num(r.get("output_tokens")),
                    _num(float(r["cost_usd"]) if r.get("cost_usd") is not None else None, 4),
                    str(r["created"]),
                    str(r["dropped"]),
                    _rate(r["created"], r["dropped"]),
                    _top(reasons),
                ]
            )
            + " |"
        )
    lines.append(
        "| **Итого** | | | "
        + f"{len(rows)} запусков | {total['duration_seconds']:.1f} | {int(total['fragments'])} "
        + f"| {int(total['input_tokens'])} | {int(total['output_tokens'])} "
        + f"| {total['cost_usd']:.4f} | {int(total['created'])} | {int(total['dropped'])} "
        + f"| {_rate(int(total['created']), int(total['dropped']))} | {_top(reasons_all)} |"
    )
    return "\n".join(lines) + "\n"


def _source(entities: Entities, row: dict[str, Any]) -> str:
    source_id = row.get("source_id")
    if not source_id:
        return f"`{row.get('target') or '—'}`"
    entity = entities.by_external("library", source_id)
    title = entities.label(entity) if entity else None
    return f"{title} (`{source_id}`)" if title else f"`{source_id}`"


def write_report(
    engine: Engine, entities: Entities, since: date, until: date | None, out: Path
) -> int:
    text = report(engine, entities, since, until)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    runs = len(report_rows(engine, since, until))
    events.emit("knowledge.extraction.report", runs=runs, out=str(out))
    return runs


# --- сборка и команда ---


class _Texts:
    """Текст абзаца для сверки цитаты: абзацы версии из её ответа библиотеки, прочие — тем же
    интерфейсом библиотеки по одному."""

    def __init__(self, library: ServiceClient) -> None:
        self.library = library
        self.known: dict[str, str] = {}

    def prime(self, paragraphs: list[dict[str, Any]]) -> None:
        self.known.update({p["id"]: p["text"] for p in paragraphs})

    def __call__(self, paragraph_id: str) -> str | None:
        if paragraph_id in self.known:
            return self.known[paragraph_id]
        response = self.library.get(f"internal/paragraphs/{paragraph_id}")
        return response.json()["text"] if response.status_code == 200 else None


@dataclass
class Service:
    filling: Filling
    engine: Engine
    texts: _Texts

    def version(self, version_id: str) -> dict[str, Any]:
        response = self.filling.library.get(f"internal/versions/{version_id}/paragraphs")
        if response.status_code == 404:
            raise CommandError(f"версия {version_id} не найдена в библиотеке")
        if response.status_code != 200:
            raise CommandError(f"библиотека ответила {response.status_code} на версию {version_id}")
        data = response.json()
        self.texts.prime(data["paragraphs"])
        return data


def _knowledge(env: dict[str, str]) -> tuple[Engine, OntologyRegistry]:
    from philograph.platform.db import make_engine

    engine = make_engine(env["PHILOGRAPH_DATABASE_URL"], [t.SCHEMA])
    t.migrations.upgrade(engine)
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    return engine, registry


def build(env: dict[str, str], library_url: str | None = None) -> Service:
    engine, registry = _knowledge(env)
    url = library_url or env.get("PHILOGRAPH_LIBRARY_URL")
    if not url:
        raise CommandError("нужен PHILOGRAPH_LIBRARY_URL или --library-url")
    library = ServiceClient("library", url.rstrip("/") + "/api", timeout=60)
    texts = _Texts(library)
    statements = Statements(engine, registry, Entities(engine, registry), texts)
    return Service(Filling(statements, None, library), engine, texts)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m philograph.knowledge.external_extraction",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("export", help="выгрузить задание JSONL по версии")
    p.add_argument("--version", required=True)
    p.add_argument("--out", type=Path, default=Path("."))
    p.add_argument("--library-url")
    p = sub.add_parser("ingest", help="записать ответы извлекателя")
    p.add_argument("--version", required=True)
    p.add_argument("--replies", type=Path, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--input-tokens", type=int, required=True)
    p.add_argument("--output-tokens", type=int, required=True)
    p.add_argument("--cache-read-tokens", type=int, default=0)
    p.add_argument("--duration", type=float, required=True, help="секунды")
    p.add_argument("--price-in", type=float)
    p.add_argument("--price-out", type=float)
    p.add_argument("--price-cache-read", type=float)
    p.add_argument("--replace", action="store_true", help="откатить прежний внешний запуск")
    p.add_argument("--library-url")
    p = sub.add_parser("report", help="таблица запусков извлечения в Markdown")
    p.add_argument("--since", type=date.fromisoformat, required=True)
    p.add_argument("--until", type=date.fromisoformat)
    p.add_argument("--out", type=Path, required=True)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    env: dict[str, str] | None = None,
    service: Service | None = None,
) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    env = dict(os.environ) if env is None else env
    try:
        if args.command == "report":  # отчёт читает только базу знаний, библиотека не нужна
            if service is not None:
                engine, entities = service.engine, service.filling.entities
            else:
                engine, registry = _knowledge(env)
                entities = Entities(engine, registry)
            runs = write_report(engine, entities, args.since, args.until, args.out)
            print(f"{args.out}: {runs} запусков")
            return 0
        svc = service or build(env, getattr(args, "library_url", None))
        if args.command == "export":
            path = export(svc.filling, svc.version(args.version), args.out)
            print(path)
        elif args.command == "ingest":
            price = price_for(args.model, args.price_in, args.price_out, args.price_cache_read)
            replies = read_replies(args.replies)
            row = ingest(
                svc.filling,
                svc.version(args.version),
                replies,
                model=args.model,
                input_tokens=args.input_tokens,
                output_tokens=args.output_tokens,
                duration_seconds=args.duration,
                cost_usd=price.cost(args.input_tokens, args.output_tokens, args.cache_read_tokens),
                replace=args.replace,
            )
            print(json.dumps(_summary(row), ensure_ascii=False))
    except CommandError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Forbidden as exc:
        print(f"источник {exc} без разрешения на внешнюю обработку", file=sys.stderr)
        return 3
    except (OSError, ServiceUnavailable) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "run_id",
        "model",
        "extractor",
        "status",
        "fragments",
        "created",
        "dropped",
        "drop_reasons",
        "input_tokens",
        "output_tokens",
        "duration_seconds",
        "cost_usd",
    )
    return {k: row.get(k) for k in keys}


if __name__ == "__main__":
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    events.configure(sinks=[events.json_sink(sys.stderr)])
    sys.exit(main())
