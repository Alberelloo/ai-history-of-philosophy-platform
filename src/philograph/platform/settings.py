"""Настройки из окружения с проверкой при старте.

Сервис описывает свои настройки классом-наследником ``ServiceSettings``. ``load`` читает
переменные окружения и, если обязательной нет или значение неверно, бросает
``SettingsError`` с названием настройки: сервис не стартует с неполной конфигурацией.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from philograph.platform import events

events.define(
    "service.settings.invalid",
    "error",
    "Сервис не стартует: настройка отсутствует или неверна",
    required=("settings", "problems"),
)


class SettingsError(Exception):
    def __init__(self, problems: dict[str, str]) -> None:
        self.problems = problems
        listed = "; ".join(f"{name}: {why}" for name, why in problems.items())
        super().__init__(f"неверные настройки: {listed}")


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHILOGRAPH_", extra="ignore")


S = TypeVar("S", bound=ServiceSettings)


def load(cls: type[S], **overrides: object) -> S:
    try:
        return cls(**overrides)
    except ValidationError as exc:
        prefix = cls.model_config.get("env_prefix", "")
        problems = {}
        for err in exc.errors():
            name = ".".join(str(p) for p in err["loc"]) or "?"
            problems[f"{prefix}{name}".upper()] = err["msg"]
        events.emit(
            "service.settings.invalid",
            settings=cls.__name__,
            problems=sorted(problems),
            error_kind="settings",
        )
        raise SettingsError(problems) from None
