# Эксплуатация публичного сервера

Что делать оператору: первый запуск, обновление, откат, резервные копии, восстановление, оповещения. Устройство описано в [design.md](../../openspec/changes/add-production-readiness/design.md) изменения `add-production-readiness`.

## Первый запуск

1. Скопировать `.env.example` в `.env` и заполнить:
   - `POSTGRES_PASSWORD`, `PHILOGRAPH_VISITOR_SECRET`, `PHILOGRAPH_INTERNAL_TOKEN` — длинные случайные строки;
   - `PHILOGRAPH_DOMAIN` — домен сайта, его DNS должен указывать на сервер;
   - `PHILOGRAPH_BACKUP_KEY` — ключ шифрования копий (команда в `.env.example`). Сохраните его в менеджере паролей отдельно от сервера: без ключа копию не прочитать;
   - `PHILOGRAPH_BACKUP_DIR` — каталог смонтированного внешнего хранилища (rclone, sshfs) или `PHILOGRAPH_BACKUP_TARGET=s3://bucket/prefix`;
   - канал оповещений: `PHILOGRAPH_ALERT_TELEGRAM_TOKEN` и `PHILOGRAPH_ALERT_TELEGRAM_CHAT` либо `PHILOGRAPH_ALERT_WEBHOOK`.
2. Запустить: `python scripts/deploy.py update <версия>`, например `update 2026.11.1`. Команда собирает образ, применяет миграции и поднимает сервисы.

Снаружи открыты только порты 80 и 443. Caddy сам выпускает и обновляет сертификат и перенаправляет HTTP на HTTPS.

## Обновление и откат

```bash
git pull
python scripts/deploy.py update 2026.11.2   # миграции, затем новые версии сервисов
python scripts/deploy.py status             # текущая и прежняя версии
python scripts/deploy.py rollback           # вернуть прежнюю версию
```

Если миграции не применились, обновление останавливается, и продолжает работать прежняя версия: ошибка видна в выводе команды и в журнале (`ops.migrations.failed`). Откат возвращает прежний образ. Миграции только добавляют таблицы и столбцы, поэтому прежний код работает с новой схемой.

## Резервные копии

Сервис `ops` делает копию каждую ночь (`PHILOGRAPH_BACKUP_HOUR`, по умолчанию 03:00 UTC) и раз в неделю проверяет восстановление в отдельной базе `philograph_verify`. Хранятся ежедневные копии за неделю, по одной на неделю за месяц и по одной на месяц за год.

Вручную:

```bash
docker compose -f compose.yaml -f compose.prod.yaml exec ops python -m philograph.ops.backup run
docker compose -f compose.yaml -f compose.prod.yaml exec ops python -m philograph.ops.backup verify
```

### Восстановление после потери сервера

1. Поднять новый сервер, заполнить `.env` тем же `PHILOGRAPH_BACKUP_KEY` и подключить хранилище копий.
2. `python scripts/deploy.py update <версия>`.
3. Развернуть последнюю копию (база и файлы источников):
   `docker compose -f compose.yaml -f compose.prod.yaml run --rm ops python -m philograph.ops.backup restore`.
   Конкретная копия — её имя последним аргументом.
4. Восстановить индексы поиска из библиотеки:
   `docker compose -f compose.yaml -f compose.prod.yaml exec search python -c "import httpx; print(httpx.post('http://127.0.0.1:8002/v1/internal/reindex', timeout=None).json())"`.
   Поиск по словам работает и до конца переиндексации. Кэш ответов модели не восстанавливается, он наполнится сам.

## Оповещения

Правила и пороги по умолчанию (меняются через `PHILOGRAPH_ALERT_RULES` в JSON):

| Правило | Срабатывает, когда |
|---|---|
| Сервис `<имя>` | сервис не готов дольше 5 минут |
| Ошибки на сайте | доля ответов 5xx шлюза выше 5 % (от 20 запросов за минуту) |
| Бюджет на модели | расход за сутки или месяц достиг 80 % лимита |
| Очередь задач | самая старая ожидающая задача старше 30 минут |
| Резервные копии | копия не создалась, последней удачной больше 26 часов или проверка восстановления не прошла |

На каждое срабатывание приходит одно сообщение и одно — когда условие перестало выполняться. В сообщениях только числа, названия сервисов и виды ошибок, данных посетителей нет.

## Лимиты

Лимиты платных операций на посетителя задаются переменными `PHILOGRAPH_LIMIT_ASK`, `PHILOGRAPH_LIMIT_GRAPH` и `PHILOGRAPH_LIMIT_DESCRIPTION` в формате «в час/в сутки», по умолчанию `20/100`, `30/200` и `60/300`. Общая частота задаётся `PHILOGRAPH_RATE_PER_SECOND` и `PHILOGRAPH_RATE_BURST`. Срабатывания видны в журнале шлюза как `gateway.limit.triggered`.
