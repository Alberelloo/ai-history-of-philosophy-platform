# Progress: pilot-evaluation

## 2026-11-19

- Изменение выделено из `pilot-launch`: туда входили задачи 2.1–2.5. Задача 2.5 «порог графа» расширена до порогов карты и упоминаний. Граф заменён картой в #42.
- Текущие значения порогов сверены по коду: `GraphSettings(min_edges=5, max_nodes=60)` в `src/philograph/knowledge/graph.py`, `MapSettings(max_entities=400)` из `PHILOGRAPH_MAP_MAX_ENTITIES` в `src/philograph/knowledge/main.py`.

## Сейчас

Ни одна задача не начата: всё ждёт `pilot-data` 1.1 и ключей владельца.

## Следующий шаг

1.1 — после загрузки источников.
