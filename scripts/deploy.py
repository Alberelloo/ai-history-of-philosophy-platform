"""Обновление и откат на сервере: ``python scripts/deploy.py update <версия> | rollback | status``.

Обновление:

0. проверяет конфигурацию ``compose.prod.yaml`` (регион читателя: доверенный прокси и имя
   заголовка страны от CDN) — при недопустимой конфигурации отказывает до сборки;
1. собирает образ новой версии (``philograph:<версия>``);
2. применяет миграции всех схем одноразовым контейнером новой версии — если они упали,
   обновление останавливается, прежние контейнеры продолжают работать;
3. перезапускает сервисы с новой версией и ждёт их готовности;
4. записывает новую версию текущей, прежнюю — для отката.

Откат возвращает прежнюю версию одной командой. Миграции только добавляют (это проверяет
тест), поэтому прежний код работает с новой схемой.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FILES = ["-f", "compose.yaml", "-f", "compose.prod.yaml"]
STATE = ROOT / ".deploy" / "state.json"
PROD_COMPOSE = ROOT / "compose.prod.yaml"

Runner = Callable[[list[str], dict[str, str]], int]


def _compose_tag(loader: yaml.SafeLoader, node: yaml.Node) -> object:
    """Собственные теги Docker Compose (``!reset``, ``!override``): значение как есть."""
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return None


class _ComposeLoader(yaml.SafeLoader):
    pass


for _tag in ("!reset", "!override"):
    _ComposeLoader.add_constructor(_tag, _compose_tag)


def run(command: list[str], env: dict[str, str]) -> int:
    print("$", " ".join(command), flush=True)
    return subprocess.run(command, cwd=ROOT, env={**os.environ, **env}, check=False).returncode


def read_state(path: Path = STATE) -> dict[str, str | None]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"current": None, "previous": None}


def write_state(state: dict[str, str | None], path: Path = STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def compose(*args: str) -> list[str]:
    return ["docker", "compose", *FILES, *args]


def gateway_env_problems(config: dict) -> list[str]:
    """Недопустимая конфигурация региона у шлюза (``regional-access``, «Шлюз доступен только
    через CDN»): сообщения оператору; пустой список — конфигурация в порядке.

    Проверяется ``compose.prod.yaml``: у сервиса ``gateway`` должны быть заданы доверенный
    прокси (``PHILOGRAPH_TRUSTED_PROXY=1``) и имя заголовка страны от CDN
    (``PHILOGRAPH_REGION_HEADER``). Без них шлюз не определит страну читателя и закроет
    ограниченные источники всем.
    """
    problems: list[str] = []
    gateway = ((config or {}).get("services") or {}).get("gateway") or {}
    environment = gateway.get("environment") or {}
    if str(environment.get("PHILOGRAPH_TRUSTED_PROXY")) != "1":
        problems.append(
            "PHILOGRAPH_TRUSTED_PROXY=1 не задан у сервиса gateway в compose.prod.yaml: "
            "шлюз не будет доверять заголовку страны от CDN, и ограниченные источники "
            "закроются всем читателям"
        )
    header = environment.get("PHILOGRAPH_REGION_HEADER")
    if not header or not str(header).strip():
        problems.append(
            "PHILOGRAPH_REGION_HEADER не задан у сервиса gateway в compose.prod.yaml: "
            "шлюз не узнает страну читателя, и ограниченные источники закроются всем читателям"
        )
    return problems


def check_prod_config(path: Path = PROD_COMPOSE) -> list[str]:
    """Сообщения оператору о недопустимой конфигурации публичного сервера; пусто — в порядке."""
    config = yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader)
    return gateway_env_problems(config)


def update(
    version: str,
    runner: Runner = run,
    state_path: Path = STATE,
    config_path: Path = PROD_COMPOSE,
) -> int:
    env = {"PHILOGRAPH_VERSION": version}
    problems = check_prod_config(config_path)
    if problems:
        for problem in problems:
            print(f"выкладка остановлена: {problem}", file=sys.stderr)
        print(
            "Поправьте compose.prod.yaml (или .env) и повторите выкладку: "
            f"python scripts/deploy.py update {version}",
            file=sys.stderr,
        )
        return 1
    if runner(compose("build"), env) != 0:
        print("сборка не удалась, работает прежняя версия", file=sys.stderr)
        return 1
    if runner(compose("run", "--rm", "migrate"), env) != 0:
        print(
            "миграции не применились, обновление остановлено; работает прежняя версия",
            file=sys.stderr,
        )
        return 1
    if runner(compose("up", "-d", "--wait", "--remove-orphans"), env) != 0:
        print(
            "сервисы новой версии не стали готовы; откат: python scripts/deploy.py rollback",
            file=sys.stderr,
        )
        state = read_state(state_path)
        write_state({"current": version, "previous": state["current"]}, state_path)
        return 1
    state = read_state(state_path)
    previous = state["current"] if state["current"] != version else state["previous"]
    write_state({"current": version, "previous": previous}, state_path)
    print(f"работает версия {version}; прежняя для отката: {previous}")
    return 0


def rollback(runner: Runner = run, state_path: Path = STATE) -> int:
    state = read_state(state_path)
    previous = state["previous"]
    if not previous:
        print("прежней версии нет: откатываться некуда", file=sys.stderr)
        return 1
    if (
        runner(compose("up", "-d", "--wait", "--remove-orphans"), {"PHILOGRAPH_VERSION": previous})
        != 0
    ):
        print("прежняя версия не стала готова", file=sys.stderr)
        return 1
    write_state({"current": previous, "previous": state["current"]}, state_path)
    print(f"откат выполнен: работает версия {previous}")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["update"] and len(argv) == 2:
        return update(argv[1])
    if argv == ["rollback"]:
        return rollback()
    if argv == ["status"]:
        print(json.dumps(read_state(), ensure_ascii=False))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
