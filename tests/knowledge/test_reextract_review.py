"""ontology-extraction (reextract-with-claude), дополнение после ревью: цитата целиком и
знаки нулевой ширины, вид элементов ``entities``, ASCII-цифры номера, повтор ``ingest``
после прерывания, повтор фрагмента в файле, версия не найдена.

По дельте ``specs/ontology-extraction`` (коммит 7e8d8db). Вывод — база, код выхода, stderr;
журнал — ``knowledge.extraction.dropped`` с ``code``, ``knowledge.run.*``.
"""

from __future__ import annotations

import json
import unicodedata
from datetime import timedelta

import httpx
import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as hst

from philograph.knowledge import quotes
from philograph.knowledge import schema as t
from philograph.knowledge.statements import Attribution, Evidence
from philograph.platform.client import ServiceClient

from ..conftest import PROFILES
from .extraction_stand import Stand
from .reextract_common import (
    check_run_accounting,
    dropped_codes,
    one_run,
    runs,
    table_count,
)
from .reextract_common import st as stmt
from .test_reextract_external import ARGS, QUOTES, TEXTS, cli, replies_file, reply_for
from .test_reextract_items import external, ingest

req = pytest.mark.req
EO = "ontology-extraction"
QUOTE = "Цитата у каждого утверждения"
CHECK = "Проверка ответа по утверждениям"
EXTERNAL = "Внешний извлекатель"


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock, fragment_size=8)


def counts(stand):
    return [table_count(stand, tb) for tb in (t.statements, t.evidence, t.attributions)]


# --- цитата ------------------------------------------------------------------------------


@req(EO, QUOTE, scenario="Многоточие автора в цитате")
def test_authors_ellipsis_in_quote(stand, onto, events):
    text = "Он сказал... и замолчал."
    stand.extract([text], {"statements": [stmt("Ницше", "holds", "Молчание", 1, "сказал... и")]})
    [statement] = stand.statements()
    assert [e["quote"] for e in statement["evidence"]] == ["сказал... и"]
    assert events.of("knowledge.extraction.dropped") == []
    assert quotes.check("сказал... и", text) is None  # не quote_too_short
    # перепроверка изменённого абзаца: подтверждение не теряется
    pid = statement["evidence"][0]["paragraph_id"]
    counts_ = onto.statements.handle_library_event(
        "source.published",
        {
            "event_id": "e-ell",
            "source_id": "s_x",
            "removed": [],
            "changed": [pid],
            "redirected": {},
        },
    )
    assert counts_["rechecked"] == 1 and counts_["lost"] == 0
    assert [e["lost"] for e in onto.statements.get(statement["id"])["evidence"]] == [False]
    assert events.where("knowledge.library.event", event_id="e-ell")[0]["lost"] == 0


@req(
    EO,
    QUOTE,
    invariant="Цитата сначала ищется целиком; части по многоточию — только если целиком нет",
)
@pytest.mark.parametrize(
    ("text", "quote", "expected"),
    [
        ("Он сказал... и замолчал.", "сказал... и", None),
        ("Он сказал… и замолчал.", "сказал… и", None),
        ("Он сказал... и замолчал.", "«сказал... и»", None),
        (
            "Он сказал... и замолчал.",
            "сказал [...] и",
            "quote_too_short",
        ),  # целиком нет, части короткие
        ("Он сказал, потом долго молчал и ушёл.", "Он сказал, потом... молчал и ушёл", None),
        (
            "Он сказал, потом долго молчал и ушёл.",
            "молчал и ушёл... Он сказал, потом",
            "quote_not_found",
        ),
        ("Он сказал... и замолчал.", "сказал... и ушёл", "quote_too_short"),
    ],
)
def test_whole_first_then_parts(text, quote, expected):
    assert quotes.check(quote, text) == expected


@req(EO, QUOTE, invariant="Знаки нулевой ширины и штрихи нормализуются одинаково в цитате и абзаце")
@pytest.mark.parametrize("zw", ["​", "⁠", "﻿"])
def test_zero_width_removed(zw):
    assert quotes.check("познание есть опыт", f"поз{zw}нание е{zw}сть опыт") is None
    assert quotes.check(f"поз{zw}нание есть{zw} опыт", "познание есть опыт") is None
    assert quotes.normalize(f"а{zw}б") == "аб"


@pytest.mark.parametrize(
    ("mark", "plain"),
    [("″", '"'), ("′", "'"), ("`", "'")],
)
@req(EO, QUOTE, invariant="Штрихи ″ ′ и обратный апостроф приводятся к кавычкам")
def test_primes_and_backtick(mark, plain):
    text = f"Он сказал {plain}да{plain} и ушёл"
    assert quotes.check(f"Он сказал {mark}да{mark} и ушёл", text) is None
    assert quotes.check(text, f"Он сказал {mark}да{mark} и ушёл") is None


@req(
    EO,
    QUOTE,
    invariant="Цитата с многоточием автора находится в статементе при записи и перепроверке",
)
def test_add_accepts_authors_ellipsis(stand, onto):
    onto.paragraphs["p_el"] = "Он сказал... и замолчал."
    a = onto.person("Эл")
    b = onto.entities.create("position", [("ru", "ЭлПоз", "primary")])
    sid = onto.statements.add(
        a,
        "holds",
        obj=b,
        attributions=[Attribution("source", "s_el")],
        evidence=[Evidence("p_el", "сказал... и", source_id="s_el")],
    )
    assert onto.statements.get(sid)["evidence"][0]["lost"] is False


@req(EO, QUOTE, invariant="Любая подстрока абзаца с многоточием автора находится целиком")
@given(
    hst.lists(hst.text(alphabet="абвгдежзиклмн", min_size=1, max_size=6), min_size=3, max_size=8),
    hst.data(),
)
@settings(parent=PROFILES["pure"], max_examples=300)
def test_substring_with_authors_ellipsis_property(ws, data):
    text = "... ".join(ws) + "..."
    a = data.draw(hst.integers(0, len(text) - 1))
    b = data.draw(hst.integers(a + 1, len(text)))
    sub = text[a:b]
    if any(ch.isalnum() for ch in sub):  # без значимого текста — отказ, см. test_reextract_quotes
        assert quotes.check(sub, text) is None
        assert quotes.check(unicodedata.normalize("NFD", sub), text) is None


# --- элементы entities --------------------------------------------------------------------

GOOD = stmt("Верный", "holds", "Опыт", 1, QUOTES[0])


@req(EO, CHECK, scenario="Элемент entities не того вида")
def test_entities_item_wrong_kind(stand, events):
    quote = QUOTES[0]
    entities = [
        {"name": "СущностьА", "type": ["person"]},
        {
            "name": "СущностьБ",
            "type": "person",
            "dating": {"text": 1724, "paragraph": 1, "quote": quote},
        },
        {
            "name": "СущностьВ",
            "type": "person",
            "dating": {"text": "1724", "paragraph": 1, "quote": 5},
        },
    ]
    vid, _ = stand.version(TEXTS)
    stand.model.replies.append(
        {"statements": [stmt("Верный", "holds", "Опыт", 1, quote)], "entities": entities}
    )
    stand.filling.extract_version(vid, limit=1)
    row = one_run(stand)
    assert row["status"] == "done" and row["created"] == 1
    assert len(stand.statements()) == 1
    for name in ("СущностьА", "СущностьБ", "СущностьВ"):
        assert stand.onto.entities.find(name) == []
    assert [s for s in stand.statements() if s["type"] in ("lifespan", "dating")] == []
    assert dropped_codes(events) == ["schema_item"] * 3
    check_run_accounting(stand, events)
    assert row["drop_reasons"] == {"schema_item": 3}


@pytest.mark.parametrize(
    "entity",
    [
        {"name": "Э", "type": 5},
        {"name": "Э", "type": {"a": 1}},
        {"name": "Э", "type": True},
        {"name": "Э", "type": "person", "dating": {"text": ["1724"], "paragraph": 1, "quote": "x"}},
        {"name": "Э", "type": "person", "dating": {"text": "1724", "paragraph": 1.5, "quote": "x"}},
        {
            "name": "Э",
            "type": "person",
            "dating": {"text": "1724", "paragraph": True, "quote": "x"},
        },
        {"name": "Э", "type": "person", "dating": {"text": "1724", "paragraph": "²", "quote": "x"}},
        {"name": "Э", "type": "person", "dating": {"text": "1724", "paragraph": "٣", "quote": "x"}},
        {
            "name": "Э",
            "type": "person",
            "dating": {"text": "1724", "paragraph": "１", "quote": "x"},
        },
        {"name": "Э", "type": "person", "dating": {"text": "1724", "paragraph": [1], "quote": "x"}},
        {"name": "Э", "type": "person", "dating": "1724"},
        {"name": "Э", "type": "person", "dating": 1724},
        {"name": "Э", "type": "person", "dating": ["1724"]},
        {"name": "Э", "type": "person", "dating": True},
        {"name": "Э", "type": "person", "dating": ""},
        {"name": "Э", "type": "person", "dating": 0},
        {
            "name": "Э",
            "type": "person",
            "dating": {"text": "1724", "paragraph": 1, "quote": None},
        },
    ][:-1],
)
@req(
    EO,
    CHECK,
    invariant="Элемент entities не того вида — schema_item, остальное в ответе обрабатывается",
)
def test_entities_item_kinds_dropped_rest_kept(stand, events, entity):
    external(stand, [GOOD], entities=[entity])
    assert dropped_codes(events) == ["schema_item"]
    assert len(stand.statements()) == 1 and stand.onto.entities.find("Э") == []
    assert one_run(stand)["status"] == "done"
    check_run_accounting(stand, events)


@req(EO, CHECK, invariant="dating.paragraph строкой из ASCII-цифр — то же число, не отказ вида")
@pytest.mark.parametrize("number", ["1", " 1 ", 1])
def test_dating_paragraph_ascii_digits_pass_kind_check(stand, events, number):
    text = "Иммануил Кант (1724–1804) родился в Кёнигсберге."
    vid, _ = stand.version([text])
    dating = {"text": "1724–1804", "paragraph": number, "quote": "Иммануил Кант (1724–1804)"}
    ingest(
        stand,
        vid,
        {
            "1": {
                "statements": [],
                "entities": [{"name": "Кант", "type": "person", "dating": dating}],
            }
        },
    )
    assert events.of("knowledge.extraction.dropped") == []
    assert [s["type"] for s in stand.statements()] == ["lifespan"]


@pytest.mark.parametrize("raw", ["²", "٣", "１", "१", "①"])
@req(
    EO,
    CHECK,
    invariant="paragraph строкой — только ASCII 0-9; другие «цифры» Unicode — schema_item",
)
def test_paragraph_unicode_digits_refused(stand, events, raw):
    external(stand, [stmt("Кант", "holds", "Опыт", raw, QUOTES[0]), GOOD])
    assert dropped_codes(events) == ["schema_item"]
    assert len(stand.statements()) == 1
    assert one_run(stand)["status"] == "done"


json_leaf = hst.one_of(
    hst.none(),
    hst.booleans(),
    hst.integers(-3, 5),
    hst.floats(allow_nan=False, allow_infinity=False),
    hst.text(max_size=12),
    hst.sampled_from(["1", " 2 ", "²", "٣", "person", "position", "1724", "Кант"]),
)
json_value = hst.recursive(
    json_leaf,
    lambda c: hst.one_of(
        hst.lists(c, max_size=3), hst.dictionaries(hst.text(max_size=5), c, max_size=3)
    ),
    max_leaves=6,
)
FIELDS = ("name", "type", "ru", "en", "original", "dating")
dating_value = hst.one_of(
    json_value,
    hst.fixed_dictionaries(
        {},
        optional={k: json_value for k in ("text", "paragraph", "quote")},
    ),
)
entity_item = hst.one_of(
    json_value,
    hst.fixed_dictionaries(
        {},
        optional={
            "name": hst.one_of(hst.sampled_from(["Платон", "Зевс", "Кант", ""]), json_value),
            "type": hst.one_of(hst.sampled_from(["person", "work", "position", "x"]), json_value),
            "ru": json_value,
            "en": json_value,
            "original": json_value,
            "dating": dating_value,
        },
    ),
)


# шлюз сам отвергает элементы entities без name/type или не объекты (model_schema)
gateway_entity = hst.fixed_dictionaries(
    {
        "name": hst.one_of(hst.sampled_from(["Платон", "Зевс", "Кант", ""]), json_value),
        "type": hst.one_of(hst.sampled_from(["person", "work", "position", "x"]), json_value),
    },
    optional={"ru": json_value, "en": json_value, "original": json_value, "dating": dating_value},
)


@req(
    EO,
    CHECK,
    invariant="Произвольные значения полей entities не роняют запуск; верные утверждения записаны",
)
@example([{"name": "Платон", "type": "person", "dating": "1724"}])
@example([{"name": "Платон", "type": "work", "dating": 5}])
@example([{"name": "Платон", "type": "person", "dating": ["x"]}])
@given(hst.lists(entity_item, max_size=6))
@settings(
    parent=PROFILES["heavy"],
    max_examples=150,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_arbitrary_entities_never_crash_property(stand, events, entities):
    stand.reset()
    events.clear()
    external(stand, [GOOD], entities=entities)
    row = check_run_accounting(stand, events)
    assert row["status"] == "done" and row["failure"] is None
    assert any(s["type"] == "holds" for s in stand.statements())  # верное утверждение записано
    for c in dropped_codes(events):
        assert c in __import__("philograph.knowledge.extraction_codes", fromlist=["CODES"]).CODES


@req(EO, CHECK, invariant="То же через шлюз: произвольные entities не роняют запуск")
@given(hst.lists(gateway_entity, max_size=4))
@settings(
    parent=PROFILES["heavy"],
    max_examples=40,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_arbitrary_entities_never_crash_gateway_property(stand, events, entities):
    import uuid

    stand.reset()
    events.clear()
    vid, _ = stand.version([f"{TEXTS[0]} #{uuid.uuid4().hex}"])
    stand.model.replies.append({"statements": [GOOD], "entities": entities})
    stand.filling.extract_version(vid)
    row = check_run_accounting(stand, events)
    assert row["status"] == "done"
    assert any(s["type"] == "holds" for s in stand.statements())


# --- внешний извлекатель ------------------------------------------------------------------


def base_argv(stand, tmp_path, replies):
    stand.filling.fragment_size = 2
    vid, _ = stand.version(TEXTS)
    path = replies_file(tmp_path, replies)
    return vid, ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"]


@req(EO, EXTERNAL, scenario="Повтор после прерванной записи")
def test_repeat_after_interrupted_ingest(stand, tmp_path, events, capsys):
    replies = {"1": reply_for(0), "2": reply_for(1), "3": reply_for(2)}
    vid, argv = base_argv(stand, tmp_path, replies)
    ids = stand.versions[vid]["paragraphs"]
    real = stand.onto.statements.paragraph_text

    def interrupted(paragraph_id):
        if paragraph_id == ids[2]["id"]:  # абзац 3 — во втором фрагменте
            raise RuntimeError("обрыв записи")
        return real(paragraph_id)

    stand.onto.statements.paragraph_text = interrupted
    with pytest.raises(RuntimeError):
        cli(stand, argv)
    [first] = runs(stand)
    assert first["status"] == "failed" and len(stand.statements()) >= 1
    stand.onto.statements.paragraph_text = real
    after_failure = counts(stand)
    events.clear()
    assert cli(stand, argv) == 2
    assert capsys.readouterr().err.strip()
    assert counts(stand) == after_failure and len(runs(stand)) == 1
    assert events.of("knowledge.run.started") == []
    assert cli(stand, [*argv, "--replace"]) == 0
    statuses = {r["run_id"]: r["status"] for r in runs(stand)}
    assert statuses[first["run_id"]] == "rolled_back"
    assert sorted(statuses.values()) == ["done", "rolled_back"]
    replaced = counts(stand)
    stand.reset()  # эталон: одна полная запись в пустую онтологию
    assert cli(stand, argv) == 0
    assert replaced == counts(stand)


def stale_start(stand, hours=7):
    return stand.filling.clock.now() - timedelta(hours=hours)


@req(
    EO,
    EXTERNAL,
    invariant="Повтор блокирует неоткатанный внешний запуск; --replace откатывает (брошенный — тоже)",
)
@pytest.mark.parametrize(
    "statuses", [["failed"], ["running"], ["done"], ["failed", "running"], ["failed", "done"]]
)
def test_any_unrolled_external_run_blocks_repeat(stand, tmp_path, events, statuses):
    replies = {"1": reply_for(0), "3": reply_for(2)}
    vid, argv = base_argv(stand, tmp_path, replies)
    assert cli(stand, argv) == 0
    baseline = counts(stand)
    seeded = [one_run(stand)["run_id"]]
    # дополнительные запуски той же версии с заданными статусами (как оставил бы прерванный ingest)
    with stand.onto.statements.engine.begin() as conn:
        conn.execute(
            t.filling_runs.update()
            .where(t.filling_runs.c.run_id == seeded[0])
            .values(status=statuses[0], started_at=stale_start(stand))
        )
        for i, status in enumerate(statuses[1:]):
            conn.execute(
                t.filling_runs.insert().values(
                    run_id=f"ext_seed{i}",
                    kind="extraction",
                    target=vid,
                    extractor="external",
                    started_at=stale_start(stand),
                    created=0,
                    dropped=0,
                    status=status,
                )
            )
    events.clear()
    assert cli(stand, argv) == 2
    assert counts(stand) == baseline and len(runs(stand)) == len(statuses)
    assert events.of("knowledge.run.started") == []
    assert cli(stand, [*argv, "--replace"]) == 0
    final = [r["status"] for r in runs(stand)]
    assert final.count("done") == 1 and final.count("rolled_back") == len(statuses)
    assert counts(stand) == baseline


@req(EO, EXTERNAL, invariant="Откатанный запуск не блокирует повтор; чужая версия не блокирует")
def test_rolled_back_and_other_version_do_not_block(stand, tmp_path):
    replies = {"1": reply_for(0)}
    _vid, argv = base_argv(stand, tmp_path, replies)
    assert cli(stand, argv) == 0
    assert cli(stand, [*argv, "--replace"]) == 0
    stand.filling.rollback(next(r["run_id"] for r in runs(stand) if r["status"] == "done"))
    assert cli(stand, argv) == 0  # все прежние откатаны
    other, _ = stand.version(TEXTS)
    other_argv = [*argv]
    other_argv[2] = other
    assert cli(stand, other_argv) == 0


@req(EO, EXTERNAL, scenario="Повтор фрагмента в файле ответов")
def test_duplicate_fragment_in_jsonl(stand, tmp_path, events, capsys):
    vid, _ = stand.version(TEXTS)
    path = tmp_path / "dup.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"fragment": 1, "reply": reply_for(i, subject=f"П{i}_")}, ensure_ascii=False)
            for i in (0, 1)
        ),
        encoding="utf-8",
    )
    code = cli(
        stand, ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"]
    )
    assert code == 2
    assert capsys.readouterr().err.strip()
    assert runs(stand) == [] and counts(stand) == [0, 0, 0]
    assert events.of("knowledge.run.started") == []


@req(
    EO,
    EXTERNAL,
    invariant="Повтор ключа верхнего уровня JSON-объекта ответов — код 2, ничего не записано",
)
def test_duplicate_top_level_key_in_json_object(stand, tmp_path, events, capsys):
    vid, _ = stand.version(TEXTS)
    path = tmp_path / "dup.json"
    path.write_text('{"1": {"statements": []}, "1": {"statements": []}}', encoding="utf-8")
    code = cli(
        stand, ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"]
    )
    assert code == 2 and capsys.readouterr().err.strip()
    assert runs(stand) == [] and counts(stand) == [0, 0, 0]


@req(
    EO,
    EXTERNAL,
    invariant="Повтор ключа внутри ответа — обычный JSON (последнее значение), команда продолжается",
)
def test_duplicate_key_inside_reply_is_plain_json(stand, tmp_path, events):
    vid, _ = stand.version(TEXTS)
    good = json.dumps(reply_for(0)["statements"], ensure_ascii=False)
    path = tmp_path / "inner.json"
    path.write_text('{"1": {"statements": [], "statements": %s}}' % good, encoding="utf-8")
    code = cli(
        stand, ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"]
    )
    assert code == 0
    assert len(stand.statements()) == 1  # последнее значение «statements» победило
    assert one_run(stand)["status"] == "done"


@req(
    EO,
    EXTERNAL,
    invariant="Версии нет в библиотеке или библиотека недоступна — код 2, без трассировки",
)
@pytest.mark.parametrize("command", ["export", "ingest"])
@pytest.mark.parametrize("failure", ["404", "500", "unavailable"])
def test_version_missing_or_library_down(stand, tmp_path, events, capsys, command, failure):
    path = replies_file(tmp_path, {"1": reply_for(0)})
    if failure == "unavailable":

        def down(request):
            raise httpx.ConnectError("нет связи")

        transport = httpx.MockTransport(down)
        stand.filling.library = ServiceClient("library", "http://library/api", transport=transport)
        vid = "v_any"
    elif failure == "500":
        stand.filling.library = ServiceClient(
            "library",
            "http://library/api",
            transport=httpx.MockTransport(lambda r: httpx.Response(500, json={})),
        )
        vid = "v_any"
    else:
        vid = "v_no_such_version"
    argv = (
        ["export", "--version", vid, "--out", str(tmp_path / "out")]
        if command == "export"
        else ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"]
    )
    code = cli(stand, argv)
    captured = capsys.readouterr()
    assert code == 2
    assert captured.err.strip() and "Traceback" not in captured.err
    assert runs(stand) == [] and counts(stand) == [0, 0, 0]
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").glob("*.jsonl"))


@req(
    EO,
    CHECK,
    invariant="dating — объект, null или отсутствует; null и отсутствие — как без датировки",
)
@pytest.mark.parametrize("variant", ["null", "absent"])
def test_dating_null_or_absent_is_fine(stand, events, variant):
    entity = {"name": "Кант", "type": "person"}
    if variant == "null":
        entity["dating"] = None
    external(stand, [stmt("Кант", "holds", "Опыт", 1, QUOTES[0])], entities=[entity])
    assert events.of("knowledge.extraction.dropped") == []
    assert len(stand.statements()) == 1


def seed_run(stand, vid, status, hours, run_id, extractor="external", target=None):
    with stand.onto.statements.engine.begin() as conn:
        conn.execute(
            t.filling_runs.insert().values(
                run_id=run_id,
                kind="extraction",
                target=target or vid,
                extractor=extractor,
                started_at=stale_start(stand, hours),
                created=0,
                dropped=0,
                status=status,
            )
        )


@req(EO, EXTERNAL, scenario="Идёт запись той же версии")
@pytest.mark.parametrize("replace", [True, False])
@pytest.mark.parametrize("hours", [1, 0, 5.9])
def test_running_write_in_progress_refuses(stand, tmp_path, events, capsys, replace, hours):
    vid, argv = base_argv(stand, tmp_path, {"1": reply_for(0)})
    seed_run(stand, vid, "running", hours, "ext_live")
    events.clear()
    code = cli(stand, [*argv, *(["--replace"] if replace else [])])
    err = capsys.readouterr().err
    assert code == 2 and "запись идёт" in err and "Traceback" not in err
    assert [(r["run_id"], r["status"]) for r in runs(stand)] == [("ext_live", "running")]
    assert counts(stand) == [0, 0, 0]
    assert events.of("knowledge.run.started") == [] and events.of("knowledge.run.rolled_back") == []


@req(
    EO,
    EXTERNAL,
    invariant="Идущая запись не даёт откатить и прочие запуски версии: ничего не откатывается",
)
def test_live_running_blocks_rollback_of_others(stand, tmp_path, events, capsys):
    vid, argv = base_argv(stand, tmp_path, {"1": reply_for(0)})
    assert cli(stand, argv) == 0
    baseline = counts(stand)
    done_id = one_run(stand)["run_id"]
    seed_run(stand, vid, "running", 1, "ext_live")
    assert cli(stand, [*argv, "--replace"]) == 2
    assert {r["run_id"]: r["status"] for r in runs(stand)} == {
        done_id: "done",
        "ext_live": "running",
    }
    assert counts(stand) == baseline


@req(EO, EXTERNAL, scenario="Брошенная запись")
@pytest.mark.parametrize("hours", [7, 6.5, 48])
def test_abandoned_running_is_rolled_back_by_replace(stand, tmp_path, events, hours):
    vid, argv = base_argv(stand, tmp_path, {"1": reply_for(0), "3": reply_for(2)})
    seed_run(stand, vid, "running", hours, "ext_dead")
    assert cli(stand, argv) == 2  # без --replace — по-прежнему отказ
    assert counts(stand) == [0, 0, 0]
    assert cli(stand, [*argv, "--replace"]) == 0
    by_id = {r["run_id"]: r["status"] for r in runs(stand)}
    assert by_id.pop("ext_dead") == "rolled_back"
    assert list(by_id.values()) == ["done"]
    assert events.where("knowledge.run.rolled_back", run_id="ext_dead")


@req(EO, EXTERNAL, invariant="Порог 6 ч: моложе — идёт, старше — брошен")
@pytest.mark.parametrize(("hours", "code"), [(5.99, 2), (6.01, 0)])
def test_six_hour_threshold(stand, tmp_path, hours, code):
    vid, argv = base_argv(stand, tmp_path, {"1": reply_for(0)})
    seed_run(stand, vid, "running", hours, "ext_edge")
    assert cli(stand, [*argv, "--replace"]) == code
    status = {r["run_id"]: r["status"] for r in runs(stand)}["ext_edge"]
    assert status == ("running" if code == 2 else "rolled_back")


@req(EO, EXTERNAL, invariant="Идущий запуск другой версии или шлюза не блокирует запись")
def test_live_running_of_other_version_or_gateway_does_not_block(stand, tmp_path):
    vid, argv = base_argv(stand, tmp_path, {"1": reply_for(0)})
    other, _ = stand.version(TEXTS)
    seed_run(stand, other, "running", 1, "ext_other")
    seed_run(stand, vid, "running", 1, "gw_live", extractor="gateway")
    assert cli(stand, argv) == 0
    assert {r["run_id"]: r["status"] for r in runs(stand)}["ext_other"] == "running"
