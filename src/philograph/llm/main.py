"""Точка входа сервиса LLM: ``uvicorn philograph.llm.main:app``."""

from __future__ import annotations

import os

from fastapi import FastAPI
from sqlalchemy import text

from philograph import __version__
from philograph.llm import store as st
from philograph.llm.app import build_app
from philograph.llm.config import LLMSettings, load_config
from philograph.llm.gateway import LLMGateway
from philograph.llm.providers import FakeProvider, OpenAICompatibleProvider, Provider
from philograph.llm.templates import Template, TemplateRegistry
from philograph.platform import events
from philograph.platform.db import make_engine
from philograph.platform.health import Health
from philograph.platform.settings import load
from philograph.prompts import PROMPTS


def create(env: dict[str, str] | None = None) -> FastAPI:
    env = dict(os.environ) if env is None else env
    given = {
        "llm_config": env.get("PHILOGRAPH_LLM_CONFIG"),
        "database_url": env.get("PHILOGRAPH_DATABASE_URL"),
    }
    settings = load(LLMSettings, **{k: v for k, v in given.items() if v})
    config = load_config(settings.llm_config, env)
    providers: dict[str, Provider] = {}
    for name, provider in config.providers.items():
        if provider.kind == "fake":
            providers[name] = FakeProvider(default=provider.fake_reply or "ok")
        else:
            key = env.get(provider.api_key_env or "", "")
            providers[name] = OpenAICompatibleProvider(provider.base_url or "", key)
    engine = make_engine(settings.database_url, [st.SCHEMA])
    st.migrations.upgrade(engine)
    health = Health("llm", __version__)

    def database() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    health.depends_on("database", database)
    templates = TemplateRegistry()
    for spec in PROMPTS:
        templates.register(Template(spec.name, spec.instructions, spec.data_slots))
    gateway = LLMGateway(config, providers, templates, st.Store(engine))
    return build_app(gateway, health)


def _app() -> FastAPI:
    events.configure(sinks=[events.json_sink()])
    return create()


if os.environ.get("PHILOGRAPH_LLM_CONFIG"):
    app = _app()
