"""Настройка сервиса LLM: роли, провайдеры, цены, бюджеты.

Хранится в YAML, путь к нему задаёт ``PHILOGRAPH_LLM_CONFIG``. Ключи провайдеров в файл не
пишутся: в нём только имя переменной окружения, откуда ключ берётся.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from philograph.platform import events
from philograph.platform.settings import ServiceSettings, SettingsError

Budget = Literal["site", "filling"]


class ProviderConfig(BaseModel):
    kind: Literal["openai_compatible", "fake"]
    base_url: str | None = None
    api_key_env: str | None = None


class RoleConfig(BaseModel):
    provider: str
    model: str
    max_output_tokens: int = 1024
    timeout_seconds: float = 30.0


class NightTariff(BaseModel):
    """Окно ночного тарифа по UTC в минутах от полуночи; может переходить через полночь."""

    start_minute: int = Field(ge=0, lt=1440)
    end_minute: int = Field(ge=0, lt=1440)
    multiplier: float = Field(gt=0, le=1)

    def active(self, minute_of_day: int) -> bool:
        if self.start_minute <= self.end_minute:
            return self.start_minute <= minute_of_day < self.end_minute
        return minute_of_day >= self.start_minute or minute_of_day < self.end_minute


class Price(BaseModel):
    """Цены в долларах за миллион токенов."""

    input_cache_miss: float
    input_cache_hit: float
    output: float = 0.0
    night: NightTariff | None = None


class BudgetConfig(BaseModel):
    daily_limit_usd: float | None = None
    monthly_limit_usd: float | None = None
    alert_ratio: float = Field(default=0.8, gt=0, le=1)


class GatewayConfig(BaseModel):
    providers: dict[str, ProviderConfig]
    roles: dict[str, RoleConfig]
    prices: dict[str, Price]
    budgets: dict[Budget, BudgetConfig] = Field(
        default_factory=lambda: {"site": BudgetConfig(), "filling": BudgetConfig()}
    )
    max_retries: int = 2
    retry_base_seconds: float = 0.5
    schema_retries: int = 2
    text_retention_days: int = 90

    @model_validator(mode="after")
    def _consistent(self) -> GatewayConfig:
        for name, role in self.roles.items():
            if role.provider not in self.providers:
                raise ValueError(f"роль {name}: нет провайдера {role.provider}")
            if role.model not in self.prices:
                raise ValueError(f"роль {name}: нет цены для модели {role.model}")
        return self


class LLMSettings(ServiceSettings):
    llm_config: Path
    database_url: str = "sqlite://"


def load_config(path: Path, env: dict[str, str] | None = None) -> GatewayConfig:
    """Читает настройку и проверяет, что ключи всех используемых провайдеров заданы."""
    env = os.environ if env is None else env
    config = GatewayConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    missing = {}
    used = {role.provider for role in config.roles.values()}
    for name in sorted(used):
        provider = config.providers[name]
        if provider.kind == "fake":
            continue
        if not provider.api_key_env or not env.get(provider.api_key_env):
            var = provider.api_key_env or f"<api_key_env провайдера {name}>"
            missing[var] = f"нет ключа провайдера {name}"
        else:
            events.register_secret(env[provider.api_key_env])
    if missing:
        events.emit(
            "service.settings.invalid",
            settings="GatewayConfig",
            problems=sorted(missing),
            error_kind="settings",
        )
        raise SettingsError(missing)
    return config
