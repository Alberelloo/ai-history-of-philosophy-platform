"""Сценарии, инварианты и события: operational-alerts, backup-and-recovery, deployment."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from philograph.ops import migrate
from philograph.ops.__main__ import Scheduler
from philograph.ops.alerts import (
    Alerts,
    AlertSettings,
    BackupRule,
    BudgetRule,
    Check,
    ErrorRateRule,
    QueueRule,
    ReadinessRule,
    http_probe,
)
from philograph.ops.backup import SUFFIX, BackupError, DirStorage, _pack, retained
from philograph.platform.health import Health
from philograph.platform.lifecycle import running
from philograph.platform.queue import Queue
from philograph.platform.web import create_app

from ..search.conftest import rig  # noqa: F401
from .test_alerts import Hook, ops_engine  # noqa: F401
from .test_backup import bk, clean_schemas  # noqa: F401
from .test_deploy import Recorder

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import deploy

req = pytest.mark.req
OA = "operational-alerts"
BR = "backup-and-recovery"
DP = "deployment"
ROOT = Path(__file__).resolve().parents[2]


# --- operational-alerts --------------------------------------------------------------


@req(OA, "Правила оповещений", scenario="Сервис не готов")
def test_service_not_ready_five_minutes_alerts_with_service_and_reason(clock, events):
    hook = Hook()
    rule = ReadinessRule("search", lambda: (False, "qdrant"), 5, clock)
    alerts = Alerts({"ready:search": ("Сервис search", rule)}, hook.channel())
    alerts.evaluate()
    clock.advance(minutes=4)
    alerts.evaluate()
    assert hook.messages == [] and events.of("ops.alert.fired") == []  # пять минут ещё не прошло
    clock.advance(minutes=1)
    alerts.evaluate()
    assert len(hook.messages) == 1
    assert "search" in hook.messages[0] and "qdrant" in hook.messages[0]
    fired = events.one("ops.alert.fired")
    assert fired["rule"] == "ready:search" and "qdrant" in fired["summary"]
    events.assert_none("ops.alert.delivery_failed")


@req(OA, "Правила оповещений", scenario="Сервис не готов")
def test_not_ready_reason_comes_from_real_health_probe(clock, events):
    """Причина — имена проваленных проверок из /health/ready, а не тексты исключений."""
    answers = iter([httpx.Response(503, json={"problems": {"qdrant": "x", "database": "y"}})] * 2)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: next(answers)))
    rule = ReadinessRule("search", http_probe("http://search/health/ready", client), 0, clock)
    hook = Hook()
    Alerts({"ready:search": ("Сервис search", rule)}, hook.channel()).evaluate()
    assert "database, qdrant" in hook.messages[0]
    assert "database, qdrant" in events.one("ops.alert.fired")["summary"]


@req(OA, "Правила оповещений", invariant="короткий сбой короче порога не вызывает оповещения")
def test_short_outage_is_silent(clock, events):
    state = {"ready": False}
    hook = Hook()
    rule = ReadinessRule("search", lambda: (state["ready"], "qdrant"), 5, clock)
    alerts = Alerts({"ready:search": ("Сервис search", rule)}, hook.channel())
    alerts.evaluate()
    clock.advance(minutes=3)
    alerts.evaluate()
    state["ready"] = True
    alerts.evaluate()
    assert hook.messages == []
    events.assert_none("ops.alert.fired")
    events.assert_none("ops.alert.resolved")


@req(OA, "Канал оповещений", scenario="Повтор")
def test_every_minute_for_an_hour_is_one_alert_and_one_recovery(clock, events):
    state = {"ready": False}
    hook = Hook()
    rule = ReadinessRule("search", lambda: (state["ready"], "qdrant"), 5, clock)
    alerts = Alerts({"ready:search": ("Сервис search", rule)}, hook.channel())
    for _ in range(61):
        alerts.evaluate()
        clock.advance(minutes=1)
    assert len(hook.messages) == 1 and hook.messages[0].startswith("⚠")
    assert len(events.of("ops.alert.fired")) == 1
    state["ready"] = True
    alerts.evaluate()
    alerts.evaluate()
    assert len(hook.messages) == 2 and hook.messages[1].startswith("✓")
    assert len(events.of("ops.alert.fired")) == 1 and len(events.of("ops.alert.resolved")) == 1
    # Новый сбой после восстановления — новое оповещение, а не молчание.
    state["ready"] = False
    clock.advance(minutes=1)
    alerts.evaluate()
    clock.advance(minutes=5)
    alerts.evaluate()
    assert [m[0] for m in hook.messages] == ["⚠", "✓", "⚠"]


@req(
    OA,
    "Канал оповещений",
    invariant="недоставленное оповещение записывается в журнал, не теряя состояния",
)
def test_delivery_failure_logged_without_resending(events):
    hook = Hook(fail=True)
    alerts = Alerts({"x": ("X", lambda: Check(True, "плохо"))}, hook.channel())
    alerts.evaluate()
    alerts.evaluate()
    failed = events.one("ops.alert.delivery_failed")
    assert failed["rule"] == "x" and failed["channel"] == "webhook"
    assert events.one("ops.alert.fired")["rule"] == "x"


@req(OA, "Восстановление", scenario="Сервис вернулся")
def test_service_back_sends_recovery_with_logged_resolution(clock, events):
    answers = [503, 200]
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: (
                httpx.Response(answers[0], json={"problems": {"qdrant": ""}})
                if answers[0] != 200
                else httpx.Response(200)
            )
        )
    )
    hook = Hook()
    rule = ReadinessRule("search", http_probe("http://search/health/ready", client), 0, clock)
    alerts = Alerts({"ready:search": ("Сервис search", rule)}, hook.channel())
    alerts.evaluate()
    assert hook.messages[0].startswith("⚠")
    answers[0] = 200  # поиск снова готов
    alerts.evaluate()
    assert len(hook.messages) == 2 and hook.messages[1].startswith("✓ Сервис search: восстановлено")
    resolved = events.one("ops.alert.resolved")
    assert resolved["rule"] == "ready:search" and "готов" in resolved["summary"]
    alerts.evaluate()
    assert len(hook.messages) == 2  # повторно о восстановлении не сообщается


@req(OA, "Восстановление", invariant="восстановление только после срабатывания")
def test_no_recovery_without_prior_alert(events):
    hook = Hook()
    Alerts({"x": ("X", lambda: Check(False, "в порядке"))}, hook.channel()).evaluate()
    assert hook.messages == []
    events.assert_none("ops.alert.resolved")


def snapshot(**delta):
    return {
        "counters": [
            {"name": "http.requests", "labels": {"route": "/r", "status": s}, "value": v}
            for s, v in delta.items()
        ]
    }


def fired_summaries(events) -> list[str]:
    return [e["summary"] for e in events.of("ops.alert.fired")]


@req(OA, "Правила оповещений", invariant="доля ошибок выше порога и не меньше минимума запросов")
@pytest.mark.parametrize(
    "ok, errors, fires",
    [
        (95, 5, False),  # ровно порог 5% не «выше»
        (94, 6, True),
        (5, 5, False),  # 10 запросов — меньше минимума, доля не считается
        (0, 20, True),  # ровно минимум запросов, все ошибки
        (1, 18, False),  # 19 запросов — меньше минимума
    ],
)
def test_error_rate_threshold_and_minimum(events, ok, errors, fires):
    snaps = iter([snapshot(**{"200": 0, "500": 0}), snapshot(**{"200": ok, "500": errors})])
    rule = ErrorRateRule(lambda: next(snaps), AlertSettings())
    alerts = Alerts({"errors": ("Ошибки", rule)}, Hook().channel())
    alerts.evaluate()
    alerts.evaluate()
    assert bool(events.of("ops.alert.fired")) is fires


@req(
    OA,
    "Правила оповещений",
    invariant="перезапуск сервиса и сброс счётчиков не вызывают оповещения",
)
def test_counter_reset_is_not_an_error_spike(events):
    snaps = iter([snapshot(**{"200": 500, "500": 400}), snapshot(**{"200": 10, "500": 0})])
    rule = ErrorRateRule(lambda: next(snaps), AlertSettings())
    alerts = Alerts({"errors": ("Ошибки", rule)}, Hook().channel())
    alerts.evaluate()
    alerts.evaluate()
    events.assert_none("ops.alert.fired")


@req(
    OA,
    "Правила оповещений",
    invariant="бюджет близок к лимиту: порог включительно, без лимита не считается",
)
@pytest.mark.parametrize(
    "spent, limit, fires",
    [(1.59, 2.0, False), (1.6, 2.0, True), (5.0, 2.0, True), (9.0, 0, False), (9.0, None, False)],
)
def test_budget_threshold(events, spent, limit, fires):
    rule = BudgetRule(
        lambda: [{"budget": "site", "period": "month", "spent_usd": spent, "limit_usd": limit}],
        AlertSettings(),
    )
    Alerts({"budget": ("Бюджет", rule)}, Hook().channel()).evaluate()
    assert bool(events.of("ops.alert.fired")) is fires
    if fires:
        assert "site за месяц" in fired_summaries(events)[0]


@req(OA, "Правила оповещений", invariant="самая старая задача очереди старше порога")
def test_queue_rule_boundary_and_alert(ops_engine, clock, events):
    queue = Queue(ops_engine, clock)
    settings = AlertSettings(queue_age_minutes=30)
    alerts = Alerts(
        {"queue": ("Очередь", QueueRule(ops_engine, settings, clock))}, Hook().channel()
    )
    alerts.evaluate()
    events.assert_none("ops.alert.fired")  # очередь пуста
    queue.enqueue("search:source.published", {"x": 1}, key="k1")
    clock.advance(minutes=30)
    alerts.evaluate()
    events.assert_none("ops.alert.fired")  # ровно порог — ещё не «старше»
    clock.advance(minutes=1)
    alerts.evaluate()
    assert "задач в очереди: 1" in events.one("ops.alert.fired")["summary"]


@req(OA, "Правила оповещений", invariant="неудачная копия и устаревшая копия вызывают оповещение")
def test_backup_rule_stale_copy(bk, events):
    bk.backups.run()
    rule = BackupRule(bk.ops, AlertSettings(backup_age_hours=26), bk.clock)
    assert not rule().firing
    bk.clock.advance(hours=27)
    alerts = Alerts({"backup": ("Копии", rule)}, Hook().channel())
    alerts.evaluate()
    assert "последней удачной копии" in events.one("ops.alert.fired")["summary"]


@req(
    OA,
    "Без персональных данных",
    invariant="в оповещении нет текстов вопросов и данных посетителей",
)
def test_alert_never_carries_labels_or_exception_text_from_visitors(events):
    secret = "что я думаю о Канте? мой email a@b.ru"
    counters = {
        "counters": [
            {
                "name": "http.requests",
                "labels": {"route": f"/api/assistant/{secret}", "status": "502", "q": secret},
                "value": 40,
            }
        ]
    }
    rule = ErrorRateRule(lambda: counters, AlertSettings())
    hook = Hook()
    alerts = Alerts(
        {
            "errors": ("Ошибки", rule),
            "boom": ("Правило", lambda: (_ for _ in ()).throw(ValueError(secret))),
        },
        hook.channel(),
    )
    alerts.evaluate()
    counters["counters"][0]["value"] = 80
    alerts.evaluate()
    assert len(hook.messages) == 2  # ошибки ассистента и сбой самого правила
    for text in hook.messages + fired_summaries(events):
        assert secret not in text and "a@b.ru" not in text and "Канте" not in text
    assert any("ValueError" in s for s in fired_summaries(events))  # вид ошибки виден
    assert any("502" in s for s in fired_summaries(events))  # и вид ошибок ассистента


# --- backup-and-recovery -------------------------------------------------------------


@req(
    BR,
    "Ежедневные копии",
    invariant="правило хранения: неделя по дням, месяц по неделям, год по месяцам",
    nolog="чистая функция выбора копий",
)
def test_retention_boundaries():
    now = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)

    def name(**delta):
        return f"{(now - timedelta(**delta)):%Y%m%dT%H%M%SZ}{SUFFIX}"

    assert retained([], now) == set()
    ancient = name(days=800)
    assert retained([ancient], now) == {ancient}  # последняя копия остаётся всегда
    morning, evening = name(days=1, hours=-2), name(days=1, hours=2)  # два за один день
    keep = retained([morning, evening], now)
    assert keep == {morning}  # из дня остаётся самая свежая
    older_than_year = [name(days=d) for d in (10, 400)]
    assert name(days=400) not in retained([*older_than_year, name(days=1)], now)


@req(
    BR,
    "Ежедневные копии",
    invariant="копирование раз в сутки по расписанию, неудача не останавливает планировщик",
)
def test_scheduler_survives_failed_backup_and_still_alerts(bk, events):
    calls = []

    def failing():
        calls.append(1)
        raise BackupError("хранилище недоступно")

    bk.clock.set(datetime(2026, 11, 4, 3, 5, tzinfo=UTC))
    evaluated = []
    scheduler = Scheduler(bk.ops, lambda: evaluated.append(1), failing, None, bk.clock)
    assert scheduler.tick() == ["alerts", "backup"]
    assert calls == [1] and evaluated == [1]
    bk.clock.advance(minutes=1)
    assert scheduler.tick() == ["alerts"]  # без нового итога копия не запускается дважды
    assert calls == [1]


@req(
    BR,
    "Шифрование копий",
    invariant="ключ хранится вне копий; копия с изменённым содержимым не открывается",
)
def test_tampered_or_keyless_backup_unreadable(bk, events, monkeypatch):
    name = bk.backups.run()
    stored = (bk.dir / name).read_bytes()
    flipped = bytearray(stored)
    flipped[len(flipped) // 2] ^= 0x01
    (bk.dir / name).write_bytes(bytes(flipped))
    with pytest.raises(BackupError):
        bk.backups.open(name)
    with pytest.raises(BackupError):
        bk.backups.verify(bk.verify_url)
    assert events.one("ops.backup.verify_failed")["name"] == name
    assert {p.suffix for p in bk.dir.iterdir()} == {SUFFIX}
    monkeypatch.delenv("PHILOGRAPH_BACKUP_KEY", raising=False)
    from philograph.ops.backup import from_env

    with pytest.raises(BackupError, match="PHILOGRAPH_BACKUP_KEY"):
        from_env({"PHILOGRAPH_DATABASE_URL": bk.database_url})


def _forged(bk, edit) -> str:
    """Подменённая копия: заново упакована и зашифрована тем же ключом."""
    name = bk.backups.latest()
    content = bk.backups.open(name)
    manifest = json.loads(content["manifest.json"])
    content = edit(content, manifest)
    forged = f"{(bk.clock.now() + timedelta(days=1)):%Y%m%dT%H%M%SZ}{SUFFIX}"
    bk.backups.storage.put(forged, bk.backups.fernet.encrypt(_pack(content)))
    return forged


@req(BR, "Проверка восстановления", invariant="миграции совпадают с копией")
def test_verify_fails_when_migrations_differ(bk, events):
    bk.backups.run()

    def edit(content, manifest):
        manifest["migrations"]["library"] = [*manifest["migrations"]["library"], 9999]
        return {**content, "manifest.json": json.dumps(manifest).encode()}

    forged = _forged(bk, edit)
    with pytest.raises(BackupError, match="миграций"):
        bk.backups.verify(bk.verify_url)
    failed = events.one("ops.backup.verify_failed")
    assert failed["name"] == forged and "миграций" in failed["reason"]
    events.assert_none("ops.backup.verified")
    assert BackupRule(bk.ops, AlertSettings(), bk.clock)().firing


@req(BR, "Проверка восстановления", invariant="основные таблицы не пусты")
def test_verify_fails_when_main_tables_empty(bk, events):
    bk.backups.run()

    def edit(content, manifest):
        manifest["counts"]["library.sources"] = 0
        manifest["counts"]["library.versions"] = 0
        content = {k: v for k, v in content.items()}
        content["data/library.sources.jsonl"] = b""
        content["data/library.versions.jsonl"] = b""
        return {**content, "manifest.json": json.dumps(manifest).encode()}

    _forged(bk, edit)
    with pytest.raises(BackupError, match="пусты"):
        bk.backups.verify(bk.verify_url)
    assert "пусты" in events.one("ops.backup.verify_failed")["reason"]
    events.assert_none("ops.backup.verified")


@req(BR, "Проверка восстановления", scenario="Плановая проверка")
def test_scheduled_verification_runs_weekly_and_reports(bk, events):
    bk.clock.set(datetime(2026, 11, 4, 3, 5, tzinfo=UTC))
    scheduler = Scheduler(
        bk.ops, lambda: None, bk.backups.run, lambda: bk.backups.verify(bk.verify_url), bk.clock
    )
    assert scheduler.tick() == ["alerts", "backup"]
    bk.clock.advance(minutes=1)
    assert scheduler.tick() == ["alerts", "verify"]
    assert events.one("ops.backup.verified")["rows"] > 0
    bk.clock.advance(days=3)
    assert "verify" not in scheduler.tick()  # раз в неделю, не чаще
    bk.clock.advance(days=5)
    assert "verify" in scheduler.tick()
    assert len(events.of("ops.backup.verified")) == 2


@req(
    BR,
    "Неудачная копия",
    invariant="неудача не оставляет копии и сменяется восстановлением оповещения",
)
def test_failed_backup_alert_resolves_after_success(bk, events):
    good = bk.backups.run()
    bk.clock.advance(hours=1)
    working = bk.backups.storage
    bk.backups.storage = DirStorage(bk.dir / "нет")
    with pytest.raises(BackupError):
        bk.backups.run()
    failed = events.one("ops.backup.failed")
    assert failed["error_kind"] == "BackupError" and failed["reason"]
    assert [p.name for p in bk.dir.glob(f"*{SUFFIX}")] == [good]  # частичной копии нет
    hook = Hook()
    alerts = Alerts(
        {"backup": ("Копии", BackupRule(bk.ops, AlertSettings(), bk.clock))}, hook.channel()
    )
    alerts.evaluate()
    bk.backups.storage = working
    bk.clock.advance(hours=1)
    bk.backups.run()
    alerts.evaluate()
    assert [m[0] for m in hook.messages] == ["⚠", "✓"]
    assert events.one("ops.alert.resolved")["rule"] == "backup"
    assert len(events.of("ops.backup.completed")) == 2


@req(BR, "Восстановление производных данных", scenario="Потеря векторной базы")
def test_vector_store_loss_rebuilt_by_reindex_and_cache_not_in_backup(rig, events):
    rig.publish("ru")
    rig.indexer.vectors.client.delete_collection(rig.indexer.active_collection)
    lexical = rig.search("привычка ума")
    assert lexical["results"] and lexical["semantic_used"] is False  # по словам работает
    totals = rig.indexer.reindex()
    assert totals["indexed"] > 0 and totals["embedded"] > 0
    assert events.one("search.index.rebuilt")["embedded"] == totals["embedded"]
    semantic = rig.search("из прошлого нельзя вывести будущее")
    assert semantic["semantic_used"] is True and semantic["results"]


# --- deployment ----------------------------------------------------------------------


def _compose(name: str) -> dict:
    return yaml.load((ROOT / name).read_text(encoding="utf-8"), Loader=deploy._ComposeLoader)


@req(DP, "Внутренние части не видны снаружи", invariant="публикуются только порты HTTP и HTTPS")
def test_prod_compose_publishes_only_caddy_80_443():
    base, prod = _compose("compose.yaml"), _compose("compose.prod.yaml")
    exposed = {n: s["ports"] for n, s in base["services"].items() if s.get("ports")}
    # В базовом файле наружу смотрит только шлюз, и боевой файл сбрасывает его порты.
    assert set(exposed) <= {"gateway"}
    assert prod["services"]["gateway"]["ports"] == []
    assert prod["services"]["caddy"]["ports"] == ["80:80", "443:443"]
    for forbidden in ("postgres", "qdrant", "llm", "worker", "ops"):
        assert not base["services"].get(forbidden, {}).get("ports")
        assert not prod["services"].get(forbidden, {}).get("ports")


@req(
    DP,
    "Публичный адрес по HTTPS",
    scenario="HTTP",
    nolog="статическая проверка Caddyfile: события журнала нет по природе",
)
def test_caddyfile_site_is_domain_with_automatic_https():
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    code = "\n".join(l for line in caddyfile.splitlines() if not line.lstrip().startswith("#"))
    assert code.lstrip().startswith("{$PHILOGRAPH_DOMAIN} {")
    for off in ("auto_https off", "disable_redirects", "http://", "tls internal", "skip_install"):
        assert off not in code  # перенаправление и сертификаты у Caddy не отключены
    assert code.count("reverse_proxy") == 1


@req(
    DP,
    "Автоматический перезапуск",
    invariant="все долгоживущие сервисы перезапускаются автоматически",
)
def test_all_long_running_services_have_restart_policy(events):
    base = _compose("compose.yaml")
    prod = _compose("compose.prod.yaml")
    services = {
        **base["services"],
        **{k: {**base["services"].get(k, {}), **v} for k, v in prod["services"].items()},
    }
    one_shot = {"migrate", "seed"}
    for name, service in services.items():
        expected = "no" if name in one_shot else "unless-stopped"
        assert service.get("restart") == expected, name
    assert events.names() == []  # статическая проверка конфигурации не пишет событий


@req(DP, "Автоматический перезапуск", invariant="штатная остановка не считается перезапуском")
def test_clean_stop_leaves_no_restart_marker(tmp_path, events):
    for _ in range(2):
        with running("assistant", "1.0", tmp_path):
            assert (tmp_path / "assistant.running").exists()
        assert not (tmp_path / "assistant.running").exists()
    assert events.of("service.restarted") == []
    assert [e["restarted"] for e in events.of("service.started")] == [False, False]
    assert len(events.of("service.stopped")) == 2


class _Broken:
    schema = "broken"

    def upgrade(self, engine):
        raise RuntimeError("DROP TABLE нечто")


@req(DP, "Обновление с миграциями", scenario="Неудачная миграция")
def test_failed_migration_event_and_operator_message(
    tmp_path, database_url, events, capsys, monkeypatch
):
    real = migrate.all_migrations()
    monkeypatch.setattr(migrate, "all_migrations", lambda: [real[0], _Broken()])
    with pytest.raises(RuntimeError):
        migrate.upgrade_all(database_url)
    failed = events.one("ops.migrations.failed")
    assert failed["schema"] == "broken" and failed["error_kind"] == "RuntimeError"
    events.assert_none("ops.migrations.applied")  # итог «применены» не пишется
    # Сценарий обновления: миграции упали — оператор видит ошибку, сервисы не тронуты.
    state = tmp_path / "state.json"
    deploy.write_state({"current": "1.4.0", "previous": "1.3.0"}, state)
    runner = Recorder(fail_on="migrate")
    assert deploy.update("1.5.0", runner, state) == 1
    err = capsys.readouterr().err
    assert "миграции не применились" in err and "прежняя версия" in err
    assert runner.steps() == ["build", "run"]
    assert deploy.read_state(state) == {"current": "1.4.0", "previous": "1.3.0"}


@req(
    DP, "Обновление с миграциями", invariant="миграции применяются до запуска новых версий сервисов"
)
def test_migrations_run_before_services_start(tmp_path):
    state = tmp_path / "state.json"
    deploy.write_state({"current": "1.4.0", "previous": None}, state)
    runner = Recorder()
    assert deploy.update("1.5.0", runner, state) == 0
    commands = [c for c, _ in runner.commands]
    migrate_at = next(i for i, c in enumerate(commands) if "migrate" in c)
    up_at = next(i for i, c in enumerate(commands) if "up" in c)
    assert migrate_at < up_at
    broken = Recorder(fail_on="build")
    assert deploy.update("1.6.0", broken, state) == 1
    assert broken.steps() == ["build"]  # ни миграций, ни запуска
    assert deploy.read_state(state)["current"] == "1.5.0"


@req(
    DP,
    "Откат обновления",
    scenario="Откат",
    nolog="сценарий развёртывания событий не пишет: проверяются состояние, команды и сообщения",
)
def test_update_with_unready_services_then_one_command_rollback(tmp_path, capsys):
    state = tmp_path / "state.json"
    deploy.write_state({"current": "1.4.0", "previous": "1.3.0"}, state)
    assert deploy.update("1.5.0", Recorder(fail_on="up"), state) == 1
    assert "rollback" in capsys.readouterr().err  # оператору подсказана команда отката
    assert deploy.read_state(state) == {"current": "1.5.0", "previous": "1.4.0"}
    runner = Recorder()
    assert deploy.rollback(runner, state) == 0  # одна команда
    assert len(runner.commands) == 1 and runner.commands[0][1] == {"PHILOGRAPH_VERSION": "1.4.0"}
    assert "--wait" in runner.commands[0][0]
    assert "откат выполнен: работает версия 1.4.0" in capsys.readouterr().out
    assert deploy.read_state(state) == {"current": "1.4.0", "previous": "1.5.0"}


@req(
    DP,
    "Откат обновления",
    invariant="неудавшийся откат не меняет состояние",
    nolog="сценарий развёртывания событий не пишет",
)
def test_failed_rollback_keeps_state(tmp_path, capsys):
    state = tmp_path / "state.json"
    deploy.write_state({"current": "1.5.0", "previous": "1.4.0"}, state)
    assert deploy.rollback(Recorder(fail_on="up"), state) == 1
    assert deploy.read_state(state) == {"current": "1.5.0", "previous": "1.4.0"}
    assert "не стала готова" in capsys.readouterr().err


@req(
    DP,
    "Версия в журнале",
    invariant="каждый сервис сообщает версию при старте и в проверках состояния",
)
@pytest.mark.parametrize(
    "service", ["gateway", "library", "search", "assistant", "knowledge", "llm"]
)
def test_each_service_reports_version(service, events):
    app = create_app(service, "2.7.1", Health(service, "2.7.1"))
    with TestClient(app) as client:
        started = events.one("service.started")
        assert started["version"] == "2.7.1" and started["service"] == service
        for probe in ("live", "ready"):
            assert client.get(f"/health/{probe}").json()["version"] == "2.7.1"
    assert events.one("service.stopped")["version"] == "2.7.1"
