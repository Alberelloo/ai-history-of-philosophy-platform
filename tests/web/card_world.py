"""Данные для браузерных тестов карточек (redesign-entity-cards): миры на ``stack.world``.

Утверждения записываются как у импорта: без явного статуса и происхождения утверждение с
атрибуцией источника — «по источникам» (ручная запись по умолчанию стала бы проверенной).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from philograph.knowledge import schema as t
from philograph.knowledge.dates import parse
from philograph.knowledge.entities import normalize
from philograph.knowledge.statements import Attribution, Evidence, Provenance

from ..knowledge.test_cards_redesign_unit import _artifact


def src(who: str = "s_a") -> list[Attribution]:
    return [Attribution("source", who)]


def add(world, subject: str, type_: str, **kw) -> str:
    sourced = any(a.who_kind == "source" for a in kw.get("attributions") or [])
    plain = "provenance" not in kw and not kw.get("evidence")
    if sourced and plain and kw.get("status") in (None, "sourced"):
        kw["provenance"] = Provenance("imported")
    return world.statements.add(subject, type_, **kw)


def lived(world, person: str, place: str, role: str | None = None, **kw) -> str:
    q = {"place_role": role} if role else {}
    return add(world, person, "lived_in", obj=place, qualifiers=q, attributions=src(), **kw)


def place(world, name: str, lat: float | None = None, lon: float | None = None) -> str:
    pid = world.thing("place", name)
    if lat is not None:
        add(world, pid, "coordinates", value={"lat": lat, "lon": lon}, attributions=src())
    return pid


def rename(world, entity: str, label: str) -> str:
    """Название, которое правила названий уже не пропустят (данные до правил): меняется в базе."""
    with world.engine.begin() as conn:
        conn.execute(
            t.names.update()
            .where(t.names.c.entity_id == entity)
            .values(text=label, normalized=normalize(label))
        )
    return entity


def legacy_person(world, label: str, birth: str, death: str) -> str:
    """Персона с названием, которое правила названий уже не пропустят."""
    return rename(world, world.person("Прежняя Запись", birth, death), label)


_POLITIES = Path(tempfile.mkdtemp(prefix="philograph-card-polities-")) / "polities.sqlite"


def polities_env() -> dict[str, str]:
    """Артефакт образований для стенда: Англия вокруг Лондона, Пруссия вокруг Кёнигсберга."""
    if not _POLITIES.exists():
        _artifact(
            _POLITIES,
            [
                ("england", "Королевство Англия", 1600, 1707, (-6, 50, 2, 56), 20.0),
                ("prussia", "Королевство Пруссия", 1701, 1918, (19, 53, 23, 56), 10.0),
            ],
        )
    return {"PHILOGRAPH_POLITIES_DB": str(_POLITIES)}


_DAMAGED = Path(tempfile.mkdtemp(prefix="philograph-card-polities-damaged-")) / "polities.sqlite"


def damaged_polities_env() -> dict[str, str]:
    """Артефакт образований без таблицы строк: слой открывается, поиск в точке падает."""
    if not _DAMAGED.exists():
        import sqlite3

        _artifact(
            _DAMAGED, [("prussia", "Королевство Пруссия", 1701, 1918, (19, 53, 23, 56), 10.0)]
        )
        conn = sqlite3.connect(_DAMAGED)
        conn.execute("DROP TABLE polity_rows")
        conn.commit()
        conn.close()
    return {"PHILOGRAPH_POLITIES_DB": str(_DAMAGED)}


def locke(world) -> dict[str, str]:
    """Локк: роль, пять мест (Лондон — основное), девять трудов с датами."""
    p = world.person("Джон Локк", "1632", "1704")
    add(world, p, "person_role", value="philosopher", attributions=src())
    london = place(world, "Лондон", 51.51, -0.13)
    lived(world, p, london, "activity", status="verified")
    lived(world, p, place(world, "Рингтон"), "birth")
    for name in ("Оксфорд", "Париж", "Амстердам"):
        lived(world, p, place(world, name), "residence")
    works = []
    for i, name in enumerate(
        ["Опыт о разумении", "Два трактата", "Письмо о терпимости", "О воспитании",
         "Элементы естествознания", "Рассуждение о чудесах", "Мысли о воспитании",
         "Парафраз посланий", "Разумность христианства"]
    ):  # fmt: skip
        w = world.thing("work", name, str(1689 + i))
        add(world, w, "author", obj=p, attributions=src(), status="verified")
        works.append(w)
    return {"locke": p, "london": london, "works": works}


def kant(world, stack) -> dict[str, str]:
    """Кант: влияния разной природы, учитель, влиявшие на него. Источники A и B — учебники."""
    n, r = stack.textbooks["N"], "s_russell"
    world.source(r, "Рассел")
    k = world.person("Иммануил Кант", "1724", "1804")
    people = {
        name: world.person(label, birth, death)
        for name, (label, birth, death) in {
            "hume": ("Дэвид Юм", "1711", "1776"),
            "knutzen": ("Мартин Кнутцен", "1713", "1751"),
            "fichte": ("Иоганн Фихте", "1762", "1814"),
            "schelling": ("Фридрих Шеллинг", "1775", "1854"),
            "leibniz": ("Готфрид Лейбниц", "1646", "1716"),
            "wolff": ("Христиан Вольф", "1679", "1754"),
            "hutcheson": ("Фрэнсис Хатчесон", "1694", "1746"),
            "berkeley": ("Джордж Беркли", "1685", "1753"),
        }.items()
    }
    add(world, k, "influenced_by", obj=people["hume"], attributions=src(n))
    add(world, k, "criticizes", obj=people["hume"], attributions=src(n), status="verified")
    add(world, k, "studied_with", obj=people["knutzen"], attributions=src(n))
    add(world, people["fichte"], "influenced_by", obj=k, attributions=src(n))
    add(world, people["schelling"], "influenced_by", obj=k, attributions=src(n))
    add(
        world,
        k,
        "influenced_by",
        obj=people["leibniz"],
        attributions=[Attribution("source", n), Attribution("source", r, stance="disputes")],
    )
    add(world, k, "develops", obj=people["wolff"], provenance=Provenance("generated"))
    add(world, k, "influenced_by", obj=people["hutcheson"], attributions=src(n))
    paragraph = stack.paragraph("N", "Кант пишет об опыте")
    add(
        world,
        k,
        "influenced_by",
        obj=people["berkeley"],
        attributions=src(n),
        evidence=[Evidence(paragraph, "Кант пишет", source_id=n)],
        provenance=Provenance("extracted"),
    )
    return {"kant": k, **people}


def fixed(text: str) -> str:
    return parse(text).to_json()
