"""Каталог источников: ``python -m philograph.library.catalog <команда>``.

Команды:
  add <url> --kind K [--section S] [--adapter A]   черновик записи по ссылке
  harvest [--id ID ...]                             обновить данные с сайта, показать изменения
  approve ID ... [--by NAME] [--note TEXT]          одобрить записи
  validate                                          проверить каталог (для CI)
  sync [--id ID ...] [--dry-run]                    привести библиотеку к каталогу
  check-updates                                     проверить обновления файлов по ссылкам
  status                                            состояние записей

Для sync, check-updates и status нужны PHILOGRAPH_DATABASE_URL и PHILOGRAPH_FILES_ROOT.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from philograph.library.catalog import model
from philograph.library.catalog.service import OUTCOMES
from philograph.platform.clock import SystemClock

DEFAULT_CATALOG = Path("sources/catalog.yaml")


def _service(catalog: model.Catalog):
    from philograph.library import schema
    from philograph.library.catalog.fetcher import CatalogFetch, Fetcher
    from philograph.library.catalog.service import CatalogService
    from philograph.library.processing import Pipeline, PipelineSettings
    from philograph.library.registry import Registry
    from philograph.operator.access import migrations as operator_migrations
    from philograph.platform.db import make_engine
    from philograph.platform.files import FileStore
    from philograph.platform.queue import migrations as queue_migrations

    sets = (schema.migrations, operator_migrations, queue_migrations)
    engine = make_engine(os.environ["PHILOGRAPH_DATABASE_URL"], [m.schema for m in sets])
    for m in sets:
        m.upgrade(engine)
    files = FileStore(Path(os.environ["PHILOGRAPH_FILES_ROOT"]))
    fetcher = Fetcher()
    registry = Registry(engine)
    pipeline = Pipeline(
        registry,
        files,
        CatalogFetch(engine, fetcher, files),
        settings=PipelineSettings(fetch_retries=0),  # повторы делает загрузчик
    )
    return CatalogService(catalog, registry, pipeline, fetcher), engine


def _table(rows: list[list[str]], head: list[str]) -> str:
    widths = [max(len(str(r[i])) for r in [head, *rows]) for i in range(len(head))]
    lines = ["  ".join(str(c).ljust(w) for c, w in zip(head, widths, strict=True))]
    lines.append("  ".join("-" * w for w in widths))
    for r in rows:
        lines.append("  ".join(str(c).ljust(w) for c, w in zip(r, widths, strict=True)))
    return "\n".join(lines)


def _outcomes(outcomes) -> str:
    rows = [
        [
            o.catalog_id,
            OUTCOMES.get(o.outcome, o.outcome),
            o.state or "",
            o.version_id or "",
            o.detail[:120],
        ]
        for o in outcomes
    ]
    return _table(rows, ["запись", "итог", "состояние", "версия", "подробности"])


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="python -m philograph.library.catalog",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("add")
    p.add_argument("url")
    p.add_argument("--kind", required=True, choices=["textbook", "primary", "reference"])
    p.add_argument("--section")
    p.add_argument("--adapter", choices=["gutenberg", "wikisource", "archive_org", "direct"])
    p = sub.add_parser("harvest")
    p.add_argument("--id", action="append")
    p = sub.add_parser("approve")
    p.add_argument("ids", nargs="+")
    p.add_argument("--by", default="operator")
    p.add_argument("--note")
    sub.add_parser("validate")
    p = sub.add_parser("sync")
    p.add_argument("--id", action="append")
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("check-updates")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    catalog = model.Catalog.load(args.catalog)
    clock = SystemClock()

    if args.command == "validate":
        problems = model.validate(catalog, year=clock.now().year)
        for problem in problems:
            print(problem)
        errors = [p for p in problems if p.level == "error"]
        print(
            f"записей: {len(catalog.entries)} "
            f"{json.dumps(model.counts(catalog), ensure_ascii=False)}; "
            f"ошибок: {len(errors)}, предупреждений: {len(problems) - len(errors)}"
        )
        return 1 if errors else 0

    if args.command in ("add", "harvest"):
        from philograph.library.catalog.fetcher import Fetcher
        from philograph.library.catalog.service import CatalogService

        service = CatalogService(catalog, None, None, Fetcher(), clock)  # type: ignore[arg-type]
        if args.command == "add":
            entry, new = service.add(
                args.url, kind=args.kind, section=args.section, adapter=args.adapter
            )
            if new:
                service.fill_death_years(entry)
                if entry["license"] is None:
                    from philograph.library.catalog.adapters import Harvest, suggest_license

                    h = entry["harvested"]
                    entry["license"] = suggest_license(
                        Harvest(h["metadata"], h["files"], h["license_hint"]), clock.now().year
                    )
                catalog.save()
                meta = model.metadata(entry)
                print(
                    f"добавлено: {entry['id']} — {meta.get('title')}; "
                    f"авторы: {', '.join(a['name'] for a in meta.get('authors') or [])}; "
                    f"лицензия: {(entry['license'] or {}).get('kind', 'не определена')}"
                )
            else:
                print(f"уже в каталоге: {entry['id']}")
            return 0
        for entry in catalog.entries:
            if args.id and entry["id"] not in args.id:
                continue
            if entry["adapter"] == "direct":
                continue
            for change in service.harvest(entry):
                print(f"{entry['id']}: {change.field}: {change.old!r} → {change.new!r}")
        catalog.save()
        return 0

    if args.command == "approve":
        for entry_id in args.ids:
            entry = catalog.find(entry_id)
            if entry is None:
                print(f"нет записи {entry_id}")
                return 1
            entry["review"] = {
                "status": "approved",
                "by": args.by,
                "at": clock.now().date().isoformat(),
                "note": args.note,
            }
        catalog.save()
        return 0

    service, engine = _service(catalog)
    if args.command == "status":
        rows = [
            [
                r["id"],
                r["review"],
                r["source_id"] or "",
                r["latest_state"] or "",
                "да" if r["published"] else "",
                str(r["fetch_failures"] or ""),
                (r["error"] or {}).get("message", "")[:80] if r["error"] else "",
            ]
            for r in service.status()
        ]
        print(
            _table(
                rows,
                [
                    "запись",
                    "одобрение",
                    "источник",
                    "последняя версия",
                    "опубликован",
                    "неудач",
                    "ошибка",
                ],
            )
        )
        return 0
    outcomes = (
        service.check_updates()
        if args.command == "check-updates"
        else service.sync(args.id, dry_run=args.dry_run)
    )
    if not getattr(args, "dry_run", False):
        from philograph.platform.queue import Queue

        service.pipeline.dispatch_outbox(Queue(engine))
    print(_outcomes(outcomes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
