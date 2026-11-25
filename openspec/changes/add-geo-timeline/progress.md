# Progress

## 2026-11-25 — планирование (разработчик, субагент `coder`)

- Ведёт: субагент `coder` по поручению основной сессии (`change-loop`). Ветка `claude/reference-catalog` (от `origin/claude/embedding-docker`). Коммитит ведущий.
- CLI `openspec` в окружении нет: файлы созданы вручную по образцу `archive/2026-11-18-synchro-map`. `openspec validate` не прогонялся, формат сверен чтением с `openspec/config.yaml`.
- Референс разобран по тексту страницы и по собранному коду (`/assets/influenced-by-*.js`):
  - d3-geo `geoOrthographic` на SVG;
  - `ne_110m_admin_0_countries.json`;
  - d3-drag и d3-zoom;
  - `d3.timer`, весь период за 15 с;
  - окно видимости связи 250 лет (в тексте поста — 150).

  WebGL нет. Выводы — в документе вариантов, раздел 1.
- Сделано:
  - 1.1 — `docs/design/features/geo-timeline-options.md`: 7 вариантов рендера, хранение координат, вид места, интеграция, доступность, границы, тестируемость, рекомендация;
  - 1.2 — `proposal.md`, `design.md`, `tasks.md`, дельты `geo-timeline` (новая возможность), `ontology-registry`, `ontology-extraction`, `visual-design`.
- Решение: А (d3-geo, SVG) + К1 (`coordinates`, вид `geo`) + Р1 (`place_role`) + И1 (`/graph?view=globe`) + отдельный `GET /v1/map/places` поверх `SectionMap`.
- Прочитаны соседние изменения стека: `add-reference-catalog` (общий снимок `knowledge/snapshot.py`, `knowledge/epochs.py`), папки `add-epochs` и `add-epoch-context` (на момент чтения — только каталоги `specs/`). Глобус опирается на снимок. Эпоху на подписи года берёт из `eras` ответа `/map`, от `add-epochs` не зависит.
- Не проверено:
  - объём мест в данных Lead'а: число персон с Wikidata-id неизвестно, данные `.stack` у Lead'а;
  - производительность SVG на 1 CPU без GPU (задача 5.6);
  - e2e на этой машине не прогнать (1 ГБ RAM, нет Docker) — 7.7.

Статус пунктов: 1.1, 1.2 — сделаны; 1.3 — следующий (ревью плана); остальные не начаты.

Следующий шаг: ревьювер и тестировщик читают план (1.3), правки — в эти же файлы, затем 1.4 и слой 2.
