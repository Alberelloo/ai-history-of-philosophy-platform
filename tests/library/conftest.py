from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from philograph.library import schema
from philograph.library.model import RawLine
from philograph.library.processing import Pipeline, PipelineSettings
from philograph.library.registry import License, Registry
from philograph.operator.access import ActionLog
from philograph.operator.access import migrations as operator_migrations
from philograph.platform.files import FileStore

BOOK = (
    "Глава 1. Опыт\n\nВсякое знание начинается с опыта, говорит Кант.\n\n"
    "Но не всё оно происходит из опыта.\n\nГлава 2. Рассудок\n\n"
    "Рассудок даёт правила явлениям.\n"
).encode()


@dataclass
class FakeOcr:
    """Распознаёт «изображение» как заданный текст; считает вызовы."""

    text: str = "Распознанный текст страницы о познании и опыте."
    confidence: float = 0.93
    calls: int = 0
    fail_on: int | None = None  # номер вызова, на котором упасть

    def recognize(self, image: bytes, languages: list[str]):
        self.calls += 1
        if self.fail_on is not None and self.calls == self.fail_on:
            raise RuntimeError("процесс распознавания упал")
        return [RawLine(self.text, block_break=True, confidence=self.confidence)], self.confidence


@dataclass
class Lib:
    registry: Registry
    pipeline: Pipeline
    files: dict[str, bytes]
    ocr: FakeOcr
    fetched: list[str] = field(default_factory=list)

    def license(self, **overrides) -> License:
        params = {"kind": "public-domain", "basis": "public_domain", "author_death_years": [1804]}
        params.update(overrides)
        return License(**params)

    def register(self, title="Критика чистого разума", files=None, **fields) -> str:
        params = {
            "title": title,
            "authors": ["И. Кант"],
            "language": "ru",
            "kind": "textbook",
            "license": self.license(),
            "scope": "public",
            "files": files or [{"name": "book", "path": "book.txt"}],
        }
        params.update(fields)
        return self.registry.register("operator", **params)

    def publish_new(self, source_id: str) -> str:
        version_id = self.pipeline.start("operator", source_id)
        assert self.registry.version(version_id)["state"] == "checked", self.registry.version(
            version_id
        )
        self.registry.publish("operator", version_id)
        return version_id


@pytest.fixture
def lib(engine_for, clock, tmp_path) -> Lib:
    engine = engine_for(schema.migrations, operator_migrations)
    registry = Registry(engine, clock, actions=ActionLog(engine, clock))
    registry.add_license_kind(
        "public-domain",
        "Общественное достояние",
        None,
        {"display": True, "external_processing": True, "quoting": True},
    )
    registry.add_license_kind(
        "cc-by",
        "CC BY 4.0",
        "https://creativecommons.org/licenses/by/4.0/",
        {"display": True, "external_processing": True, "quoting": True},
    )
    registry.add_license_kind(
        "no-display",
        "Только для обработки",
        None,
        {"display": False, "external_processing": True, "quoting": False},
    )
    files = {"book.txt": BOOK}
    ocr = FakeOcr()
    holder: dict = {}

    def fetch(spec):
        key = spec.get("path") or spec.get("url")
        holder["lib"].fetched.append(key)
        if key not in files:
            raise OSError(f"не загружается: {key}")
        return files[key]

    pipeline = Pipeline(
        registry,
        FileStore(tmp_path / "files"),
        fetch,
        ocr=ocr,
        clock=clock,
        settings=PipelineSettings(),
    )
    result = Lib(registry, pipeline, files, ocr)
    holder["lib"] = result
    return result
