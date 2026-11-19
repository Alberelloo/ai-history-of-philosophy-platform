# Progress: quality-followups

## 2026-11-19

- Изменение заведено при уборке OpenSpec (ветка `claude/openspec-cleanup`). Задачи перенесены из архивных изменений: synchro-map 7.3, reader-layout 6.2, reader-mentions-popover 5.2, reader-full-card 4.2, reader-notes 5.2, reader-assistant 5.2, assistant-page 5.2. В архиве у каждой стоит пометка «перенесено в `quality-followups` п. N».
- Состояние эталонов проверено по `tests/e2e/visual/baselines/win32`: есть 154 снимка `reader-*`, добавлены в #32 и последний раз менялись в #42. Снимков `map-*` нет.
- E2E под карту проходит в CI: проверки `e2e` в #42 и #43 зелёные (аудит, раздел 3).

## Сейчас

Задачи 1.x ждут владельца с Windows. Задачу 2.1 может взять тестировщик без владельца.

## Следующий шаг

2.1 — запуск тестировщика.
