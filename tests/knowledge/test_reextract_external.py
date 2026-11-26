"""ontology-extraction (reextract-with-claude): «Внешний извлекатель» и «Отчёт о запусках
извлечения».

По дельте ``specs/ontology-extraction``. Команда запускается как пользователь: через
``external_extraction.main(argv, service=…)`` на стенде (библиотека — поддельный транспорт,
база — SQLite теста), вывод — файл задания, строка ``filling_runs``, утверждения, код выхода,
stdout/stderr; журнал — ``knowledge.extraction.exported/fragment/dropped/skipped/report`` и
``knowledge.run.*``.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as hst

from philograph.knowledge import external_extraction as ext
from philograph.knowledge import schema as t
from philograph.prompts import PROMPTS

from ..conftest import PROFILES
from .extraction_stand import Stand
from .reextract_common import (
    FRAGMENT,
    assert_event_keys,
    check_run_accounting,
    dropped_codes,
    no_context,
    one_run,
    runs,
    table_count,
)
from .reextract_common import st as stmt
from .test_reextract_items import FAULTS, PARAGRAPHS

req = pytest.mark.req
EO = "ontology-extraction"
EXTERNAL = "Внешний извлекатель"
REPORT = "Отчёт о запусках извлечения"

TEXTS = [
    "Кант писал, что всякое знание начинается с опыта.",
    "Юм считал причинность привычкой ума.",
    "Локк сравнивал душу с чистой доской.",
    "Беркли отрицал существование материи.",
    "Рид отвечал Юму здравым смыслом.",
]
QUOTES = [
    "всякое знание начинается с опыта",
    "причинность привычкой ума",
    "душу с чистой доской",
    "отрицал существование материи",
    "отвечал Юму здравым смыслом",
]
MODEL = "claude-opus-5-5"
ARGS = ["--model", MODEL, "--input-tokens", "1000000", "--output-tokens", "100000"]


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock, fragment_size=2)


def service(stand) -> ext.Service:
    return ext.Service(
        stand.filling, stand.onto.statements.engine, ext._Texts(stand.filling.library)
    )


def cli(stand, argv, capsys=None):
    return ext.main(argv, env={}, service=service(stand))


def reply_for(n: int, k: int = 1, subject: str = "Автор") -> dict:
    """Ответ с утверждением по абзацу ``k`` фрагмента, цитата — из абзаца ``n`` (с 0)."""
    return {
        "statements": [stmt(f"{subject}{n}", "holds", f"Позиция {n}", k, QUOTES[n])],
    }


def replies_file(tmp_path, replies: dict, jsonl: bool = False):
    path = tmp_path / ("replies.jsonl" if jsonl else "replies.json")
    if jsonl:
        path.write_text(
            "\n".join(
                json.dumps({"fragment": int(k), "reply": v}, ensure_ascii=False)
                for k, v in replies.items()
            ),
            encoding="utf-8",
        )
    else:
        path.write_text(json.dumps(replies, ensure_ascii=False), encoding="utf-8")
    return path


def counts(stand):
    return [table_count(stand, tb) for tb in (t.statements, t.evidence, t.attributions)]


# --- выгрузка ----------------------------------------------------------------------------


@req(EO, EXTERNAL, scenario="Выгрузка задания")
def test_export_task(stand, tmp_path, events, capsys):
    vid, ids = stand.version(TEXTS)
    assert cli(stand, ["export", "--version", vid, "--out", str(tmp_path)]) == 0
    path = tmp_path / f"{vid}.jsonl"
    assert capsys.readouterr().out.strip() == str(path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    task, *fragments = rows
    assert len(fragments) == 4
    assert task["kind"] == "task" and task["fragments"] == 4
    data = stand.filling.version(vid)
    assert (task["version_id"], task["source_id"]) == (vid, data["source_id"])
    assert task["source_title"] == "Учебник" and task["template"] == "ontology.extract"
    assert task["instructions"] == next(
        p.instructions for p in PROMPTS if p.name == "ontology.extract"
    )
    assert "holds" in task["relations"] and "person" in task["entity_types"]
    second = fragments[1]
    assert second["kind"] == "fragment" and second["fragment"] == 2
    assert second["paragraph_ids"] == ids[1:3]  # абзацы 2 и 3
    assert second["passages"].startswith(f"[1] {TEXTS[1]}")
    assert second["passages"] == f"[1] {TEXTS[1]}\n\n[2] {TEXTS[2]}"
    assert {"language", "section"} <= set(second)
    assert [f["fragment"] for f in fragments] == [1, 2, 3, 4]
    assert [f["paragraph_ids"] for f in fragments] == [ids[0:2], ids[1:3], ids[2:4], ids[3:5]]
    [exported] = events.of("knowledge.extraction.exported")
    assert no_context(exported.fields) == {"version_id", "fragments"}
    assert (exported["version_id"], exported["fragments"]) == (vid, 4)


@req(EO, EXTERNAL, scenario="Выгрузка задания")
def test_export_default_dir_is_cwd(stand, tmp_path, monkeypatch):
    vid, _ = stand.version(TEXTS)
    monkeypatch.chdir(tmp_path)
    assert cli(stand, ["export", "--version", vid]) == 0
    assert (tmp_path / f"{vid}.jsonl").exists()


@req(EO, EXTERNAL, invariant="Источник без разрешения на внешнюю обработку не выгружается: код 3")
def test_export_forbidden_exit_3(stand, tmp_path, events, capsys):
    vid, _ = stand.version(TEXTS)
    stand.versions[vid]["permissions"]["external_processing"] = False
    stand.versions[vid]["external_processing"] = False
    out = tmp_path / "out"
    assert cli(stand, ["export", "--version", vid, "--out", str(out)]) == 3
    assert not list(out.glob("*.jsonl")) and not (out / f"{vid}.jsonl").exists()
    [skipped] = events.of("knowledge.extraction.skipped")
    assert skipped["reason"] == "external_processing_forbidden"
    assert skipped["source_id"] == stand.versions[vid]["source_id"]
    assert events.of("knowledge.extraction.exported") == []


@req(EO, EXTERNAL, invariant="Фрагменты ingest совпадают с фрагментами export той же версии")
@pytest.mark.parametrize("size", [1, 2, 3, 30])
def test_ingest_fragments_equal_export(stand, tmp_path, events, size):
    stand.filling.fragment_size = size
    vid, ids = stand.version(TEXTS)
    assert cli(stand, ["export", "--version", vid, "--out", str(tmp_path)]) == 0
    rows = [json.loads(x) for x in (tmp_path / f"{vid}.jsonl").read_text("utf-8").splitlines()]
    fragments = rows[1:]
    # на каждом фрагменте n и каждом абзаце k — утверждение с цитатой из абзаца k
    replies = {}
    for fragment in fragments:
        items = []
        for k, pid in enumerate(fragment["paragraph_ids"], start=1):
            n = ids.index(pid)
            items.append(
                stmt(f"Субъект{fragment['fragment']}_{k}", "holds", f"Позиция{n}", k, QUOTES[n])
            )
        replies[str(fragment["fragment"])] = {"statements": items}
    path = replies_file(tmp_path, replies)
    assert (
        cli(stand, ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"])
        == 0
    )
    assert events.of("knowledge.extraction.dropped") == []
    assert [e["paragraphs"] for e in events.of(FRAGMENT)] == [
        len(f["paragraph_ids"]) for f in fragments
    ]
    assert one_run(stand)["fragments"] == len(fragments) == rows[0]["fragments"]
    by_subject = {s["subject"]: s for s in stand.statements()}
    for fragment in fragments:
        for k, pid in enumerate(fragment["paragraph_ids"], start=1):
            entity = stand.onto.entities.find(f"Субъект{fragment['fragment']}_{k}")[0]["id"]
            [evidence] = by_subject[entity]["evidence"]
            assert evidence["paragraph_id"] == pid


@req(EO, EXTERNAL, invariant="Выгрузка одной версии детерминирована: те же строки при повторе")
def test_export_is_deterministic(stand, tmp_path):
    vid, _ = stand.version(TEXTS)
    cli(stand, ["export", "--version", vid, "--out", str(tmp_path / "a")])
    cli(stand, ["export", "--version", vid, "--out", str(tmp_path / "b")])
    assert (tmp_path / "a" / f"{vid}.jsonl").read_bytes() == (
        tmp_path / "b" / f"{vid}.jsonl"
    ).read_bytes()


# --- запись ответов ----------------------------------------------------------------------


@req(EO, EXTERNAL, scenario="Запись ответов Claude")
def test_ingest_claude_replies(stand, tmp_path, events, capsys):
    vid, _ = stand.version(TEXTS)
    path = replies_file(tmp_path, {"1": reply_for(0), "3": reply_for(2)})
    code = cli(
        stand,
        ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "120"],
    )
    assert code == 0
    row = one_run(stand)
    assert row["extractor"] == "external" and row["model"] == "claude-opus-5-5"
    assert row["kind"] == "extraction" and row["status"] == "done"
    assert row["fragments"] == 4 and row["duration_seconds"] == 120
    assert row["cost_usd"] == 6.0  # 4 + 2 по тарифу $4/$20 за 1M
    assert row["input_tokens"] == 1_000_000 and row["output_tokens"] == 100_000
    assert row["drop_reasons"]["reply_missing"] == 2
    assert row["source_id"] == stand.versions[vid]["source_id"] and row["target"] == vid
    assert row["created"] == 2 and row["dropped"] == 2
    statements = stand.statements()
    assert len(statements) == 2
    assert {s["provenance"]["model"] for s in statements} == {"claude-opus-5-5"}
    assert {s["provenance"]["run_id"] for s in statements} == {row["run_id"]}
    [finished] = events.of("knowledge.run.finished")
    assert (finished["run_id"], finished["created"], finished["dropped"]) == (row["run_id"], 2, 2)
    assert len(events.of(FRAGMENT)) == 2  # на каждый фрагмент с ответом
    assert dropped_codes(events) == ["reply_missing", "reply_missing"]
    summary = json.loads(capsys.readouterr().out)
    assert summary["model"] == MODEL and summary["cost_usd"] == 6.0
    check_run_accounting(stand, events)


@req(EO, EXTERNAL, scenario="Повторная запись")
def test_ingest_repeat(stand, tmp_path, events, capsys):
    vid, _ = stand.version(TEXTS)
    path = replies_file(tmp_path, {"1": reply_for(0), "3": reply_for(2)})
    argv = ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "120"]
    assert cli(stand, argv) == 0
    first = one_run(stand)
    before = counts(stand)
    capsys.readouterr()
    events.clear()
    assert cli(stand, argv) == 2
    captured = capsys.readouterr()
    assert captured.err.strip()  # сообщение
    assert counts(stand) == before and len(runs(stand)) == 1
    assert events.of("knowledge.run.started") == [] and events.of(FRAGMENT) == []
    assert cli(stand, [*argv, "--replace"]) == 0
    assert counts(stand) == before  # утверждения, подтверждения, атрибуции — те же
    statuses = {r["run_id"]: r["status"] for r in runs(stand)}
    assert statuses[first["run_id"]] == "rolled_back"
    assert sorted(statuses.values()) == ["done", "rolled_back"]
    assert events.where("knowledge.run.rolled_back", run_id=first["run_id"])
    # и третий раз с --replace: по-прежнему без удвоения
    assert cli(stand, [*argv, "--replace"]) == 0
    assert counts(stand) == before
    assert sorted(r["status"] for r in runs(stand)) == ["done", "rolled_back", "rolled_back"]


@req(EO, EXTERNAL, invariant="Повтор не удваивает ни утверждения, ни подтверждения, ни атрибуции")
@given(
    hst.lists(hst.integers(0, 4), min_size=1, max_size=5, unique=True),
    hst.integers(1, 3),
)
@settings(
    parent=PROFILES["heavy"],
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_replace_does_not_double_property(stand, tmp_path_factory, events, picks, repeats):
    stand.reset()
    events.clear()
    tmp_path = tmp_path_factory.mktemp("r")
    vid, _ = stand.version(TEXTS)
    replies = {str(n + 1): reply_for(n, subject=f"Ав{n}_") for n in picks if n < 4}
    if not replies:
        replies = {"1": reply_for(0)}
    path = replies_file(tmp_path, replies)
    argv = ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "3"]
    assert cli(stand, argv) == 0
    baseline = counts(stand)
    for _ in range(repeats):
        assert cli(stand, argv) == 2
        assert counts(stand) == baseline
        assert cli(stand, [*argv, "--replace"]) == 0
        assert counts(stand) == baseline
    assert [r["status"] for r in runs(stand)].count("done") == 1


@req(EO, EXTERNAL, invariant="--replace откатывает только внешние завершённые запуски этой версии")
def test_replace_leaves_other_runs_alone(stand, tmp_path, events):
    vid, _ = stand.version(TEXTS)
    other, _ = stand.version(TEXTS)
    stand.model.replies.extend([{"statements": [stmt("ГШ", "holds", "Поз ГШ", 1, QUOTES[0])]}] * 2)
    stand.filling.extract_version(vid)  # запуск шлюза той же версии
    gateway_run = one_run(stand)
    path = replies_file(tmp_path, {"1": reply_for(1)})
    argv = ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"]
    other_argv = [*argv]
    other_argv[2] = other
    assert cli(stand, argv) == 0 and cli(stand, other_argv) == 0
    assert cli(stand, [*argv, "--replace"]) == 0
    by_id = {r["run_id"]: r for r in runs(stand)}
    assert by_id[gateway_run["run_id"]]["status"] == "done"
    rolled = [r for r in by_id.values() if r["status"] == "rolled_back"]
    assert len(rolled) == 1 and rolled[0]["target"] == vid and rolled[0]["extractor"] == "external"
    live = [r for r in by_id.values() if r["status"] == "done" and r["extractor"] == "external"]
    assert sorted(r["target"] for r in live) == sorted([vid, other])


@req(
    EO,
    EXTERNAL,
    invariant="Без прежнего — запись; после failed без --replace — код 2",
)
def test_replace_without_previous_and_failed_previous(stand, tmp_path, events):
    vid, _ids = stand.version(TEXTS)
    path = replies_file(tmp_path, {"1": reply_for(0)})
    argv = ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"]
    assert cli(stand, [*argv, "--replace"]) == 0  # прежнего нет
    assert len(stand.statements()) == 1
    # прежний запуск неудачен: по новой формулировке повтор без --replace блокируется любым
    # неоткатанным внешним запуском (done/failed/running)
    row = one_run(stand)
    with stand.onto.statements.engine.begin() as conn:
        conn.execute(t.filling_runs.update().values(status="failed"))
    before = [table_count(stand, tb) for tb in (t.statements, t.evidence, t.attributions)]
    assert cli(stand, argv) == 2
    assert [r["status"] for r in runs(stand)] == ["failed"] and row["status"] == "done"
    assert [table_count(stand, tb) for tb in (t.statements, t.evidence, t.attributions)] == before
    assert cli(stand, [*argv, "--replace"]) == 0
    assert sorted(r["status"] for r in runs(stand)) == ["done", "rolled_back"]


@req(EO, EXTERNAL, invariant="Ответ с номером вне фрагментов игнорируется с событием reply_invalid")
@pytest.mark.parametrize("key", ["0", "5", "99", "-1", "abc", "", "1.0", "²"])
def test_reply_out_of_range_ignored(stand, tmp_path, events, key):
    vid, _ = stand.version(TEXTS)  # 4 фрагмента
    path = replies_file(tmp_path, {"1": reply_for(0), key: reply_for(1, subject="Чужой")})
    code = cli(
        stand, ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"]
    )
    assert code == 0
    assert sorted(dropped_codes(events)) == [
        "reply_invalid",
        "reply_missing",
        "reply_missing",
        "reply_missing",
    ]
    assert stand.onto.entities.find("Чужой1") == []
    assert len(stand.statements()) == 1
    row = check_run_accounting(stand, events)
    assert row["drop_reasons"] == {"reply_invalid": 1, "reply_missing": 3}
    assert row["status"] == "done"


@req(EO, EXTERNAL, invariant="Фрагмент без ответа — ровно одна отбраковка reply_missing")
@pytest.mark.parametrize("answered", [[], [1], [2, 4], [1, 2, 3, 4]])
def test_missing_reply_one_drop_each(stand, tmp_path, events, answered):
    vid, _ = stand.version(TEXTS)
    path = replies_file(tmp_path, {str(n): {"statements": []} for n in answered})
    cli(stand, ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"])
    assert dropped_codes(events).count("reply_missing") == 4 - len(answered)
    assert len(events.of(FRAGMENT)) == len(answered)
    row = check_run_accounting(stand, events)
    assert row["fragments"] == 4


@req(EO, EXTERNAL, invariant="Файл ответов: JSON-объект или JSONL — одинаковый результат")
def test_replies_json_and_jsonl_equal(stand, tmp_path, events):
    vid, _ = stand.version(TEXTS)
    replies = {"1": reply_for(0), "2": reply_for(1), "4": {"statements": [{"x": 1}]}}
    results = []
    for jsonl in (False, True):
        stand.reset()
        events.clear()
        path = replies_file(tmp_path, replies, jsonl=jsonl)
        argv = ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"]
        assert cli(stand, argv) == 0
        row = one_run(stand)
        results.append(
            (
                row["created"],
                row["dropped"],
                row["drop_reasons"],
                sorted(dropped_codes(events)),
                sorted(s["type"] for s in stand.statements()),
            )
        )
    assert results[0] == results[1]
    assert results[0][2] == {"reply_missing": 1, "schema_item": 1}


@req(
    EO,
    EXTERNAL,
    invariant="Тот же путь проверки: одинаковый ответ — одинаковый результат у шлюза и ingest",
)
@given(
    hst.lists(
        hst.one_of(hst.just("good"), hst.sampled_from([0, 1, 2, 3, 4, 5, 7])),
        min_size=1,
        max_size=8,
    )
)
@settings(
    parent=PROFILES["heavy"],
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_gateway_and_ingest_agree_property(stand, tmp_path_factory, events, plan):
    items = []
    for i, step in enumerate(plan):
        if step == "good":
            n = i % 8
            items.append(stmt(f"Мыслитель{i}", "holds", f"Тезис{i}", n + 1, f"утверждал тезис {n}"))
        else:
            items.append(FAULTS[step][0](i))
    reply = {"statements": items}
    outcomes = []
    for path in ("gateway", "ingest"):
        stand.reset()
        events.clear()
        stand.filling.fragment_size = 8
        vid, _ = stand.version([f"{p} #{uuid.uuid4().hex}" for p in PARAGRAPHS])  # без кэша шлюза
        if path == "gateway":
            stand.model.replies.append(reply)
            stand.filling.extract_version(vid, limit=1)
        else:
            tmp = tmp_path_factory.mktemp("g")
            argv = ["ingest", "--version", vid, "--replies", str(replies_file(tmp, {"1": reply}))]
            assert cli(stand, [*argv, *ARGS, "--duration", "1"]) == 0
        row = one_run(stand)
        outcomes.append(
            (
                row["created"],
                row["dropped"],
                row["drop_reasons"],
                sorted(dropped_codes(events)),
                sorted(
                    (
                        s["type"],
                        tuple(sorted((a["who_kind"], a["stance"]) for a in s["attributions"])),
                        tuple(e["quote"] for e in s["evidence"]),
                    )
                    for s in stand.statements()
                ),
                sorted((e["created"], e["dropped"], e["paragraphs"]) for e in events.of(FRAGMENT)),
            )
        )
    assert outcomes[0] == outcomes[1]


# --- тариф и стоимость -------------------------------------------------------------------


def run_cli(stand, tmp_path, extra, model=MODEL, replies=None):
    vid, _ = stand.version(TEXTS)
    path = replies_file(tmp_path, replies or {"1": reply_for(0)})
    argv = ["ingest", "--version", vid, "--replies", str(path), "--model", model, "--duration", "1"]
    return cli(stand, argv + extra)


@pytest.mark.parametrize(
    ("extra", "cost"),
    [
        (["--input-tokens", "1000000", "--output-tokens", "100000"], 6.0),
        (["--input-tokens", "0", "--output-tokens", "0"], 0.0),
        (["--input-tokens", "500000", "--output-tokens", "0"], 2.0),
        (["--input-tokens", "0", "--output-tokens", "50000"], 1.0),
        (
            [
                "--input-tokens",
                "1000000",
                "--output-tokens",
                "100000",
                "--cache-read-tokens",
                "1000000",
            ],
            6.2,
        ),
        (
            [
                "--input-tokens",
                "10",
                "--output-tokens",
                "10",
                "--price-in",
                "1",
                "--price-out",
                "2",
            ],
            0.00003,
        ),
        (["--input-tokens", "1000000", "--output-tokens", "1000000", "--price-in", "1"], 21.0),
        (["--input-tokens", "1000000", "--output-tokens", "1000000", "--price-out", "1"], 5.0),
        (
            [
                "--input-tokens",
                "1000000",
                "--output-tokens",
                "1000000",
                "--cache-read-tokens",
                "1000000",
                "--price-in",
                "1",
                "--price-out",
                "2",
                "--price-cache-read",
                "0.5",
            ],
            3.5,
        ),
    ],
)
@req(
    EO,
    EXTERNAL,
    invariant="cost_usd = (in·price_in + out·price_out + cache·price_cache_read) / 10⁶",
)
def test_cost_formula(stand, tmp_path, extra, cost):
    assert run_cli(stand, tmp_path, extra) == 0
    assert one_run(stand)["cost_usd"] == pytest.approx(cost, abs=1e-9)


@pytest.mark.parametrize(
    "extra",
    [
        [],  # нет цен
        ["--price-in", "1"],  # только одна цена
        ["--price-out", "1"],
        ["--price-cache-read", "1"],
    ],
)
@req(EO, EXTERNAL, invariant="Модель без тарифа и без цен в аргументах — отказ (код 2) до записи")
def test_unknown_model_without_prices_refused_before_writing(
    stand, tmp_path, events, capsys, extra
):
    code = run_cli(
        stand,
        tmp_path,
        ["--input-tokens", "1", "--output-tokens", "1", *extra],
        model="some-model-x",
    )
    assert code == 2
    assert capsys.readouterr().err.strip()
    assert runs(stand) == [] and stand.statements() == []
    assert events.of("knowledge.run.started") == []
    assert counts(stand) == [0, 0, 0]


@req(EO, EXTERNAL, invariant="Неизвестная модель с обеими ценами в аргументах — запись по ним")
def test_unknown_model_with_prices_ok(stand, tmp_path):
    code = run_cli(
        stand,
        tmp_path,
        [
            "--input-tokens",
            "2000000",
            "--output-tokens",
            "1000000",
            "--price-in",
            "0.5",
            "--price-out",
            "1.5",
        ],
        model="other-model-7",
    )
    assert code == 0
    row = one_run(stand)
    assert row["model"] == "other-model-7" and row["cost_usd"] == pytest.approx(2.5)
    assert row["extractor"] == "external"


@pytest.mark.parametrize("model", [MODEL, "other-model-7", "main", "strong", "vendor/x:1"])
@req(EO, EXTERNAL, invariant="model запуска — переданный идентификатор, не имя роли")
def test_model_is_passed_identifier(stand, tmp_path, model):
    run_cli(
        stand,
        tmp_path,
        ["--input-tokens", "1", "--output-tokens", "1", "--price-in", "1", "--price-out", "1"],
        model=model,
    )
    row = one_run(stand)
    assert row["model"] == model
    assert {s["provenance"]["model"] for s in stand.statements()} == {model}


@req(EO, EXTERNAL, invariant="После ingest ни один запуск не running: и при исключении при записи")
def test_ingest_never_leaves_running(stand, tmp_path, events):
    vid, _ = stand.version(TEXTS)

    def boom(_pid):
        raise RuntimeError("библиотека недоступна")

    stand.onto.statements.paragraph_text = boom
    path = replies_file(tmp_path, {"1": reply_for(0)})
    with pytest.raises(RuntimeError):
        cli(stand, ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"])
    [row] = runs(stand)
    assert row["status"] == "failed" and row["finished_at"] is not None
    assert row["failure"].startswith("RuntimeError")
    assert events.where("knowledge.run.failed", run_id=row["run_id"], error_kind="RuntimeError")


@req(EO, EXTERNAL, invariant="Запрет внешней обработки: ingest — код 3, ничего не пишется")
def test_ingest_forbidden_exit_3(stand, tmp_path, events):
    vid, _ = stand.version(TEXTS)
    stand.versions[vid]["permissions"]["external_processing"] = False
    path = replies_file(tmp_path, {"1": reply_for(0)})
    code = cli(
        stand, ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"]
    )
    assert code == 3
    assert runs(stand) == [] and stand.statements() == []
    assert events.where("knowledge.extraction.skipped", reason="external_processing_forbidden")


@req(EO, EXTERNAL, invariant="События отбраковки внешнего пути — те же поля и коды из перечня")
def test_external_drop_events(stand, tmp_path, events):
    vid, _ = stand.version(TEXTS)
    replies = {"1": {"statements": [stmt("Х", "holds", "Y", 1, "нет такой"), {"subject": "a"}]}}
    cli(
        stand,
        [
            "ingest",
            "--version",
            vid,
            "--replies",
            str(replies_file(tmp_path, replies)),
            *ARGS,
            "--duration",
            "1",
        ],
    )
    assert_event_keys(events)
    assert sorted(dropped_codes(events)) == [
        "quote_not_found",
        "reply_missing",
        "reply_missing",
        "reply_missing",
        "schema_item",
    ]


# --- отчёт -------------------------------------------------------------------------------


def parse_table(text: str) -> tuple[list[str], list[list[str]]]:
    lines = [ln for ln in text.splitlines() if ln.startswith("|")]
    cells = [[c.strip() for c in ln.strip("|").split("|")] for ln in lines]
    return cells[0], cells[2:]  # шапка, пропуская строку разделителей


@req(EO, REPORT, scenario="Отчёт за день")
def test_report_for_a_day(stand, clock, tmp_path, events):
    today = clock.now().date()
    argv = ["--duration", "30", "--price-in", "4", "--price-out", "20"]
    # два завершённых внешних запуска
    v1, _ = stand.version(TEXTS)
    f1 = replies_file(
        tmp_path, {"1": reply_for(0), "2": {"statements": [stmt("Х", "holds", "Y", 1, "нет")]}}
    )
    assert (
        cli(
            stand,
            [
                "ingest",
                "--version",
                v1,
                "--replies",
                str(f1),
                "--model",
                MODEL,
                "--input-tokens",
                "1000",
                "--output-tokens",
                "100",
                *argv,
            ],
        )
        == 0
    )
    v2, _ = stand.version(TEXTS)
    f2 = replies_file(tmp_path, {"1": reply_for(2, subject="Другой")})
    assert (
        cli(
            stand,
            [
                "ingest",
                "--version",
                v2,
                "--replies",
                str(f2),
                "--model",
                MODEL,
                "--input-tokens",
                "2000",
                "--output-tokens",
                "300",
                *argv,
            ],
        )
        == 0
    )
    # третий запуск — откатан (повтор с --replace откатывает первый запуск v2)
    v3, _ = stand.version(TEXTS)
    f3 = replies_file(tmp_path, {"1": reply_for(3, subject="Третий")})
    third = [
        "ingest",
        "--version",
        v3,
        "--replies",
        str(f3),
        "--model",
        MODEL,
        "--input-tokens",
        "7000",
        "--output-tokens",
        "700",
        *argv,
    ]
    assert cli(stand, third) == 0
    replaced = [*third]
    replaced[replaced.index("7000")] = "8000"  # новый запуск с другими токенами
    assert cli(stand, [*replaced, "--replace"]) == 0  # прежний v3 откатан, новый записан
    rows = runs(stand)
    done = [r for r in rows if r["status"] == "done"]
    assert len(done) == 3 and [r["status"] for r in rows].count("rolled_back") == 1
    out = tmp_path / "out" / "report.md"
    events.clear()
    assert cli(stand, ["report", "--since", today.isoformat(), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    head, body = parse_table(text)
    assert len(body) == len(done) + 1  # строки запусков и «Итого»
    *runs_rows, total = body
    for name in (
        "Источник",
        "Модель",
        "Извлекатель",
        "Статус",
        "Время",
        "Фрагменты",
        "Токены вход",
        "Токены выход",
        "Стоимость",
        "Создано",
        "Отброшено",
        "Доля",
        "причин",
    ):
        assert any(name in h for h in head), name
    col = {
        name: next(i for i, h in enumerate(head) if name in h)
        for name in (
            "Модель",
            "Извлекатель",
            "Статус",
            "Фрагменты",
            "Токены вход",
            "Токены выход",
            "Стоимость",
            "Создано",
            "Отброшено",
            "Доля",
            "причин",
        )
    }
    assert [r[col["Модель"]] for r in runs_rows] == [MODEL] * 3
    assert [r[col["Извлекатель"]] for r in runs_rows] == ["external"] * 3
    assert [r[col["Статус"]] for r in runs_rows] == ["done"] * 3
    rolled = next(r for r in rows if r["status"] == "rolled_back")
    assert rolled["run_id"] not in text and "7000" not in "".join(
        r[col["Токены вход"]] for r in runs_rows
    )
    # источник: название и source_id
    for r in done:
        assert any(r["source_id"] in row[0] for row in runs_rows)
    assert all("Учебник" in row[0] for row in runs_rows)
    # итого — суммы по filling_runs
    assert "Итого" in total[0]
    assert int(total[col["Токены вход"]]) == sum(r["input_tokens"] for r in done)
    assert int(total[col["Токены выход"]]) == sum(r["output_tokens"] for r in done)
    assert float(total[col["Стоимость"]]) == pytest.approx(
        sum(r["cost_usd"] for r in done), abs=1e-4
    )
    assert int(total[col["Создано"]]) == sum(r["created"] for r in done)
    assert int(total[col["Отброшено"]]) == sum(r["dropped"] for r in done)
    assert int(total[col["Фрагменты"]]) == sum(r["fragments"] for r in done)
    # строка запуска: числа совпадают с базой
    first = next(r for r in done if r["target"] == v1)
    line = next(row for row in runs_rows if first["source_id"] in row[0])
    assert (
        int(line[col["Создано"]]) == first["created"]
        and int(line[col["Отброшено"]]) == first["dropped"]
    )
    assert line[col["Доля"]] == f"{first['dropped'] / (first['created'] + first['dropped']):.0%}"
    assert "reply_missing" in line[col["причин"]] and "quote_not_found" in line[col["причин"]]
    [reported] = events.of("knowledge.extraction.report")
    assert no_context(reported.fields) == {"runs", "out"}
    assert (reported["runs"], reported["out"]) == (3, str(out))


@req(EO, REPORT, invariant="В отчёт входят только запуски периода; откатанные и вне периода — нет")
def test_report_period_and_rollbacks(stand, clock, tmp_path, events):
    day0 = clock.now().date()
    ids = []
    for offset in (0, 1, 3):
        clock.set(
            clock.now().replace(year=day0.year, month=day0.month, day=day0.day)
            + timedelta(days=offset)
        )
        vid, _ = stand.version(TEXTS)
        path = replies_file(tmp_path, {"1": reply_for(0, subject=f"Д{offset}_")})
        cli(stand, ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"])
        ids.append(vid)
    all_runs = {r["target"]: r for r in runs(stand)}

    def listed(*argv):
        out = tmp_path / "r.md"
        assert cli(stand, ["report", *argv, "--out", str(out)]) == 0
        _, body = parse_table(out.read_text(encoding="utf-8"))
        return body[:-1], body[-1]

    rows, total = listed("--since", day0.isoformat())
    assert len(rows) == 3
    rows, total = listed("--since", (day0 + timedelta(days=1)).isoformat())
    assert len(rows) == 2
    rows, total = listed(
        "--since", day0.isoformat(), "--until", (day0 + timedelta(days=1)).isoformat()
    )
    assert len(rows) == 2 and all_runs[ids[2]]["source_id"] not in "".join(r[0] for r in rows)
    rows, total = listed("--since", (day0 + timedelta(days=10)).isoformat())
    assert rows == [] and "Итого" in total[0] and "0" in total[0 + 3]
    # откат исключает запуск из отчёта
    stand.filling.rollback(all_runs[ids[0]]["run_id"])
    rows, _ = listed("--since", day0.isoformat())
    assert len(rows) == 2 and all(all_runs[ids[0]]["source_id"] not in r[0] for r in rows)


@req(
    EO,
    REPORT,
    invariant="Отчёт: три частых кода с числом, доля dropped/(created+dropped), итого",
)
def test_report_top_codes_and_rates(stand, clock, tmp_path):
    vid, _ = stand.version(TEXTS)
    bad = [stmt("Х", "holds", "Y", 1, f"нет {i}") for i in range(4)]  # quote_not_found ×4
    bad += [stmt("Х", "holds", "Y", 99, "Кант") for _ in range(3)]  # paragraph_out_of_window ×3
    bad += [stmt("Х", "holds", "Y", 1, "Кант", stance="z") for _ in range(2)]  # stance_invalid ×2
    bad += ["не объект"]  # schema_item ×1
    good = reply_for(0)["statements"]
    path = replies_file(tmp_path, {"1": {"statements": good + bad}})
    cli(stand, ["ingest", "--version", vid, "--replies", str(path), *ARGS, "--duration", "1"])
    out = tmp_path / "r.md"
    cli(stand, ["report", "--since", clock.now().date().isoformat(), "--out", str(out)])
    head, body = parse_table(out.read_text(encoding="utf-8"))
    top = body[0][next(i for i, h in enumerate(head) if "причин" in h)]
    # создано 1, отброшено 10 + 3 «reply_missing»
    assert top.startswith("quote_not_found 4") and "paragraph_out_of_window 3" in top
    assert top.count(",") == 2  # три кода
    assert "stance_invalid 2" in top or "reply_missing 3" in top
    created, dropped = 1, 13
    share = body[0][next(i for i, h in enumerate(head) if "Доля" in h)]
    assert share == f"{dropped / (created + dropped):.0%}"
    assert body[-1][next(i for i, h in enumerate(head) if "Доля" in h)] == share
    assert date.fromisoformat(clock.now().date().isoformat())
