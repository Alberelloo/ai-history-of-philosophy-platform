// Мини-обвязка юнит-тестов модулей клиента: файл *.test.ts собирается esbuild и
// запускается в node (tests/web/test_geo_units.py). Падение — ненулевой код выхода.

let failed = 0;
let passed = 0;

export function test(name: string, fn: () => void): void {
  try {
    fn();
    passed += 1;
  } catch (e) {
    failed += 1;
    console.log(`FAIL ${name}: ${(e as Error).message}`);
  }
}

export function eq<T>(actual: T, expected: T, what = ""): void {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  if (a !== b) throw new Error(`${what} ожидалось ${b}, получено ${a}`);
}

export function ok(cond: unknown, what: string): void {
  if (!cond) throw new Error(what);
}

export function near(actual: number, expected: number, tol: number, what = ""): void {
  if (!(Math.abs(actual - expected) <= tol)) throw new Error(`${what} ожидалось ${expected}±${tol}, получено ${actual}`);
}

export function done(): void {
  console.log(`passed ${passed}, failed ${failed}`);
  if (failed) throw new Error(`${failed} failed`);
}
