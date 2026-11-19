# Progress: pilot-data

## 2026-11-19

- Изменение выделено из `pilot-launch`: туда входили задачи 1.1–1.3. Добавлены 1.2–1.4: оставшиеся шаги поиска источников из `docs/progress-*.md`, сведённых в `sources/discovery-log.md`.
- Счёт по `sources/catalog.yaml` на коммите b57c44f: 317 записей, из них 304 approved, 10 rejected, 3 draft. Из одобренных 76 в разделе `epistemology`. Виды лицензий одобренных: `public-domain` 285, `public-domain-ru` 18, `cc-by-nc-sa-4.0` 1. Ещё 2 записи `public-domain-ru` отклонены, всего 20, как в аудите.
- Что наполнение и упоминания пропускают при `external_processing: false`, сверено по коду: `knowledge/filling.py` (причина `external_processing_forbidden`) и `knowledge/mentions.py` (без `resolver`, событие `knowledge.mentions.unresolved`).

## Сейчас

Ни одна задача не начата. Все ждут владельца: нужны стенд или сервер, ключи и решения по лицензиям.

## Следующий шаг

1.1 — после того как владелец выдаст стенд и ключ эмбеддингов.
