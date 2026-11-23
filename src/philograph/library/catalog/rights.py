"""Классификация правового статуса источника.

Порядок проверок — здесь, пороги по юрисдикциям — в ``sources/rights-tiers.yaml`` (данные,
а не код). Открытую лицензию распознаёт ``suggest_license``; эта функция отвечает на вопрос
«общественное достояние, под охраной или неизвестно».
"""

from __future__ import annotations

import re
from typing import Any

OPEN_LICENSE_HINT = re.compile(r"creativecommons\.org/licenses|CC[- ]BY|CC0", re.I)
PUBLIC_DOMAIN_HINT = re.compile(r"public domain|PD-|publicdomain|NOT_IN_COPYRIGHT", re.I)


def classify_tier(
    harvest: Any,
    year: int,
    *,
    death_plus_years: int = 70,
) -> dict[str, Any]:
    """Правовой статус по метаданным харвеста: ``rights_tier`` + доказательство и юрисдикция."""
    hint = harvest.license_hint or ""
    meta = harvest.metadata or {}
    people: list[dict[str, Any]] = list(meta.get("authors") or [])
    translator = meta.get("translator")
    if translator:
        people.append(translator)
    deaths = [p.get("death_year") for p in people]
    detail = "; ".join(f"{p['name']} ум. {p['death_year']}" for p in people if p.get("death_year"))

    if OPEN_LICENSE_HINT.search(hint):
        return {
            "rights_tier": "open_license",
            "rights_evidence": f"сайт: {hint}",
            "rights_jurisdiction": None,
        }

    pd_hint = bool(PUBLIC_DOMAIN_HINT.search(hint)) or (meta.get("publisher") or "").endswith(
        "wikisource.org"
    )
    if people and all(d is not None for d in deaths):
        if all(d + death_plus_years < year for d in deaths):
            if pd_hint:
                return {
                    "rights_tier": "public_domain",
                    "rights_evidence": f"срок охраны истёк; {detail}",
                    "rights_jurisdiction": "RU",
                }
            return {
                "rights_tier": "in_copyright",
                "rights_evidence": (
                    f"нет открытой лицензии и отметки общественного достояния; {detail}"
                ),
                "rights_jurisdiction": "RU",
            }
        return {
            "rights_tier": "in_copyright",
            "rights_evidence": f"срок охраны не истёк; {detail}",
            "rights_jurisdiction": "RU",
        }

    return {
        "rights_tier": "unknown",
        "rights_evidence": "нет годов смерти авторов и подсказки лицензии",
        "rights_jurisdiction": None,
    }
