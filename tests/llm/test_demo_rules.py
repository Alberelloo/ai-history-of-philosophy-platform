"""Демо-конфигурация моделей: правила фальшивого провайдера по тексту вопроса."""

from __future__ import annotations

from pathlib import Path

from philograph.llm.config import load_config
from philograph.llm.providers import FakeProvider, Message, ProviderRequest

DEMO = Path(__file__).parents[2] / "config" / "llm.demo.yaml"


def request(template: str, question: str, history: str = "") -> ProviderRequest:
    text = (
        f'<data name="question">\n{question}\n</data>\n\n<data name="history">\n{history}\n</data>'
    )
    return ProviderRequest("m", (Message("user", text),), 100, 0.0, 5.0, template=template)


def provider(name: str) -> FakeProvider:
    spec = load_config(DEMO, {}).providers[name]
    return FakeProvider(
        default=spec.fake_reply or "ok",
        replies=dict(spec.fake_replies),
        rules=[(r.template, r.contains, r.reply, r.block) for r in spec.fake_rules],
    )


def test_router_rules_by_question():
    router = provider("demo-router")
    reply = router.generate(request("assistant.route", "Покажи НА КАРТЕ эмпиристов")).text
    assert '"type": "map"' in reply and "эмпиризм" in reply
    assert '"names": []' in router.generate(request("assistant.route", "что на карте?")).text
    # Остальные вопросы — как раньше, «база знаний»; правило другого шаблона не срабатывает.
    assert '"knowledge"' in router.generate(request("assistant.route", "кто такой Юм?")).text
    assert '"knowledge"' in router.generate(request("card.description", "на карте")).text
    view = router.generate(request("assistant.map.view", "эмпиристов XVIII века")).text
    assert '"groups": ["c1"]' in view
    # Правила смотрят только в вопрос: прошлый вопрос об эмпиристах в истории не в счёт.
    later = request("assistant.route", "покажи на карте Китай", "Вопрос: эмпиристы на карте")
    assert '"names": []' in router.generate(later).text
