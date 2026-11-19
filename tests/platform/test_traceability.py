"""Юнит-тесты scripts/check_traceability.py: разбор сценариев, маркеров, журнала и junit.

Каждый тест собирает маленький репозиторий во временной папке: спецификацию, настройки
режимов и тестовые модули, и запускает проверку на нём.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import check_traceability as tr  # noqa: E402

req = pytest.mark.req
SR = "service-runtime"
TRACE = "Прослеживаемость требований тестами"

SPEC = """\
## Requirements

### Requirement: Запись

Сервис SHALL писать.

#### Scenario: Успех

- **THEN** записано

#### Scenario: Отказ

- **THEN** не записано

### Requirement: Чтение

Сервис SHALL читать.

#### Scenario: Чтение главы

- **THEN** прочитано
"""


def make_repo(tmp_path, monkeypatch, tests: dict[str, str], config: str = "enforce: [demo]\n"):
    spec = tmp_path / "openspec" / "specs" / "demo" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(SPEC, encoding="utf-8")
    (tmp_path / "openspec" / "traceability.yaml").write_text(config, encoding="utf-8")
    for name, body in tests.items():
        path = tmp_path / "tests" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
    (tmp_path / "src").mkdir()
    monkeypatch.setattr(tr, "ROOT", tmp_path)
    return tmp_path


FULL = textwrap.dedent(
    """\
    import pytest

    req = pytest.mark.req
    CAP = "demo"


    @req(CAP, "Запись", scenario="Успех")
    @req(CAP, "Запись", scenario="Отказ")
    def test_write(events):
        events.one("demo.written")


    @req(CAP, "Чтение", scenario="Чтение главы", invariant="только опубликованное")
    def test_read(caplog):
        assert caplog.records == []
"""
)


@req(SR, TRACE)
def test_summary_counts_requirements_scenarios_logs_and_invariants(tmp_path, monkeypatch, capsys):
    make_repo(tmp_path, monkeypatch, {"test_demo.py": FULL})
    assert tr.main() == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:4] == [
        "Требований с тестами: 2 из 2",
        "Сценариев с тестами: 3 из 3",
        "Требований с проверкой журнала: 2 из 2",
        "Нормативных тестов: 1",
    ]


@req(SR, TRACE)
def test_scenario_typo_is_an_error(tmp_path, monkeypatch, capsys):
    """Мутация: заголовок сценария с опечаткой проваливает проверку даже в режиме отчёта."""
    make_repo(tmp_path, monkeypatch, {"test_demo.py": FULL.replace('"Отказ"', '"Отказы"')})
    assert tr.main() == 1
    out = capsys.readouterr().out
    assert "в «Запись» нет сценария «Отказы» (tests/test_demo.py::test_write)" in out
    assert "Сценариев с тестами: 2 из 3" in out


@req(SR, TRACE)
def test_uncovered_scenario_fails_only_when_enforced(tmp_path, monkeypatch, capsys):
    body = FULL.replace('@req(CAP, "Запись", scenario="Отказ")\n', "")
    make_repo(tmp_path, monkeypatch, {"test_demo.py": body})
    assert tr.main(["--report"]) == 0
    out = capsys.readouterr().out
    assert "сценарии без теста (1):\n    - Запись / Отказ" in out

    (tmp_path / "openspec" / "traceability.yaml").write_text(
        "enforce: [demo]\nenforce_scenarios: [demo]\n", encoding="utf-8"
    )
    assert tr.main() == 1
    assert "demo: нет теста для сценария «Запись / Отказ»" in capsys.readouterr().out


@req(SR, TRACE)
def test_test_without_log_check_is_reported_and_nolog_accepted(tmp_path, monkeypatch, capsys):
    """Мутация: тест без обращения к журналу попадает в отчёт, с enforce_log — ошибка."""
    body = FULL.replace('events.one("demo.written")', "assert True")
    make_repo(tmp_path, monkeypatch, {"test_demo.py": body})
    assert tr.main(["--report"]) == 0
    out = capsys.readouterr().out
    assert "Требований с проверкой журнала: 1 из 2" in out
    assert "требования без проверки журнала и без nolog (1):\n    - Запись" in out

    (tmp_path / "openspec" / "traceability.yaml").write_text(
        "enforce: [demo]\nenforce_log: [demo]\n", encoding="utf-8"
    )
    assert tr.main() == 1
    assert "demo: нет теста с проверкой журнала для «Запись»" in capsys.readouterr().out

    test = tmp_path / "tests" / "test_demo.py"
    test.write_text(
        test.read_text(encoding="utf-8").replace(
            'scenario="Успех")', 'scenario="Успех", nolog="только вид экрана")'
        ),
        encoding="utf-8",
    )
    assert tr.main() == 0
    assert "Требований с проверкой журнала: 1 из 2" in capsys.readouterr().out


@req(SR, TRACE)
def test_log_check_found_through_helpers(tmp_path, monkeypatch):
    make_repo(
        tmp_path,
        monkeypatch,
        {
            "helpers.py": """\
                def assert_logged(stack, name):
                    return wait_for(stack, name)


                def wait_for(stack, name):
                    return [e for e in stack.logs("svc") if e["event"] == name]
            """,
            "test_demo.py": """\
                import pytest

                from .helpers import assert_logged

                req = pytest.mark.req


                def check(events):
                    events.one("demo.read")


                @req("demo", "Запись")
                def test_imported_helper(stack):
                    assert_logged(stack, "demo.written")


                @req("demo", "Чтение")
                def test_local_helper(events):
                    check(events)


                @req("demo", "Чтение")
                def test_no_log():
                    events = []
                    events.clear()
            """,
        },
    )
    logs = {m.test.rsplit("::", 1)[1]: m.logs for m in tr.collect().markers}
    assert logs == {"test_imported_helper": True, "test_local_helper": True, "test_no_log": False}
    names = {"demo.written", "demo.read", "demo.lost", "knowledge.portrait.added"}
    assert tr.unchecked_events(names) == ["demo.lost", "knowledge.portrait.added"]


@req(SR, TRACE)
def test_prefix_names_events_of_a_family(tmp_path, monkeypatch):
    make_repo(
        tmp_path,
        monkeypatch,
        {
            "test_demo.py": """\
                import pytest


                @pytest.mark.req("demo", "Запись")
                def test_family(events):
                    assert all(n.startswith("knowledge.portrait.") for n in events.names())
            """
        },
    )
    names = {"knowledge.portrait.added", "knowledge.portraits", "ops.alert.fired"}
    assert tr.unchecked_events(names) == ["knowledge.portraits", "ops.alert.fired"]


@pytest.mark.parametrize(
    ("decorator", "message"),
    [
        ('@req(CAP, NAMES["write"])', "маркер не разобран"),
        ('@req(CAP, "Запись", scenario=f"{CAP}")', "маркер не разобран: scenario="),
        ('@req(CAP, "Запись", scenarios="Успех")', "неизвестный параметр маркера «scenarios»"),
        ('@req(CAP, "Запись", nolog="  ")', "nolog без причины"),
        ('@req(CAP, "Запись", "Успех")', "ждёт два аргумента"),
    ],
)
@req(SR, TRACE)
def test_unresolved_or_malformed_marker_is_an_error(
    tmp_path, monkeypatch, capsys, decorator, message
):
    body = (
        FULL + f'\n\nNAMES = {{"write": "Запись"}}\n\n\n{decorator}\ndef test_more():\n    pass\n'
    )
    make_repo(tmp_path, monkeypatch, {"test_demo.py": body})
    assert tr.main() == 1
    assert message in capsys.readouterr().out


@req(SR, TRACE)
def test_markers_outside_collected_tests_are_errors(tmp_path, monkeypatch, capsys):
    """Засчитываются только тесты, которые соберёт pytest; остальное — ошибка, не покрытие."""
    make_repo(
        tmp_path,
        monkeypatch,
        {
            "test_demo.py": FULL.replace('@req(CAP, "Чтение"', '@req(CAP, "Чтение-старое"')
            + textwrap.dedent(
                """

    def test_outer():
        @req(CAP, "Чтение")
        def test_inner():
            pass


    @req(CAP, "Чтение")
    def helper():
        pass


    class Helper:
        @req(CAP, "Чтение")
        def test_method(self):
            pass


    class TestReading:
        @req(CAP, "Чтение", scenario="Чтение главы")
        def test_method(self, events):
            events.one("demo.read")
"""
            ),
            "conftest.py": """\
                import pytest


                @pytest.mark.req("demo", "Чтение")
                def test_in_conftest():
                    pass
            """,
        },
    )
    assert tr.main() == 1
    out = capsys.readouterr().out
    assert out.count("маркер не на тесте") == 4
    assert "tests/conftest.py:4" in out
    tests = {m.test for m in tr.collect().markers if m.requirement == "Чтение"}
    assert tests == {"tests/test_demo.py::TestReading::test_method"}


@req(SR, TRACE)
def test_class_marker_applies_to_its_tests(tmp_path, monkeypatch, capsys):
    make_repo(
        tmp_path,
        monkeypatch,
        {
            "test_demo.py": """\
                import pytest

                req = pytest.mark.req


                @req("demo", "Запись")
                @req("demo", "Чтение")
                class TestAll:
                    def test_a(self, events):
                        events.one("demo.read")

                    def helper(self):
                        pass
            """
        },
    )
    assert tr.main() == 0
    out = capsys.readouterr().out
    assert "Требований с тестами: 2 из 2" in out
    assert {m.test for m in tr.collect().markers} == {"tests/test_demo.py::TestAll::test_a"}


@req(SR, TRACE)
def test_modified_requirement_expects_delta_scenarios(tmp_path, monkeypatch, capsys):
    """Изменение задало требование заново: ждём его сценарии, прежний заголовок ещё допустим."""
    make_repo(tmp_path, monkeypatch, {"test_demo.py": FULL})
    delta = tmp_path / "openspec" / "changes" / "c1" / "specs" / "demo" / "spec.md"
    delta.parent.mkdir(parents=True)
    delta.write_text(
        "## MODIFIED Requirements\n\n### Requirement: Чтение\n\nSHALL.\n\n"
        "#### Scenario: Чтение главы\n\n#### Scenario: Чтение заметки\n",
        encoding="utf-8",
    )
    model = tr.spec_model("demo")
    assert model["Чтение"].expected == ["Чтение главы", "Чтение заметки"]
    assert model["Запись"].expected == ["Успех", "Отказ"]
    assert tr.main(["--report"]) == 0
    out = capsys.readouterr().out
    assert "Сценариев с тестами: 3 из 4" in out
    assert "- Чтение / Чтение заметки" in out


JUNIT = """\
<testsuites><testsuite>
<testcase classname="tests.test_demo" name="test_write[a]"><skipped message="x"/></testcase>
<testcase classname="tests.test_demo" name="test_write[b]"/>
{read}
</testsuite></testsuites>
"""


@req(SR, TRACE)
def test_junit_requires_marked_tests_to_run(tmp_path, monkeypatch, capsys):
    make_repo(tmp_path, monkeypatch, {"test_demo.py": FULL})
    report = tmp_path / "junit.xml"
    report.write_text(
        JUNIT.format(read='<testcase classname="tests.test_demo" name="test_read"/>'),
        encoding="utf-8",
    )
    assert tr.main(["--junit", str(report)]) == 0
    assert "Помеченных тестов не выполнилось: 0" in capsys.readouterr().out

    report.write_text(
        JUNIT.format(
            read='<testcase classname="tests.test_demo" name="test_read"><skipped/></testcase>'
        ),
        encoding="utf-8",
    )
    assert tr.main(["--junit", str(report)]) == 1
    assert "помеченный тест пропущен: tests/test_demo.py::test_read" in capsys.readouterr().out

    report.write_text(JUNIT.format(read=""), encoding="utf-8")
    assert tr.main(["--junit", str(report), "--junit-report"]) == 0
    out = capsys.readouterr().out
    assert "помеченный тест не запускался: tests/test_demo.py::test_read" in out

    # Второй отчёт (другой прогон) дополняет первый.
    other = tmp_path / "junit-2.xml"
    other.write_text(
        JUNIT.format(read='<testcase classname="tests.test_demo" name="test_read"/>'),
        encoding="utf-8",
    )
    assert tr.main(["--junit", str(report), "--junit", str(other)]) == 0


@req(SR, TRACE)
def test_strict_modes_need_enforce(tmp_path, monkeypatch, capsys):
    make_repo(tmp_path, monkeypatch, {"test_demo.py": FULL}, "enforce: []\nenforce_log: [demo]\n")
    assert tr.main() == 1
    assert "demo: в enforce_scenarios/enforce_log, но не в enforce" in capsys.readouterr().out


@req(SR, TRACE)
def test_static_catalog_matches_sources():
    """Каталог событий по исходникам совпадает с тем, что модули определяют при загрузке."""
    import importlib
    import pkgutil

    import philograph
    from philograph.platform import events as ev

    for module in pkgutil.walk_packages(philograph.__path__, "philograph."):
        importlib.import_module(module.name)
    runtime = {name for name in ev.catalog() if not name.startswith("test.")}
    assert tr.catalog_events() == runtime
