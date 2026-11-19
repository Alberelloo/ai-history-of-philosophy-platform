"""Проверка прослеживаемости: требования и сценарии спецификаций связаны с тестами.

Требования и сценарии берутся из спецификаций OpenSpec (``### Requirement:`` и
``#### Scenario:`` под ним): основная спецификация и дельты действующих изменений. Требование,
которое изменение переименовало (``## RENAMED Requirements``, строка ``- FROM:``) или удалило
(``## REMOVED Requirements``), теста больше не ждёт, а маркер на него — ошибка. Если изменение
добавило или изменило требование, ожидаемые сценарии берутся из дельты.

Тест связывается с требованием маркером::

    @pytest.mark.req("<возможность>", "<требование>")                    # требование
    @pytest.mark.req("<возможность>", "<требование>", scenario="<...>")  # сценарий дословно
    @pytest.mark.req("<возможность>", "<требование>", invariant="<...>") # нормативный тест
    @pytest.mark.req(..., nolog="<причина>")  # тест сознательно не проверяет журнал

Режимы (``openspec/traceability.yaml``):

- ``enforce`` — у каждого требования возможности есть тест;
- ``enforce_scenarios`` — у каждого сценария возможности есть тест;
- ``enforce_log`` — у каждого требования есть тест с проверкой журнала или с ``nolog``.

Всегда ошибка: маркер на несуществующее требование или сценарий, аргумент маркера не строка и
не строковая константа модуля, неизвестный параметр маркера, пустой ``nolog``, маркер не на
тесте (засчитываются только функции ``test_*`` модуля и методы ``test_*`` классов ``Test*``).

Проверка журнала определяется статически по AST: в теле теста или в функциях, которые он
вызывает (того же модуля или импортированных из ``tests/``, до глубины ``HELPER_DEPTH``),
есть обращение к фикстуре ``events`` (кроме ``events.clear``), вызов ``wait_logs(...)`` или
``<стенд>.logs(...)``, обращение к ``caplog``. Ограничения: не видны проверки в фикстурах, в
функциях вне ``tests/``, в методах классов-помощников и при вызове через переменную; журнал,
переданный под другим именем, тоже не виден. Обращение не значит, что проверка содержательна:
это решает тестировщик и ревьювер.

Запуск::

    python scripts/check_traceability.py                     # проверка и итог
    python scripts/check_traceability.py --report            # плюс списки непокрытого
    python scripts/check_traceability.py --junit report.xml  # плюс сверка с прогоном pytest
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQ_RE = re.compile(r"^### Requirement:\s*(.+?)\s*$", re.MULTILINE)
SCENARIO_RE = re.compile(r"^#### Scenario:\s*(.+?)\s*$")
RENAMED_FROM_RE = re.compile(r"^-\s*FROM:\s*`?###\s*Requirement:\s*(.+?)`?\s*$", re.MULTILINE)
EVENT_DEFINE_RE = re.compile(r'\bdefine\(\s*"([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)"')
PREFIX_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*\.$")
MARKER_OPTIONS = ("scenario", "invariant", "nolog")
# Насколько глубоко идти по вызовам вспомогательных функций в поиске проверки журнала.
HELPER_DEPTH = 3


# --- спецификации ---------------------------------------------------------------------


def _sections(text: str) -> dict[str, str]:
    """Спецификация изменения по разделам: ``ADDED/MODIFIED/REMOVED/RENAMED Requirements``."""
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    return {part.partition("\n")[0].strip(): part for part in parts[1:]}


def retired(text: str) -> set[str]:
    """Имена требований, которые изменение переименовало или удалило."""
    sections = _sections(text)
    names = set(RENAMED_FROM_RE.findall(sections.get("RENAMED Requirements", "")))
    return names | set(REQ_RE.findall(sections.get("REMOVED Requirements", "")))


def requirement_blocks(text: str) -> dict[str, list[str]]:
    """Требования текста и их сценарии: от ``### Requirement:`` до следующего заголовка 2–3
    уровня. Удалённые требования (раздел REMOVED) сюда не входят."""
    blocks: dict[str, list[str]] = {}
    current: list[str] | None = None
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            current = None
            continue
        found = REQ_RE.match(line)
        if found:
            current = None
            if section != "REMOVED Requirements":
                current = blocks.setdefault(found.group(1), [])
            continue
        if line.startswith("### "):
            current = None
            continue
        scenario = SCENARIO_RE.match(line)
        if scenario and current is not None:
            current.append(scenario.group(1))
    return blocks


def _spec_paths(capability: str) -> tuple[Path, list[Path]]:
    main = ROOT / "openspec" / "specs" / capability / "spec.md"
    changes = [
        path
        for path in sorted(ROOT.glob(f"openspec/changes/*/specs/{capability}/spec.md"))
        if "archive" not in path.relative_to(ROOT).parts
    ]
    return main, changes


@dataclass
class Requirement:
    where: list[str] = field(default_factory=list)
    # Сценарии, которые ждут теста: из дельты, если изменение задало требование заново.
    expected: list[str] = field(default_factory=list)
    # Все известные заголовки сценариев (основная спецификация и дельты): для опечаток.
    known: set[str] = field(default_factory=set)


def spec_model(capability: str) -> dict[str, Requirement]:
    """Требования возможности по основной спецификации и действующим изменениям."""
    main, changes = _spec_paths(capability)
    found: dict[str, Requirement] = {}
    gone: set[str] = set()
    redefined: dict[str, list[str]] = {}
    for path in [main, *changes]:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for name, scenarios in requirement_blocks(text).items():
            item = found.setdefault(name, Requirement())
            item.where.append(str(path.relative_to(ROOT)))
            item.known.update(scenarios)
            if path == main:
                item.expected = list(scenarios)
            else:
                merged = redefined.setdefault(name, [])
                merged.extend(s for s in scenarios if s not in merged)
        gone |= retired(text)
    for name, scenarios in redefined.items():
        found[name].expected = scenarios
    return {name: item for name, item in found.items() if name not in gone}


def spec_requirements(capability: str) -> dict[str, list[str]]:
    """Требования возможности и файлы, где они описаны."""
    return {name: item.where for name, item in spec_model(capability).items()}


# --- тесты ----------------------------------------------------------------------------


@dataclass
class Marker:
    capability: str
    requirement: str
    test: str  # tests/x/test_y.py::TestA::test_b
    logs: bool
    scenario: str | None = None
    invariant: str | None = None
    nolog: str | None = None


@dataclass
class Module:
    path: Path
    tree: ast.Module
    consts: dict[str, str]
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef]
    imports: dict[str, tuple[str, str]]  # имя → (модуль tests.x.y, имя в нём)
    aliases: set[str]  # имена, под которыми модуль держит pytest.mark.req


@dataclass
class Collected:
    markers: list[Marker] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Строки, которые называют события в тестах с проверкой журнала.
    log_strings: set[str] = field(default_factory=set)


def _dotted(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def _is_mark_req(node: ast.expr) -> bool:
    """``pytest.mark.req`` или ``mark.req``."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "req"
        and (
            (isinstance(node.value, ast.Attribute) and node.value.attr == "mark")
            or (isinstance(node.value, ast.Name) and node.value.id == "mark")
        )
    )


def _load(path: Path) -> Module:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    consts: dict[str, str] = {}
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    imports: dict[str, tuple[str, str]] = {}
    aliases: set[str] = set()
    package = _dotted(path).rsplit(".", 1)[0]
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign | ast.AnnAssign):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            value = stmt.value
            for target in targets:
                if not isinstance(target, ast.Name) or value is None:
                    continue
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    consts[target.id] = value.value
                elif _is_mark_req(value):
                    aliases.add(target.id)
        elif isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            functions[stmt.name] = stmt
        elif isinstance(stmt, ast.ImportFrom) and stmt.level:
            base = package.split(".")
            base = base[: len(base) - (stmt.level - 1)] if stmt.level > 1 else base
            module = ".".join([*base, *([stmt.module] if stmt.module else [])])
            for alias in stmt.names:
                imports[alias.asname or alias.name] = (module, alias.name)
        elif isinstance(stmt, ast.ImportFrom) and (stmt.module or "").startswith("tests"):
            for alias in stmt.names:
                imports[alias.asname or alias.name] = (stmt.module or "", alias.name)
    return Module(path, tree, consts, functions, imports, aliases)


class _Analyzer:
    """Разбор всех модулей ``tests/``: маркеры, тесты, проверки журнала."""

    def __init__(self, root: Path) -> None:
        self.modules: dict[str, Module] = {}
        for path in sorted((root / "tests").rglob("*.py")):
            self.modules[_dotted(path)] = _load(path)

    # Проверка журнала --------------------------------------------------------------

    def _resolve_function(self, module: Module, name: str):
        if name in module.functions:
            return module, module.functions[name]
        if name in module.imports:
            target, original = module.imports[name]
            other = self.modules.get(target)
            if other and original in other.functions:
                return other, other.functions[original]
        return None

    def logs(self, module: Module, fn: ast.AST, strings: set[str], depth: int = 0) -> bool:
        """Есть ли в функции (или в вызываемых ею помощниках) обращение к журналу."""
        found = False
        local: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Attribute):
                owner = node.value
                if isinstance(owner, ast.Name) and owner.id == "events" and node.attr != "clear":
                    found = True
            elif isinstance(node, ast.Name) and node.id == "caplog":
                found = True
            elif isinstance(node, ast.Call):
                func = node.func
                if (isinstance(func, ast.Name) and func.id == "wait_logs") or (
                    isinstance(func, ast.Attribute) and func.attr in ("wait_logs", "logs")
                ):
                    found = True
                if isinstance(func, ast.Name) and depth < HELPER_DEPTH:
                    helper = self._resolve_function(module, func.id)
                    if helper and helper[1] is not fn and self.logs(*helper, strings, depth + 1):
                        found = True
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                local.add(node.value)
            elif isinstance(node, ast.Name) and node.id in module.consts:
                local.add(module.consts[node.id])
        if found:
            strings |= local
        return found

    # Маркеры ------------------------------------------------------------------------

    def _is_req(self, module: Module, deco: ast.expr) -> bool:
        if not isinstance(deco, ast.Call):
            return False
        func = deco.func
        return _is_mark_req(func) or (isinstance(func, ast.Name) and func.id in module.aliases)

    def _value(self, module: Module, arg: ast.expr) -> str | None:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        if isinstance(arg, ast.Name):
            return module.consts.get(arg.id)
        return None

    def _parse_marker(self, module: Module, call: ast.Call, where: str, out: Collected):
        line = f"{module.path.relative_to(ROOT).as_posix()}:{call.lineno}"
        if len(call.args) != 2:
            out.errors.append(f"маркер req ждёт два аргумента (возможность, требование): {line}")
            return None
        values = [self._value(module, a) for a in call.args]
        if any(v is None for v in values):
            out.errors.append(
                f"маркер не разобран: аргумент не строка и не строковая константа модуля ({line})"
            )
            return None
        options: dict[str, str] = {}
        for keyword in call.keywords:
            if keyword.arg not in MARKER_OPTIONS:
                out.errors.append(f"неизвестный параметр маркера «{keyword.arg}» ({line})")
                return None
            value = self._value(module, keyword.value)
            if value is None:
                out.errors.append(
                    f"маркер не разобран: {keyword.arg}= не строка и не константа модуля ({line})"
                )
                return None
            options[keyword.arg] = value
        if "nolog" in options and not options["nolog"].strip():
            out.errors.append(f"nolog без причины ({line})")
            return None
        return values[0], values[1], options

    def collect(self) -> Collected:
        out = Collected()
        for module in self.modules.values():
            if not module.path.name.startswith("test_"):
                self._stray(module, set(), out)
                continue
            module_marks = self._module_marks(module)
            consumed: set[int] = set()
            for stmt in module.tree.body:
                if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                    if stmt.name.startswith("test_"):
                        self._test(module, stmt, [stmt.name], module_marks, consumed, out)
                elif isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"):
                    self._class(module, stmt, [stmt.name], module_marks, consumed, out)
            self._stray(module, consumed, out)
        return out

    def _module_marks(self, module: Module) -> list[ast.Call]:
        """Маркеры req в ``pytestmark`` модуля: относятся ко всем его тестам."""
        marks: list[ast.Call] = []
        for stmt in module.tree.body:
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
            ):
                items = stmt.value.elts if isinstance(stmt.value, ast.List) else [stmt.value]
                marks += [m for m in items if self._is_req(module, m)]
        return marks

    def _class(self, module, cls: ast.ClassDef, path, inherited, consumed, out) -> None:
        marks = [*inherited, *(d for d in cls.decorator_list if self._is_req(module, d))]
        for stmt in cls.body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                if stmt.name.startswith("test_"):
                    self._test(module, stmt, [*path, stmt.name], marks, consumed, out)
            elif isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"):
                self._class(module, stmt, [*path, stmt.name], marks, consumed, out)
        consumed.update(id(m) for m in marks)

    def _test(self, module, fn, path, inherited, consumed, out) -> None:
        marks = [*inherited, *(d for d in fn.decorator_list if self._is_req(module, d))]
        if not marks:
            return
        test = "::".join([module.path.relative_to(ROOT).as_posix(), *path])
        strings: set[str] = set()
        logs = self.logs(module, fn, strings)
        for call in marks:
            consumed.add(id(call))
            parsed = self._parse_marker(module, call, test, out)
            if parsed is None:
                continue
            capability, requirement, options = parsed
            out.markers.append(Marker(capability, requirement, test, logs, **options))
        if logs:
            out.log_strings |= strings

    def _stray(self, module: Module, consumed: set[int], out: Collected) -> None:
        """Маркер req, который pytest не применит к тесту: ошибка, а не тихий пропуск."""
        for node in ast.walk(module.tree):
            if (
                isinstance(node, ast.Call)
                and self._is_req(module, node)
                and id(node) not in consumed
            ):
                out.errors.append(
                    "маркер не на тесте (засчитываются функции test_* модуля и методы test_* "
                    f"классов Test*): {module.path.relative_to(ROOT).as_posix()}:{node.lineno}"
                )


def collect(root: Path | None = None) -> Collected:
    return _Analyzer(root or ROOT).collect()


def test_markers() -> dict[tuple[str, str], list[str]]:
    """Тесты по паре «возможность, требование»."""
    markers: dict[tuple[str, str], list[str]] = {}
    for marker in collect().markers:
        markers.setdefault((marker.capability, marker.requirement), []).append(marker.test)
    return markers


# --- события каталога ------------------------------------------------------------------


def catalog_events() -> set[str]:
    """Имена событий каталога по исходникам (``define("<имя>", ...)``), без ``test.*``."""
    names: set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        names |= set(EVENT_DEFINE_RE.findall(path.read_text(encoding="utf-8")))
    return {name for name in names if not name.startswith("test.")}


def unchecked_events(names: set[str], collected: Collected | None = None) -> list[str]:
    """События, которых не называет ни один тест с проверкой журнала.

    Событие названо, если его имя — строка в таком тесте (или в помощнике, который он
    вызывает), либо строка вида ``"knowledge.portrait."`` — префикс имени.
    """
    strings = (collected or collect()).log_strings
    prefixes = tuple(s for s in strings if PREFIX_RE.match(s))
    return sorted(n for n in names if n not in strings and not n.startswith(prefixes))


# --- сверка с прогоном pytest ----------------------------------------------------------


def junit_outcomes(paths: list[Path]) -> dict[tuple[str, str], bool]:
    """(classname, имя теста без параметров) → выполнялся ли хоть раз без пропуска."""
    outcomes: dict[tuple[str, str], bool] = {}
    for path in paths:
        for case in ET.parse(path).getroot().iter("testcase"):
            key = (case.get("classname", ""), case.get("name", "").split("[", 1)[0])
            ran = case.find("skipped") is None
            outcomes[key] = outcomes.get(key, False) or ran
    return outcomes


def junit_problems(markers: list[Marker], paths: list[Path]) -> list[str]:
    outcomes = junit_outcomes(paths)
    problems: list[str] = []
    for test in sorted({m.test for m in markers}):
        file, *names = test.split("::")
        classname = ".".join([*Path(file).with_suffix("").parts, *names[:-1]])
        ran = outcomes.get((classname, names[-1]))
        if ran is None:
            problems.append(f"помеченный тест не запускался: {test}")
        elif not ran:
            problems.append(f"помеченный тест пропущен: {test}")
    return problems


# --- итог ------------------------------------------------------------------------------


def _load_config() -> dict:
    config = yaml.safe_load((ROOT / "openspec" / "traceability.yaml").read_text(encoding="utf-8"))
    return config or {}


def main(argv: list[str] | tuple[str, ...] = ()) -> int:
    parser = argparse.ArgumentParser(description="Проверка прослеживаемости требований тестами")
    parser.add_argument("--report", action="store_true", help="списки непокрытого по возможностям")
    parser.add_argument(
        "--junit", action="append", type=Path, default=[], help="отчёт pytest --junitxml"
    )
    parser.add_argument(
        "--junit-report",
        action="store_true",
        help="несовпадения с отчётом pytest только печатать, не падать",
    )
    args = parser.parse_args(list(argv))

    config = _load_config()
    enforced: list[str] = config.get("enforce") or []
    enforce_scenarios: list[str] = config.get("enforce_scenarios") or []
    enforce_log: list[str] = config.get("enforce_log") or []
    problems: list[str] = [
        f"{name}: в enforce_scenarios/enforce_log, но не в enforce"
        for name in sorted(set(enforce_scenarios) | set(enforce_log))
        if name not in enforced
    ]

    collected = collect()
    problems += collected.errors
    by_requirement: dict[tuple[str, str], list[Marker]] = defaultdict(list)
    for marker in collected.markers:
        by_requirement[(marker.capability, marker.requirement)].append(marker)

    models: dict[str, dict[str, Requirement]] = {}

    def model(capability: str) -> dict[str, Requirement]:
        if capability not in models:
            models[capability] = spec_model(capability)
        return models[capability]

    # Маркеры: требование и сценарий существуют.
    for (capability, name), markers in by_requirement.items():
        requirements = model(capability)
        tests = ", ".join(sorted({m.test for m in markers}))
        if not requirements:
            problems.append(f"{capability}: маркер на неизвестную возможность ({tests})")
            continue
        if name not in requirements:
            problems.append(f"{capability}: маркер на несуществующее требование «{name}» ({tests})")
            continue
        for marker in markers:
            if marker.scenario is not None and marker.scenario not in requirements[name].known:
                problems.append(
                    f"{capability}: в «{name}» нет сценария «{marker.scenario}» ({marker.test})"
                )

    totals = defaultdict(int)
    report: dict[str, dict[str, list[str]]] = {}
    for capability in enforced:
        requirements = model(capability)
        if not requirements:
            problems.append(f"{capability}: спецификация не найдена")
        missing_scenarios: list[str] = []
        missing_log: list[str] = []
        for name, item in requirements.items():
            markers = by_requirement.get((capability, name), [])
            totals["requirements"] += 1
            if markers:
                totals["covered"] += 1
            else:
                problems.append(f"{capability}: нет теста для «{name}»")
            if any(m.logs for m in markers):
                totals["logged"] += 1
            elif not any(m.nolog for m in markers):
                missing_log.append(name)
                if capability in enforce_log:
                    problems.append(f"{capability}: нет теста с проверкой журнала для «{name}»")
            tested = {m.scenario for m in markers}
            for scenario in item.expected:
                totals["scenarios"] += 1
                if scenario in tested:
                    totals["scenarios_covered"] += 1
                    continue
                missing_scenarios.append(f"{name} / {scenario}")
                if capability in enforce_scenarios:
                    problems.append(f"{capability}: нет теста для сценария «{name} / {scenario}»")
        report[capability] = {"scenarios": missing_scenarios, "log": missing_log}

    normative = {m.test for m in collected.markers if m.invariant}
    print(f"Требований с тестами: {totals['covered']} из {totals['requirements']}")
    print(f"Сценариев с тестами: {totals['scenarios_covered']} из {totals['scenarios']}")
    print(f"Требований с проверкой журнала: {totals['logged']} из {totals['requirements']}")
    print(f"Нормативных тестов: {len(normative)}")

    if args.junit:
        mismatches = junit_problems(collected.markers, args.junit)
        print(f"Помеченных тестов не выполнилось: {len(mismatches)}")
        if args.junit_report:
            for line in mismatches:
                print(f"  · {line}")
        else:
            problems += mismatches

    if args.report:
        _print_report(report, collected)

    for problem in problems:
        print(f"  ✗ {problem}")
    return 1 if problems else 0


def _print_report(report: dict[str, dict[str, list[str]]], collected: Collected) -> None:
    print("\nНепокрытое по возможностям:")
    for capability, gaps in report.items():
        if not gaps["scenarios"] and not gaps["log"]:
            continue
        print(f"\n{capability}")
        if gaps["scenarios"]:
            print(f"  сценарии без теста ({len(gaps['scenarios'])}):")
            for line in gaps["scenarios"]:
                print(f"    - {line}")
        if gaps["log"]:
            print(f"  требования без проверки журнала и без nolog ({len(gaps['log'])}):")
            for line in gaps["log"]:
                print(f"    - {line}")
    events = catalog_events()
    unchecked = unchecked_events(events, collected)
    print(f"\nСобытия каталога без проверки в тестах: {len(unchecked)} из {len(events)}")
    for name in unchecked:
        print(f"    - {name}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
