"""Шаблоны запросов с версиями.

Инструкции модели берутся только отсюда. Версия шаблона — отпечаток его текста, поэтому
изменённый текст всегда получает новую версию, и забыть поднять её нельзя. Текст
пользователя и источников в инструкции не подставляется: он идёт отдельными блоками данных.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Template:
    name: str
    instructions: str
    data_slots: tuple[str, ...] = field(default=())

    @property
    def version(self) -> str:
        digest = hashlib.sha256(self.instructions.encode("utf-8"))
        digest.update("\x00".join(self.data_slots).encode("utf-8"))
        return digest.hexdigest()[:12]


class UnknownTemplate(Exception):
    pass


class TemplateRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Template] = {}

    def register(self, template: Template) -> Template:
        self._items[template.name] = template
        return template

    def get(self, name: str) -> Template:
        try:
            return self._items[name]
        except KeyError:
            raise UnknownTemplate(name) from None


def _escape(text: str) -> str:
    # Блок данных не может закрыть себя изнутри и выдать свой текст за инструкцию.
    return text.replace("</data", "<\\/data")


def render_data(template: Template, data: dict[str, str]) -> str:
    """Собирает сообщение с данными: каждый слот в своём размеченном блоке."""
    unknown = set(data) - set(template.data_slots)
    if unknown:
        raise ValueError(f"шаблон {template.name} не знает слотов: {', '.join(sorted(unknown))}")
    parts = []
    for slot in template.data_slots:
        if slot in data:
            parts.append(f'<data name="{slot}">\n{_escape(data[slot])}\n</data>')
    return "\n\n".join(parts)
