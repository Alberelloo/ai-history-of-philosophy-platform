"""Мутационная проверка изменения: каждая мутация ломает код, указанные тесты должны упасть.

Формат — ``tests/mutations/<изменение>/mutations.yaml``::

    mutations:
      - id: lang-given
        requirement: Язык названий сущностей      # заголовок ``### Requirement:`` дельты
        patch: lang-given.patch                     # путь от папки изменения
        expect_fail:
          - tests/knowledge/test_entity_naming.py::test_language_by_script_on_every_path

Запуск:

    python scripts/mutation_check.py --change <изменение> [--id <мутация>]
    python scripts/mutation_check.py --coverage <изменение>

Режим проверки для каждой мутации: файлы патча без незакоммиченных правок → ``git apply`` →
``pytest -q`` по каждому тесту из ``expect_fail`` (каждый должен упасть) → ``git apply -R``
(и при ошибке). Печатается таблица Markdown «требование | мутация | ожидаемый тест | упал».
Код выхода 1, если какой-то тест не упал или патч не применился.

Режим ``--coverage`` патчей не применяет и pytest не запускает: у каждого требования дельт
(ADDED и MODIFIED) есть хотя бы одна мутация с непустым ``expect_fail``, каждый патч
существует, каждый тест из ``expect_fail`` — существующий файл. Недостающее печатается,
код выхода 1.

Чистота дерева проверяется по файлам патча, а не по всему дереву: в одной ветке могут идти
несколько изменений сразу, и чужие незакоммиченные правки в других файлах мутации не мешают.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQ_RE = re.compile(r"^### Requirement:\s*(.+?)\s*$", re.MULTILINE)
PATCH_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


def mutations_dir(change: str) -> Path:
    return ROOT / "tests" / "mutations" / change


def load(change: str) -> list[dict]:
    path = mutations_dir(change) / "mutations.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("mutations") or [])


def requirements(change: str) -> list[str]:
    found: list[str] = []
    for spec in sorted((ROOT / "openspec" / "changes" / change / "specs").glob("*/spec.md")):
        for name in REQ_RE.findall(spec.read_text(encoding="utf-8")):
            if name not in found:
                found.append(name)
    return found


def coverage(change: str) -> int:
    items = load(change)
    problems: list[str] = []
    covered = {m.get("requirement") for m in items if m.get("expect_fail")}
    for name in requirements(change):
        if name not in covered:
            problems.append(f"нет мутации для требования «{name}»")
    for m in items:
        patch = mutations_dir(change) / str(m.get("patch", ""))
        if not m.get("patch") or not patch.is_file():
            problems.append(f"{m.get('id')}: нет патча {m.get('patch')}")
        for node in m.get("expect_fail") or []:
            if not (ROOT / node.split("::", 1)[0]).is_file():
                problems.append(f"{m.get('id')}: нет файла теста {node}")
        if not m.get("expect_fail"):
            problems.append(f"{m.get('id')}: пустой expect_fail")
    for p in problems:
        print(p)
    if not problems:
        print(f"{change}: мутации есть у всех {len(requirements(change))} требований")
    return 1 if problems else 0


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def _patch_files(patch: Path) -> list[str]:
    return PATCH_FILE_RE.findall(patch.read_text(encoding="utf-8"))


def run(change: str, only: str | None) -> int:
    items = [m for m in load(change) if only is None or m["id"] == only]
    if not items:
        print(f"нет мутаций {only or ''} в {mutations_dir(change)}")
        return 1
    rows: list[tuple[str, str, str, str]] = []
    failed = False
    # Код из этого дерева, а не из установленного пакета: скрипт можно запускать и в
    # отдельном ``git worktree``, не трогая рабочую копию других изменений.
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)])}
    for m in items:
        patch = mutations_dir(change) / m["patch"]
        files = _patch_files(patch)
        dirty = _git("status", "--porcelain", "--", *files).stdout.strip()
        if dirty:
            print(f"{m['id']}: файлы патча с незакоммиченными правками:\n{dirty}")
            return 1
        applied = _git("apply", str(patch))
        if applied.returncode != 0:
            rows.append(
                (m["requirement"], m["id"], "—", f"патч не применился: {applied.stderr.strip()}")
            )
            failed = True
            continue
        try:
            for node in m["expect_fail"]:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        "-x",
                        "--no-header",
                        "-p",
                        "no:cacheprovider",
                        node,
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    env=env,
                )
                last_line = (result.stdout.strip().splitlines() or [""])[-1]
                # Упал именно тест (``failed``), а не сбор или импорт (``error``).
                fell = result.returncode == 1 and " failed" in f" {last_line}"
                last = (result.stdout.strip().splitlines() or [""])[-1]
                rows.append(
                    (m["requirement"], m["id"], node, f"{'да' if fell else 'НЕТ'} ({last})")
                )
                failed |= not fell
        finally:
            reverted = _git("apply", "-R", str(patch))
        if reverted.returncode != 0:
            print(f"{m['id']}: патч не откатился: {reverted.stderr}")
            return 2
    print("| Требование | Мутация | Ожидаемый тест | Упал |")
    print("|---|---|---|---|")
    for row in rows:
        print("| " + " | ".join(row) + " |")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--change", help="прогнать мутации изменения")
    group.add_argument("--coverage", metavar="CHANGE", help="у каждого требования есть мутация")
    parser.add_argument("--id", help="только эта мутация")
    args = parser.parse_args(argv)
    if args.coverage:
        return coverage(args.coverage)
    return run(args.change, args.id)


if __name__ == "__main__":
    sys.exit(main())
