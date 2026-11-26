"""Юнит-проверка логики «Показать ещё» (``web/src/reference/paging.ts``) без браузера.

Модуль транспилируется компилятором TypeScript из ``web/node_modules`` и выполняется в node.
Случай ревью: между страницами снимок сменился, запись сдвинулась и пришла повтором —
следующий запрос всё равно идёт за следующей страницей, а не за той же."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"
SCRIPT = r"""
const ts = require(process.argv[1]);
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const options = { compilerOptions: { module: ts.ModuleKind.CommonJS } };
const js = ts.transpileModule(src, options).outputText;
const m = { exports: {} };
new Function("module", "exports", js)(m, m.exports);
const { hasMore, nextPage, appendPage } = m.exports;
const ids = (from, to) => Array.from({ length: to - from }, (_, i) => ({ id: "e" + (from + i) }));
// 30 записей, показана страница 1 (24); новая запись в начале — total 31, страница 2 — 25..31,
// её первая запись (старая 24-я) — повтор.
let shown = ids(0, 24);
let paging = { page: 1, limit: 24, total: 30, returned: 24 };
const out = { first: hasMore(paging), next: nextPage(paging) };
const merged = appendPage(shown, ids(23, 30));
shown = merged.items;
paging = { page: 2, limit: 24, total: 31, returned: 7 };
out.firstNew = merged.firstNew;
out.shown = shown.length;
out.unique = new Set(shown.map((i) => i.id)).size;
out.afterSecond = hasMore(paging);
out.nextAfterSecond = nextPage(paging);
out.emptyPage = hasMore({ page: 3, limit: 24, total: 31, returned: 0 });
out.exact = hasMore({ page: 2, limit: 15, total: 30, returned: 15 });
console.log(JSON.stringify(out));
"""


def test_load_more_counts_pages_not_rows():
    node = shutil.which("node")
    tsc = WEB / "node_modules" / "typescript" / "lib" / "typescript.js"
    if not node or not tsc.exists():
        pytest.skip("нет node или зависимостей клиента (npm ci в web/)")
    result = subprocess.run(
        [node, "-e", SCRIPT, str(tsc), str(WEB / "src" / "reference" / "paging.ts")],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    out = json.loads(result.stdout)
    assert out == {
        "first": True,
        "next": 2,
        "firstNew": 24,
        "shown": 30,
        "unique": 30,
        # 2·24 = 48 ≥ 31: дальше не нужно — кнопка исчезает, а не просит page=2 снова.
        "afterSecond": False,
        "nextAfterSecond": 3,
        "emptyPage": False,
        "exact": False,
    }
