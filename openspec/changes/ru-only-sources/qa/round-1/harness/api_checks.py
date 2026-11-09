"""Независимая проверка HTTP-слоя, учёта регионов и событий ru-only-sources (группы 1-2).

Не меняет код проекта и не использует тесты проекта как источник истины: создаёт свой учёт
во временной SQLite и вызывает приложение как клиент (TestClient / httpx через шлюз).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from philograph.gateway.app import build_app as gateway_app
from philograph.library import schema
from philograph.library.app import build_app
from philograph.library.catalog.service import CatalogService
from philograph.library.processing import Pipeline
from philograph.library.reading import Reader, Reading
from philograph.library.registry import License, Registry, RegistryError
from philograph.operator.access import migrations as operator_migrations
from philograph.platform.db import make_engine
from philograph.platform.files import FileStore
from tests.library.builders import epub

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent / "api-stand"

CHECKS: list[dict] = []


def check(case_id: str, step: str, ok: bool, expected: str, actual) -> None:
    CHECKS.append(
        {
            "case": case_id,
            "step": step,
            "ok": bool(ok),
            "expected": expected,
            "actual": actual if isinstance(actual, str) else json.dumps(actual, ensure_ascii=False, default=str),
        }
    )
    print(("PASS " if ok else "FAIL ") + case_id + " / " + step)


def payload_of(row: dict) -> dict:
    value = row.get("payload")
    return json.loads(value) if isinstance(value, str) else dict(value or {})


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    for stale in WORK.glob("api*.db*"):
        stale.unlink()
    engine = make_engine(
        f"sqlite:///{(WORK / 'api.db').as_posix()}", [schema.SCHEMA, operator_migrations.schema]
    )
    schema.migrations.upgrade(engine)
    operator_migrations.upgrade(engine)
    registry = Registry(engine)
    perms = {"display": True, "external_processing": True, "quoting": True}
    registry.add_license_kind("public-domain", "Общественное достояние", "https://example.org/pd", perms)
    registry.add_license_kind("no-display", "Только для обработки", None, {**perms, "display": False})
    registry.add_license_kind(
        "public-domain-ru", "Общественное достояние по праву РФ", None, perms, regions=["RU"]
    )
    files = {
        "book.epub": epub(
            [
                ("Глава 1. Опыт", "<p>Всякое знание начинается с опыта, говорит Кант.</p><p>Но не всё.</p>"),
                ("Глава 2. Рассудок", "<p>Рассудок даёт правила явлениям.</p>"),
            ]
        ),
        "ru.txt": "Глава 1. Русская мысль\n\nПознание — процесс постижения мира.\n\nещё абзац\n".encode(),
        "open.txt": "Глава 1. Открытая\n\nОткрытый текст источника.\n".encode(),
    }
    pipeline = Pipeline(registry, FileStore(WORK / "files"), lambda spec: files[spec["path"]])
    lic = License("public-domain", "public_domain", author_death_years=[1900])
    ids: dict[str, str] = {}
    ids["book"] = registry.register(
        "operator", title="История теории познания", authors=["В. Ф. Асмус"], year=1950,
        language="ru", kind="textbook", license=lic, scope="public",
        files=[{"name": "b", "path": "book.epub"}],
    )
    ids["open"] = registry.register(
        "operator", title="Открытая книга", authors=["А. Автор"], year=2000,
        language="ru", kind="primary", license=lic, scope="public",
        files=[{"name": "o", "path": "open.txt"}],
    )
    ids["limited"] = registry.register(
        "operator", title="Русский учебник", authors=["П. Д. Юркевич"], year=1865,
        language="ru", kind="textbook",
        license=License("public-domain-ru", "public_domain", author_death_years=[1900]),
        scope="public", files=[{"name": "r", "path": "ru.txt"}],
    )
    ids["ref"] = registry.register(
        "operator", title="Справочник", authors=["Коллектив"], year=2010,
        language="ru", kind="reference", license=lic, scope="public",
        files=[{"name": "r", "path": "open.txt"}],
    )
    for key in ("book", "open", "limited", "ref"):
        version = pipeline.start("operator", ids[key])
        registry.publish("operator", version)
    ids["unpublished"] = registry.register(
        "operator", title="Черновик", authors=["Автор"], year=2020, language="ru",
        kind="textbook", license=lic, scope="public", files=[{"name": "u", "path": "open.txt"}],
    )
    reading = Reading(registry, engine)
    reading.set_default("operator", ids["book"])
    client = TestClient(build_app(reading))

    def rows(headers: dict | None = None) -> dict[str, dict]:
        response = client.get("/api/v1/sources", headers=headers or {})
        assert response.status_code == 200, response.text
        return {s["id"]: s for s in response.json()["sources"]}

    def sources_body(headers: dict | None = None) -> dict:
        return client.get("/api/v1/sources", headers=headers or {}).json()

    # ---------- R5 / TC-7: список для DE ----------
    body_de = sources_body({"X-Philograph-Region": "DE"})
    de_rows = {s["id"]: s for s in body_de["sources"]}
    restricted = de_rows.get(ids["limited"])
    check(
        "TC-7",
        "DE: закрытая строка — только id/title/authors/restricted/regions",
        restricted == {
            "id": ids["limited"],
            "title": "Русский учебник",
            "authors": ["П. Д. Юркевич"],
            "restricted": True,
            "regions": ["RU"],
        },
        "id, title, authors, restricted:true, regions:['RU']",
        restricted,
    )
    check(
        "TC-7",
        "DE: у закрытой строки нет года/лицензии/вида/языка",
        restricted is not None
        and not ({"year", "license", "kind", "language", "translator", "edition"} & set(restricted)),
        "нет year, license, kind, language",
        sorted(restricted or {}),
    )
    check(
        "TC-7",
        "DE: default_source_id — открытый учебник",
        body_de.get("default_source_id") == ids["book"],
        f"default_source_id={ids['book']}",
        body_de.get("default_source_id"),
    )
    check(
        "EC-7",
        "неопубликованный источник отсутствует в списке",
        ids["unpublished"] not in de_rows,
        "источника нет в списке",
        ids["unpublished"] in de_rows,
    )
    open_row = de_rows.get(ids["open"]) or {}
    check(
        "TC-7",
        "DE: открытая строка обычная (год, вид, лицензия на месте)",
        "restricted" not in open_row
        and open_row.get("year") == 2000
        and open_row.get("kind") == "primary"
        and open_row.get("license", {}).get("title") == "Общественное достояние",
        "год 2000, kind primary, лицензия с названием",
        {k: open_row.get(k) for k in ("id", "year", "kind", "license")},
    )

    # ---------- R4 / TC-9 / TC-10: RU, без заголовка, мусор ----------
    ru_rows = {s["id"]: s for s in sources_body({"X-Philograph-Region": "RU"})["sources"]}
    ru = ru_rows.get(ids["limited"]) or {}
    check(
        "TC-9",
        "RU: закрытый источник открыт обычной строкой",
        "restricted" not in ru and ru.get("year") == 1865 and ru.get("kind") == "textbook",
        "обычная строка с годом 1865",
        {k: ru.get(k) for k in ("id", "year", "kind", "restricted")},
    )
    for label, headers in (
        ("без заголовка", {}),
        ("пустой заголовок", {"X-Philograph-Region": ""}),
        ("RU1", {"X-Philograph-Region": "RU1"}),
        ("XX", {"X-Philograph-Region": "XX"}),
    ):
        got = {s["id"]: s for s in sources_body(headers)["sources"]}.get(ids["limited"]) or {}
        check(
            "TC-10",
            f"неизвестный регион ({label}): ограниченный закрыт",
            got.get("restricted") is True and "year" not in got,
            "restricted:true без года",
            got,
        )
    from philograph.library.reading import parse_region

    parsed = {value: parse_region(value) for value in ("ru", "RU", "RU1", "РФ", "", None, "T1")}
    check(
        "EC-6",
        "разбор региона: только две латинские буквы",
        parsed == {"ru": "RU", "RU": "RU", "RU1": None, "РФ": None, "": None, None: None, "T1": None},
        "ru→RU, RU→RU, остальное → None",
        parsed,
    )
    lower = {s["id"]: s for s in sources_body({"X-Philograph-Region": "ru"})["sources"]}
    check(
        "EC-5",
        "строчный код региона ru приводится к RU",
        "restricted" not in (lower.get(ids["limited"]) or {}),
        "источник открыт",
        (lower.get(ids["limited"]) or {}),
    )

    # ---------- R5 / TC-9: оглавление и глава ----------
    toc_de = client.get(f"/api/v1/sources/{ids['limited']}/toc", headers={"X-Philograph-Region": "DE"})
    check(
        "R5",
        "оглавление закрытого источника для DE — 404 source_unavailable",
        toc_de.status_code == 404 and toc_de.json().get("kind") == "source_unavailable",
        "404 kind=source_unavailable",
        {"status": toc_de.status_code, "body": toc_de.json()},
    )
    toc_ru = client.get(f"/api/v1/sources/{ids['limited']}/toc", headers={"X-Philograph-Region": "RU"})
    check(
        "TC-9",
        "оглавление закрытого источника для RU — 200",
        toc_ru.status_code == 200 and bool(toc_ru.json()),
        "200 и непустое оглавление",
        {"status": toc_ru.status_code, "items": len(toc_ru.json()) if toc_ru.status_code == 200 else None},
    )
    chapter_id = next(i["chapter_id"] for i in toc_ru.json() if i.get("chapter_id"))
    chapter_de = client.get(
        f"/api/v1/sources/{ids['limited']}/chapters/{chapter_id}",
        headers={"X-Philograph-Region": "DE"},
    )
    check(
        "R5",
        "глава закрытого источника для DE — 404 и без текста",
        chapter_de.status_code == 404
        and chapter_de.json().get("kind") == "source_unavailable"
        and "Познание" not in chapter_de.text,
        "404 source_unavailable, без текста главы",
        {"status": chapter_de.status_code, "body": chapter_de.json()},
    )
    chapter_ru = client.get(
        f"/api/v1/sources/{ids['limited']}/chapters/{chapter_id}",
        headers={"X-Philograph-Region": "RU"},
    )
    blocks = [b for b in chapter_ru.json().get("blocks", []) if b.get("type") == "block"]
    check(
        "TC-9",
        "глава закрытого источника для RU — 200 с текстом",
        chapter_ru.status_code == 200 and any("Познание" in b.get("text", "") for b in blocks),
        "200 и текст главы",
        {"status": chapter_ru.status_code, "blocks": len(blocks)},
    )

    # ---------- R6 / TC-12 / TC-13: ссылка на абзац ----------
    from philograph.library.reading import Internal

    version_id = registry.get(ids["limited"]).published_version or ""
    paragraphs = Internal(registry, reading).version_paragraphs(version_id)["paragraphs"]
    paragraph_id = paragraphs[0]["id"]
    for case_id, headers, closed in (
        ("TC-12", {"X-Philograph-Region": "DE"}, True),
        ("TC-12", {}, True),
        ("TC-13", {"X-Philograph-Region": "RU"}, False),
    ):
        answer = client.get(f"/api/v1/paragraphs/{paragraph_id}", headers=headers).json()
        if closed:
            check(
                case_id,
                "закрытый регион: status/reason/source, без text, chapter_id, section_id",
                answer
                == {
                    "status": "source_unavailable",
                    "reason": "region",
                    "source": {
                        "id": ids["limited"],
                        "title": "Русский учебник",
                        "authors": ["П. Д. Юркевич"],
                    },
                },
                "source_unavailable + reason region + title/authors, без текста",
                answer,
            )
        else:
            check(
                case_id,
                "RU: абзац найден",
                answer.get("status") == "found"
                and answer.get("source_id") == ids["limited"]
                and answer.get("chapter_id"),
                "status=found, source_id источника, глава определена",
                {k: answer.get(k) for k in ("status", "source_id", "chapter_id")},
            )

    # ---------- R5 / TC-11: запомненный источник ----------
    current_de = client.get(
        "/api/v1/current", params={"remembered": ids["limited"]}, headers={"X-Philograph-Region": "DE"}
    ).json()
    check(
        "TC-11",
        "DE: запомненный закрытый → учебник по умолчанию + previous_unavailable",
        current_de == {"source_id": ids["book"], "notice": "previous_unavailable"},
        "source_id=учебник, notice=previous_unavailable",
        current_de,
    )
    current_ru = client.get(
        "/api/v1/current", params={"remembered": ids["limited"]}, headers={"X-Philograph-Region": "RU"}
    ).json()
    check(
        "UC-2",
        "RU: запомненный закрытый источник остаётся текущим",
        current_ru == {"source_id": ids["limited"], "notice": None},
        "source_id=запомненный",
        current_ru,
    )
    current_plain = client.get("/api/v1/current", headers={"X-Philograph-Region": "DE"}).json()
    check(
        "TC-11",
        "DE без запомненного: учебник по умолчанию без уведомления",
        current_plain == {"source_id": ids["book"], "notice": None},
        "source_id=учебник, notice=None",
        current_plain,
    )
    current_open = client.get(
        "/api/v1/current", params={"remembered": ids["open"]}, headers={"X-Philograph-Region": "DE"}
    ).json()
    check(
        "TC-11",
        "DE: запомненный открытый источник остаётся текущим",
        current_open == {"source_id": ids["open"], "notice": None},
        "source_id=запомненный открытый",
        current_open,
    )

    # ---------- R5: фильтры и поиск действуют на закрытую строку ----------
    by_kind = client.get(
        "/api/v1/sources", params={"kind": "textbook"}, headers={"X-Philograph-Region": "DE"}
    ).json()
    textbook_ids = {s["id"]: s for s in by_kind["sources"]}
    check(
        "TC-8",
        "фильтр вида: закрытый учебник остаётся строкой restricted",
        (textbook_ids.get(ids["limited"]) or {}).get("restricted") is True,
        "restricted:true в фильтре kind=textbook",
        (textbook_ids.get(ids["limited"]) or {}),
    )
    by_primary = client.get(
        "/api/v1/sources", params={"kind": "primary"}, headers={"X-Philograph-Region": "DE"}
    ).json()
    check(
        "TC-8",
        "фильтр вида исключает закрытый учебник из списка первоисточников",
        ids["limited"] not in {s["id"] for s in by_primary["sources"]},
        "закрытого учебника нет при kind=primary",
        sorted(s["id"] for s in by_primary["sources"]),
    )
    found = client.get(
        "/api/v1/sources", params={"q": "юркевич"}, headers={"X-Philograph-Region": "DE"}
    ).json()
    check(
        "TC-8",
        "поиск по автору находит закрытую строку",
        [s["id"] for s in found["sources"]] == [ids["limited"]]
        and found["sources"][0].get("restricted") is True,
        "одна строка restricted по запросу «юркевич»",
        [{"id": s["id"], "restricted": s.get("restricted")} for s in found["sources"]],
    )

    # ---------- R5 / EC-12: служебный регион "*" клиенту не помогает ----------
    star = {s["id"]: s for s in sources_body({"X-Philograph-Region": "*"})["sources"]}
    check(
        "EC-12",
        "заголовок '*' не открывает закрытый источник (регион неизвестен)",
        (star.get(ids["limited"]) or {}).get("restricted") is True,
        "restricted:true",
        (star.get(ids["limited"]) or {}),
    )

    # ---------- R5: закрытый источник не становится учебником по умолчанию для читателя ----------
    reading.set_default("operator", ids["limited"])
    default_de = client.get("/api/v1/sources", headers={"X-Philograph-Region": "DE"}).json()
    default_ru = client.get("/api/v1/sources", headers={"X-Philograph-Region": "RU"}).json()
    current_none = client.get("/api/v1/current", headers={"X-Philograph-Region": "DE"}).json()
    check(
        "R5",
        "закрытый источник не отдаётся как учебник по умолчанию читателю вне РФ",
        default_de.get("default_source_id") is None
        and default_ru.get("default_source_id") == ids["limited"]
        and current_none == {"source_id": None, "notice": None},
        "DE: default=null, current.source_id=null; RU: default=закрытый",
        {
            "de_default": default_de.get("default_source_id"),
            "ru_default": default_ru.get("default_source_id"),
            "de_current": current_none,
        },
    )
    reading.set_default("operator", ids["book"])

    # ---------- R7 / TC-14, TC-15, TC-16: служебные интерфейсы ----------
    published = client.get("/api/v1/internal/published").json()
    published_ids = {row["source_id"] for row in published}
    check(
        "TC-14",
        "внутренний published содержит закрытый источник",
        {ids["limited"], ids["book"], ids["open"], ids["ref"]} <= published_ids,
        "все опубликованные, включая ограниченный",
        {"published": sorted(published_ids), "unpublished_in": ids["unpublished"] in published_ids},
    )
    for region, expected in (
        ("DE", [ids["limited"]]),
        ("RU", []),
        ("ru", []),
        ("T1", [ids["limited"]]),
    ):
        answer = client.get("/api/v1/internal/access", params={"region": region}).json()
        check(
            "TC-15",
            f"internal/access?region={region}",
            answer.get("closed") == expected,
            f"closed={expected}",
            answer,
        )
    answer = client.get("/api/v1/internal/access").json()
    check(
        "TC-15",
        "internal/access без региона — закрытый источник в closed",
        answer.get("closed") == [ids["limited"]] and answer.get("region") is None,
        "closed=[ограниченный], region=null",
        answer,
    )
    payload = client.get(f"/api/v1/internal/versions/{version_id}/paragraphs").json()
    check(
        "TC-16",
        "ответ версии несёт regions, permissions, external_processing",
        payload.get("regions") == ["RU"]
        and payload.get("external_processing") is True
        and payload.get("permissions", {}).get("display") is True
        and payload.get("published") is True,
        "regions=['RU'], external_processing=true, permissions.display=true, published=true",
        {k: payload.get(k) for k in ("regions", "external_processing", "permissions", "published")},
    )
    open_version = registry.get(ids["open"]).published_version
    open_payload = client.get(f"/api/v1/internal/versions/{open_version}/paragraphs").json()
    check(
        "EC-1",
        "у источника без ограничения regions = null («везде»)",
        open_payload.get("regions") is None,
        "regions=null",
        open_payload.get("regions"),
    )

    # ---------- R1 / R2 / R3 / EC-1..EC-6: учёт регионов ----------
    registry.add_license_kind("kind-both", "RU и BY", None, perms, regions=["RU", "BY"])
    source_ru = registry.register(
        "operator", title="Только РФ", authors=["А"], language="ru", kind="primary",
        license=License("kind-both", "public_domain", author_death_years=[1900], regions=["RU"]),
        scope="public", files=[{"name": "x", "path": "open.txt"}],
    )
    source_all = registry.register(
        "operator", title="РФ и BY", authors=["Б"], language="ru", kind="primary",
        license=License("kind-both", "public_domain", author_death_years=[1900]), scope="public",
        files=[{"name": "y", "path": "open.txt"}],
    )
    check(
        "TC-2",
        "источник [RU] при виде [RU,BY] → {RU}",
        registry.regions(source_ru) == frozenset({"RU"}),
        "frozenset({'RU'})",
        sorted(registry.regions(source_ru) or []),
    )
    check(
        "TC-2",
        "источник без сужения при виде [RU,BY] → {RU,BY}",
        registry.regions(source_all) == frozenset({"RU", "BY"}),
        "frozenset({'RU','BY'})",
        sorted(registry.regions(source_all) or []),
    )
    try:
        registry.register(
            "operator", title="Шире вида", authors=["В"], language="ru", kind="primary",
            license=License("public-domain-ru", "public_domain", author_death_years=[1900], regions=["RU", "DE"]),
            scope="public", files=[{"name": "z", "path": "open.txt"}],
        )
    except RegistryError as exc:
        check(
            "TC-3",
            "расширение регионов источника относительно вида отклонено",
            exc.fields == ["license.regions"],
            "RegistryError fields=['license.regions']",
            {"error": str(exc), "fields": exc.fields},
        )
    else:
        check("TC-3", "расширение регионов отклонено", False, "RegistryError", "регистрация прошла")
    for bad in ("RU1", "РФ", "", "r"):
        try:
            registry.register(
                "operator", title=f"Плохой код {bad!r}", authors=["Г"], language="ru", kind="primary",
                license=License("public-domain", "public_domain", author_death_years=[1900], regions=[bad]),
                scope="public", files=[{"name": "z", "path": "open.txt"}],
            )
        except RegistryError as exc:
            check(
                "EC-6",
                f"код {bad!r} отклонён",
                exc.fields == ["license.regions"],
                "RegistryError fields=['license.regions']",
                {"error": str(exc), "fields": exc.fields},
            )
        else:
            check("EC-6", f"код {bad!r} отклонён", False, "RegistryError", "принят")
    # EC-2: пустой список регионов у вида = «везде»
    registry.add_license_kind("kind-empty", "Пустой список", None, perms, regions=[])
    empty_source = registry.register(
        "operator", title="Пусто у вида", authors=["Д"], language="ru", kind="primary",
        license=License("kind-empty", "public_domain", author_death_years=[1900]), scope="public",
        files=[{"name": "e", "path": "open.txt"}],
    )
    check(
        "EC-2",
        "регионы вида [] = «везде» (regions()→None, открыт без региона)",
        registry.regions(empty_source) is None
        and registry.permissions(empty_source)["display"] is True,
        "regions=None, display=true",
        {"regions": registry.regions(empty_source), "permissions": registry.permissions(empty_source)},
    )

    # ---------- R8 / TC-5: change_license → source.access_changed ----------
    before_ids = {row["event_id"] for row in registry.outbox_pending()}
    published_before = registry.get(source_all).published_version
    registry.change_license(
        "operator", source_all,
        License("kind-both", "public_domain", author_death_years=[1900], regions=["RU"]),
    )
    new_events = [r for r in registry.outbox_pending() if r["event_id"] not in before_ids]
    event = payload_of(new_events[-1]) if new_events else {}
    check(
        "TC-5",
        "change_license: событие source.access_changed с регионами и разрешениями",
        [r["kind"] for r in new_events] == ["source.access_changed"]
        and event.get("source_id") == source_all
        and event.get("regions") == ["RU"]
        and event.get("permissions", {}).get("display") is True,
        "kind=source.access_changed, payload source_id/regions=['RU']/permissions",
        {"kinds": [r["kind"] for r in new_events], "payload": event},
    )
    check(
        "TC-5",
        "после смены регионов версия остаётся опубликованной",
        registry.get(source_all).published_version == published_before,
        f"published_version={published_before}",
        registry.get(source_all).published_version,
    )

    # ---------- EC-15: два change_license подряд ----------
    before_ids = {row["event_id"] for row in registry.outbox_pending()}
    for regions in (["BY"], ["RU", "BY"]):
        registry.change_license(
            "operator", source_all,
            License("kind-both", "public_domain", author_death_years=[1900], regions=regions),
        )
    two = [payload_of(r) for r in registry.outbox_pending() if r["event_id"] not in before_ids]
    check(
        "EC-15",
        "два change_license подряд: два события по порядку, в БД последнее состояние",
        [e.get("regions") for e in two] == [["BY"], ["BY", "RU"]]
        and registry.get(source_all).license.regions == ["BY", "RU"],
        "события [['BY'], ['BY','RU']] (коды отсортированы), в БД ['BY','RU']",
        {"events": [e.get("regions") for e in two], "db": registry.get(source_all).license.regions},
    )

    # ---------- R3 / TC-4 / EC-4: пустое пересечение после сужения вида ----------
    registry.add_license_kind("kind-narrow", "BY, затем RU", None, perms, regions=["RU", "BY"])
    narrow_source = registry.register(
        "operator", title="Только BY", authors=["Е"], language="ru", kind="primary",
        license=License("kind-narrow", "public_domain", author_death_years=[1900], regions=["BY"]),
        scope="public", files=[{"name": "n", "path": "open.txt"}],
    )
    registry.add_license_kind("kind-narrow", "BY, затем RU", None, perms, regions=["RU"])
    check(
        "TC-4",
        "сужение вида до [RU] при источнике [BY]: пустое пересечение = запрет показа",
        registry.regions(narrow_source) == frozenset()
        and registry.permissions(narrow_source)["display"] is False,
        "regions=frozenset(), display=false",
        {
            "regions": sorted(registry.regions(narrow_source) or []),
            "permissions": registry.permissions(narrow_source),
        },
    )
    kind_change = [
        payload_of(r) for r in registry.outbox_pending()
        if r["kind"] == "source.access_changed" and payload_of(r).get("source_id") == narrow_source
    ]
    check(
        "TC-4",
        "по источнику с пустым пересечением записано событие с пустыми регионами",
        kind_change and kind_change[-1].get("regions") == []
        and kind_change[-1].get("permissions", {}).get("display") is False,
        "payload regions=[], permissions.display=false",
        kind_change[-1] if kind_change else None,
    )
    with engine.begin() as conn:
        from sqlalchemy import select as sa_select

        from philograph.library import schema as t

        narrow_row = conn.execute(
            sa_select(t.sources.c.published_version).where(t.sources.c.id == narrow_source)
        ).scalar()
    narrow_visible = {
        region: {
            s["id"]
            for s in client.get("/api/v1/sources", headers={"X-Philograph-Region": region}).json()["sources"]
        }
        for region in ("RU", "DE")
    }
    check(
        "EC-4",
        "источник с пустым пересечением не показывается ни в одном регионе",
        all(narrow_source not in ids for ids in narrow_visible.values()),
        "источника нет в списке ни для RU, ни для DE",
        {region: narrow_source in ids for region, ids in narrow_visible.items()},
    )

    # ---------- R8 / TC-6: sync вида → события по источникам ----------
    before = registry.outbox_pending()[-1]["event_id"] if registry.outbox_pending() else None
    service = CatalogService(
        catalog=SimpleNamespace(licenses=lambda: [
            {"code": "kind-sync", "title": "Синхронизация", "url": None,
             "permissions": perms, "regions": ["RU"]},
        ]),
        registry=registry,
        pipeline=None,
        fetcher=None,
    )
    sync_source = registry.register(
        "operator", title="Источник вида sync", authors=["Ж"], language="ru", kind="primary",
        license=License("public-domain", "public_domain", author_death_years=[1900]),
        scope="public", files=[{"name": "s", "path": "open.txt"}],
    )
    service.ensure_license_kinds()
    sync_source2 = registry.register(
        "operator", title="Второй вида sync", authors=["З"], language="ru", kind="primary",
        license=License("kind-sync", "public_domain", author_death_years=[1900]),
        scope="public", files=[{"name": "s2", "path": "open.txt"}],
    )
    before_ids = {row["event_id"] for row in registry.outbox_pending()}
    registry.add_license_kind("kind-sync", "Синхронизация", None, perms, regions=["RU"])
    unchanged = [r for r in registry.outbox_pending() if r["event_id"] not in before_ids]
    check(
        "EC-9",
        "повторная синхронизация без смены регионов не пишет событий",
        unchanged == [],
        "событий нет",
        [r["kind"] for r in unchanged],
    )
    service.catalog = SimpleNamespace(licenses=lambda: [
        {"code": "kind-sync", "title": "Синхронизация", "url": None,
         "permissions": perms, "regions": None},
    ])
    before_ids = {row["event_id"] for row in registry.outbox_pending()}
    service.ensure_license_kinds()
    sync_events = [payload_of(r) for r in registry.outbox_pending() if r["event_id"] not in before_ids]
    check(
        "TC-6",
        "sync снял регионы вида: событие по источнику вида, регионы null",
        [e.get("source_id") for e in sync_events] == [sync_source2]
        and sync_events[0].get("regions") is None,
        f"одно событие по {sync_source2} с regions=null",
        sync_events,
    )
    check(
        "TC-6",
        "sync не задел источник другого вида",
        sync_source not in [e.get("source_id") for e in sync_events],
        "источник другого вида без события",
        [e.get("source_id") for e in sync_events],
    )

    # ---------- EC-8: лицензия запретила показ → источника нет в списке ----------
    before_ids = {row["event_id"] for row in registry.outbox_pending()}
    registry.change_license(
        "operator", ids["open"],
        License("no-display", "public_domain", author_death_years=[1900]),
    )
    after = {s["id"] for s in client.get("/api/v1/sources", headers={"X-Philograph-Region": "DE"}).json()["sources"]}
    check(
        "EC-8",
        "лицензия запретила показ: источника нет в списке",
        ids["open"] not in after,
        "источника нет",
        {"in_list": ids["open"] in after},
    )
    no_display_events = [
        payload_of(r) for r in registry.outbox_pending()
        if r["event_id"] not in before_ids
        and payload_of(r).get("source_id") == ids["open"]
        and r["kind"] == "source.access_changed"
    ]
    check(
        "EC-8",
        "событие source.access_changed сообщает display=false",
        bool(no_display_events)
        and no_display_events[-1].get("permissions", {}).get("display") is False,
        "permissions.display=false в source.access_changed",
        no_display_events[-1] if no_display_events else None,
    )

    # ---------- EC-10 / EC-11: старые данные и хранение регионов ----------
    with engine.begin() as conn:
        conn.execute(
            schema.sources.insert().values(
                id="s_legacy000001",
                title="Старый источник",
                authors=["Старый автор"],
                language="ru",
                kind="primary",
                license={"kind": "public-domain", "basis": "public_domain", "author_death_years": [1800]},
                scope="public",
                settings={"languages": ["ru"]},
                files=[],
                status="active",
                published_version=None,
                created_at=__import__("datetime").datetime(2020, 1, 1),
            )
        )
    legacy = registry.get("s_legacy000001")
    check(
        "EC-10",
        "старая строка без регионов читается как «везде»",
        legacy.license.regions is None and registry.regions("s_legacy000001") is None,
        "regions=None",
        {"license_regions": legacy.license.regions, "effective": registry.regions("s_legacy000001")},
    )
    db_file = WORK / "api.library.db"
    with sqlite3.connect(db_file) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(sources)")]
        license_json = json.loads(
            conn.execute("SELECT license FROM sources WHERE id = ?", (ids["limited"],)).fetchone()[0]
        )
    check(
        "EC-11",
        "регионы хранятся отдельным столбцом, не в JSON лицензии",
        "regions" in columns and "regions" not in license_json,
        "столбец sources.regions есть, в JSON лицензии regions нет",
        {"has_column": "regions" in columns, "license_keys": sorted(license_json)},
    )

    # ---------- шлюз: что видит внешний клиент ----------
    gateway = gateway_app(
        {"library": "http://library", "assistant": "http://assistant"},
        None,
        transport=httpx.ASGITransport(app=build_app(reading)),
    )
    with TestClient(gateway) as gw:
        spoofed = gw.get("/api/v1/sources", headers={"X-Philograph-Region": "RU"}).json()
        spoofed_rows = {s["id"]: s for s in spoofed["sources"]}
        spoofed_open = "restricted" not in (spoofed_rows.get(ids["limited"]) or {})
        internal_status = gw.get("/api/v1/internal/published").status_code
    CHECKS.append(
        {
            "case": "R4 (вне охвата раунда)",
            "step": "шлюз: клиентский X-Philograph-Region (группа 3 tasks.md)",
            "ok": True,
            "expected": "фиксируется факт, решение — задача 3.2",
            "actual": json.dumps(
                {
                    "client_region_header_reaches_library": spoofed_open,
                    "internal_blocked_status": internal_status,
                },
                ensure_ascii=False,
            ),
        }
    )
    print("шлюз: клиентский заголовок RU открывает закрытый источник =", spoofed_open)
    print("шлюз: /api/v1/internal/published снаружи →", internal_status)

    failed = [c for c in CHECKS if not c["ok"]]
    out = Path(__file__).resolve().parent / "api-report.json"
    out.write_text(
        json.dumps({"checks": CHECKS, "failed": failed}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print("\nИтог: проверок", len(CHECKS), "провалено", len(failed))
    for item in failed:
        print("FAILED:", item["case"], item["step"], "|", item["actual"][:500])


if __name__ == "__main__":
    main()
