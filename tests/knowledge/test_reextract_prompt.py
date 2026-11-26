"""ontology-extraction (reextract-with-claude): «Художественный текст».

По дельте ``specs/ontology-extraction``. Вывод — текст инструкции, который реально ушёл
модели через шлюз (сообщения запроса к провайдеру) и попал в задание внешнего извлекателя;
поведение сервера на ответ с атрибуцией автору — в базе; журнал — ``knowledge.extraction.*``.
"""

from __future__ import annotations

import json

import pytest

from philograph.knowledge import external_extraction as ext

from .extraction_stand import Stand
from .reextract_common import EO, dropped_codes
from .reextract_common import st as stmt

req = pytest.mark.req
FICTION = "Художественный текст"
TEXT = "Так говорил Заратустра: человек есть нечто, что должно преодолеть."


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock)


def sent_instructions(stand) -> str:
    [call] = stand.model.calls
    return "\n".join(m.content for m in call.messages).lower()


@req(EO, FICTION, scenario="Правила в промпте")
def test_prompt_rules_reach_the_model(stand, events):
    stand.extract([TEXT], {"statements": []})
    text = sent_instructions(stand)
    assert "персонажи художественного текста — не персоны" in text
    assert "атрибутируй автору произведения" in text
    assert "не пиши null" in text or "вместо null" in text
    assert events.of("knowledge.extraction.dropped") == []


@req(EO, FICTION, scenario="Правила в промпте")
def test_prompt_rules_in_external_task(stand, tmp_path):
    vid, _ = stand.version([TEXT])
    service = ext.Service(
        stand.filling, stand.onto.statements.engine, ext._Texts(stand.filling.library)
    )
    assert (
        ext.main(["export", "--version", vid, "--out", str(tmp_path)], env={}, service=service) == 0
    )
    task = json.loads((tmp_path / f"{vid}.jsonl").read_text(encoding="utf-8").splitlines()[0])
    lowered = task["instructions"].lower()
    assert "персонажи художественного текста — не персоны" in lowered
    assert "атрибутируй автору произведения" in lowered
    assert task["instructions"].count("Заратустра") >= 1


@req(EO, FICTION, invariant="Высказывание персонажа атрибутируется автору, а не персонажу")
@pytest.mark.parametrize("stance", [None, "asserts", "disputes"])
def test_character_statement_attributed_to_author(stand, events, stance):
    extra = {"attributed_to": "Ницше"}
    if stance:
        extra["stance"] = stance
    stand.extract(
        [TEXT],
        {"statements": [stmt("Ницше", "holds", "Сверхчеловек", 1, "человек есть нечто", **extra)]},
    )
    [statement] = stand.statements()
    by_kind = {a["who_kind"]: a for a in statement["attributions"]}
    assert by_kind["entity"]["stance"] == (stance or "asserts")
    assert by_kind["entity"]["who"] == stand.onto.entities.find("Ницше")[0]["id"]
    assert by_kind["source"]["stance"] == "mentions"
    assert events.of("knowledge.extraction.dropped") == []


@req(EO, FICTION, invariant="Персонаж художественного текста не становится сущностью person")
@pytest.mark.parametrize("kind", ["character", "animal", "allegory", "fictional_person"])
def test_character_is_not_a_person_entity(stand, events, kind):
    stand.extract(
        [TEXT],
        {
            "statements": [
                stmt(
                    "Заратустра",
                    "holds",
                    "Сверхчеловек",
                    1,
                    "человек есть нечто",
                    subject_type=kind,
                )
            ],
            "entities": [{"name": "Заратустра", "type": kind}],
        },
    )
    assert stand.statements() == []
    assert stand.entities_of("person") == 0 and stand.onto.entities.find("Заратустра") == []
    assert set(dropped_codes(events)) == {"entity_type"}
