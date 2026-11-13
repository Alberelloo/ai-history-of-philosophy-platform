"""Требования entity-portraits и изменённое entity-cards «Портреты в карточке»: серверная часть.

Модель, порядок, видимость, раздача файлов и путь через шлюз. Отбор из Wikidata/Commons,
лицензии и операторские маршруты — в других модулях и задачах.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport
from sqlalchemy import select

from philograph.gateway.app import build_app as gateway_app
from philograph.knowledge import schema as ks
from philograph.knowledge.app import build_app
from philograph.knowledge.cards import Cards
from philograph.knowledge.portraits import Portraits
from philograph.operator import access as oa
from philograph.operator.access import ActionLog, OperatorAuth, hash_password
from philograph.platform.db import make_engine
from philograph.platform.files import FileStore

req = pytest.mark.req
EP = "entity-portraits"

PNG = b"\x89PNG\r\n\x1a\nrest"


@pytest.fixture
def portraits(onto, tmp_path, clock):
    return Portraits(onto.statements.engine, FileStore(tmp_path / "files"), clock=clock)


def make_draft(portraits, entity_id, phash, **overrides):
    """Черновик с фиктивным file_id — для проверки порядка и видимости, без файла в хранилище."""
    return portraits.add_draft(
        entity_id,
        file_id=overrides.pop("file_id", f"file_{phash}"),
        width=100,
        height=120,
        author="Автор",
        year="1800",
        license="pd",
        license_url="https://example.org/license",
        source_url=f"https://commons.wikimedia.org/wiki/File:{phash}",
        origin=f"commons:File:{phash}",
        phash=phash,
        **overrides,
    )


def make_file_draft(portraits, entity_id, phash, data=PNG):
    """Черновик с реальным файлом в FileStore — для проверки раздачи."""
    file_id = portraits.files.put(data)
    portrait_id = make_draft(portraits, entity_id, phash, file_id=file_id)
    return portrait_id, file_id


def approved(portraits, entity_id, phash, data=PNG):
    portrait_id, file_id = make_file_draft(portraits, entity_id, phash, data)
    portraits.approve(portrait_id, "operator")
    return portrait_id, file_id


def positions(engine, entity_id):
    with engine.begin() as conn:
        rows = conn.execute(
            select(ks.portraits.c.id, ks.portraits.c.position)
            .where(ks.portraits.c.entity_id == entity_id)
            .order_by(ks.portraits.c.position, ks.portraits.c.id)
        ).all()
    return dict(rows)


# --- миграция ------------------------------------------------------------------------


@req(EP, "Хранение и раздача изображений")
def test_migration_7_adds_portraits_and_keeps_old_data(tmp_path):
    """Миграция 7 накатывается на базу версии 6: таблица добавлена, старые данные читаются."""
    from sqlalchemy import inspect

    engine = make_engine(f"sqlite:///{(tmp_path / 'p.db').as_posix()}", [ks.SCHEMA])
    with engine.begin() as conn:
        # База версии 6: миграции 1–6 помечены применёнными, старая таблица с данными на месте.
        ks.migrations._version_table.create(conn, checkfirst=True)
        for version in range(1, 7):
            conn.execute(
                ks.migrations._version_table.insert().values(version=version, name=f"v{version}")
            )
        ks.metadata.create_all(conn, tables=[ks.entities])
        conn.execute(
            ks.entities.insert().values(id="e_old", type="person", primary={}, redirect_to=None)
        )
    applied = ks.migrations.upgrade(engine)
    assert applied == [7]
    with engine.begin() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("portraits", schema=ks.SCHEMA)}
        old = (
            conn.execute(select(ks.entities.c.id).where(ks.entities.c.id == "e_old"))
            .scalars()
            .all()
        )
    assert {
        "id",
        "entity_id",
        "file_id",
        "width",
        "height",
        "author",
        "year",
        "license",
        "license_url",
        "source_url",
        "origin",
        "phash",
        "position",
        "status",
        "hidden",
        "created_at",
    } <= columns
    assert old == ["e_old"]
    assert ks.migrations.latest() == 7


# --- черновики и порядок -------------------------------------------------------------


@req(EP, "Отбор портретов персоны")
def test_add_draft_appends_and_skips_duplicate(onto, portraits):
    kant = onto.person("Кант")
    first = make_draft(portraits, kant, "ph1")
    second = make_draft(portraits, kant, "ph2")
    assert make_draft(portraits, kant, "ph1") == first  # повтор по phash не добавляет строку
    assert positions(onto.statements.engine, kant) == {first: 0, second: 1}


@req(EP, "Ответ карточки с портретами")
def test_visible_limit_of_seven(onto, portraits):
    kant = onto.person("Кант")
    ids = [make_draft(portraits, kant, f"ph{i}") for i in range(8)]
    for portrait_id in ids:
        portraits.approve(portrait_id, "operator")
    visible = portraits.visible(kant)
    assert len(visible) == 7
    assert [v["url"] for v in visible] == [f"/api/knowledge/v1/portraits/{i}" for i in ids[:7]]


@req(EP, "Хранение и раздача изображений")
def test_visible_skips_draft_and_hidden_orders_by_position(onto, portraits):
    kant = onto.person("Кант")
    a = make_draft(portraits, kant, "a")
    b = make_draft(portraits, kant, "b")
    c = make_draft(portraits, kant, "c")
    for portrait_id in (a, b, c):
        portraits.approve(portrait_id, "operator")
    portraits.make_main(c, "operator")  # главное первым
    portraits.hide(b, "operator")  # скрытое не отдаётся
    visible = portraits.visible(kant)
    assert [v["url"] for v in visible] == [
        f"/api/knowledge/v1/portraits/{c}",
        f"/api/knowledge/v1/portraits/{a}",
    ]
    # У скрытого и черновика сведений для раздачи нет.
    assert portraits.visible(kant)  # черновиков нет среди approved


@req(EP, "Проверка оператором")
def test_make_main_reorders_without_losing(onto, portraits):
    kant = onto.person("Кант")
    a = make_draft(portraits, kant, "a")
    b = make_draft(portraits, kant, "b")
    c = make_draft(portraits, kant, "c")
    portraits.make_main(c, "operator")
    assert positions(onto.statements.engine, kant) == {c: 0, a: 1, b: 2}


# --- карточка ------------------------------------------------------------------------


def expected(portrait_id, phash):
    return {
        "url": f"/api/knowledge/v1/portraits/{portrait_id}",
        "width": 100,
        "height": 120,
        "author": "Автор",
        "year": "1800",
        "license": "pd",
        "license_url": "https://example.org/license",
        "source_url": f"https://commons.wikimedia.org/wiki/File:{phash}",
    }


@req(EP, "Ответ карточки с портретами")
def test_card_contains_portraits(onto, portraits):
    kant = onto.person("Кант")
    a = make_draft(portraits, kant, "a")
    b = make_draft(portraits, kant, "b")
    portraits.approve(a, "operator")
    portraits.approve(b, "operator")
    card = Cards(onto.statements, portraits=portraits).card(kant)
    assert card["portraits"] == [expected(a, "a"), expected(b, "b")]


@req(EP, "Ответ карточки с портретами")
def test_card_without_portraits_is_empty(onto, portraits):
    kant = onto.person("Кант")
    card = Cards(onto.statements, portraits=portraits).card(kant)
    assert card["portraits"] == []


@req(EP, "Ответ карточки с портретами")
def test_card_non_person_has_no_portraits(onto, portraits):
    concept = onto.thing("concept", "Причинность")
    make_draft(portraits, concept, "ph")
    card = Cards(onto.statements, portraits=portraits).card(concept)
    assert card["portraits"] == []


# --- раздача -------------------------------------------------------------------------


@req(EP, "Хранение и раздача изображений")
def test_delivery_approved_returns_file_with_headers(onto, portraits):
    kant = onto.person("Кант")
    portrait_id, file_id = approved(portraits, kant, "png")
    client = TestClient(build_app(onto.statements, portraits=portraits))
    response = client.get(f"/v1/portraits/{portrait_id}")
    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["etag"] == file_id
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


@req(EP, "Хранение и раздача изображений")
def test_delivery_404_for_draft_hidden_and_missing(onto, portraits):
    kant = onto.person("Кант")
    draft_id, _ = make_file_draft(portraits, kant, "draft")
    hidden_id, _ = make_file_draft(portraits, kant, "hidden")
    portraits.approve(hidden_id, "operator")
    portraits.hide(hidden_id, "operator")
    client = TestClient(build_app(onto.statements, portraits=portraits))
    assert client.get(f"/v1/portraits/{draft_id}").status_code == 404
    assert client.get(f"/v1/portraits/{hidden_id}").status_code == 404
    assert client.get("/v1/portraits/999999").status_code == 404


@req(EP, "Хранение и раздача изображений")
def test_gateway_delivers_portrait(onto, portraits):
    """Путь через шлюз: ``/api/knowledge/v1/portraits/{id}`` доходит до сервиса знаний."""
    kant = onto.person("Кант")
    portrait_id, _ = approved(portraits, kant, "gw")
    knowledge = build_app(onto.statements, portraits=portraits)
    app = gateway_app({"knowledge": "http://knowledge"}, transport=ASGITransport(app=knowledge))
    response = TestClient(app).get(f"/api/knowledge/v1/portraits/{portrait_id}")
    assert response.status_code == 200
    assert response.content == PNG


@req(EP, "Проверка оператором")
def test_portrait_review_requires_operator(onto, portraits, clock):
    """Очередь проверки портретов доступна только вошедшему оператору."""
    auth = OperatorAuth(hash_password("пароль", iterations=1000), clock=clock)
    client = TestClient(build_app(onto.statements, portraits=portraits, auth=auth))
    make_draft(portraits, onto.person("Кант"), "a")
    assert client.get("/v1/review/portraits").status_code == 404  # без сессии
    assert client.post("/v1/operator/login", json={"password": "пароль"}).status_code == 200
    assert client.get("/v1/review/portraits").status_code == 200


@req(EP, "Проверка оператором")
def test_portrait_review_actions_and_journal(onto, portraits, clock):
    """Подтверждение, скрытие, возврат и назначение главным; каждое действие — в журнале."""
    engine = onto.statements.engine
    actions = ActionLog(engine, clock)
    auth = OperatorAuth(hash_password("пароль", iterations=1000), clock=clock)
    client = TestClient(build_app(onto.statements, portraits=portraits, auth=auth, actions=actions))
    client.post("/v1/operator/login", json={"password": "пароль"})
    kant = onto.person("Кант", "1724", "1804")
    first, _ = make_file_draft(portraits, kant, "a")
    second, _ = make_file_draft(portraits, kant, "b")

    queue = client.get("/v1/review/portraits").json()
    assert [row["id"] for row in queue] == [first, second]
    assert queue[0]["label"] == "Кант" and queue[0]["license"] == "pd"

    assert client.post(f"/v1/review/portraits/{first}?action=approve").json() == {"status": "ok"}
    assert client.post(f"/v1/review/portraits/{second}?action=approve").json() == {"status": "ok"}
    assert [r["url"] for r in portraits.visible(kant)] == [
        f"/api/knowledge/v1/portraits/{first}",
        f"/api/knowledge/v1/portraits/{second}",
    ]

    assert client.post(f"/v1/review/portraits/{first}?action=hide").json() == {"status": "ok"}
    assert [r["url"] for r in portraits.visible(kant)] == [f"/api/knowledge/v1/portraits/{second}"]
    hidden = client.get("/v1/review/portraits?status=hidden").json()
    assert [row["id"] for row in hidden] == [first]

    assert client.post(f"/v1/review/portraits/{first}?action=show").json() == {"status": "ok"}
    assert client.post(f"/v1/review/portraits/{second}?action=main").json() == {"status": "ok"}
    assert [r["url"] for r in portraits.visible(kant)] == [
        f"/api/knowledge/v1/portraits/{second}",
        f"/api/knowledge/v1/portraits/{first}",
    ]

    with engine.begin() as conn:
        logged = conn.execute(select(oa.actions.c.action, oa.actions.c.target)).all()
    assert ("portrait_approve", str(first)) in logged
    assert ("portrait_main", str(second)) in logged

    assert client.post("/v1/review/portraits/999999?action=approve").status_code == 404
    assert client.post(f"/v1/review/portraits/{first}?action=explode").status_code == 400
