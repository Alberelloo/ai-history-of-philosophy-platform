"""Коды причин отбраковки при извлечении — закрытый перечень (ontology-extraction, «Коды
причин отбраковки»).

Код — короткое имя причины в событии ``knowledge.extraction.dropped`` (поле ``code``) и в
сводке запуска ``filling_runs.drop_reasons``. Прежние причины элемента (``entity:*``,
``dating:*``) остаются в ``reason`` как были, код выводится из них.
"""

from __future__ import annotations

from philograph.knowledge import quotes

REPLY_INVALID = "reply_invalid"
REPLY_MISSING = "reply_missing"
SCHEMA_ITEM = "schema_item"
STANCE_INVALID = "stance_invalid"
RELATION_NOT_ALLOWED = "relation_not_allowed"
PARAGRAPH_OUT_OF_WINDOW = "paragraph_out_of_window"
QUOTE_NOT_FOUND = quotes.QUOTE_NOT_FOUND
QUOTE_TOO_SHORT = quotes.QUOTE_TOO_SHORT
TYPE_MISMATCH = "type_mismatch"
QUALIFIER_INVALID = "qualifier_invalid"
STATEMENT_REFUSED = "statement_refused"
ENTITY_TYPE = "entity_type"
ENTITY_NO_TYPE = "entity_no_type"
ENTITY_AMBIGUOUS = "entity_ambiguous"
ENTITY_INVALID = "entity_invalid"
MODEL_TIMEOUT = "model_timeout"
MODEL_SCHEMA = "model_schema"
MODEL_UNAVAILABLE = "model_unavailable"
MODEL_BUDGET = "model_budget"
MODEL_REFUSED = "model_refused"

DATING_CODES = frozenset(
    f"dating_{c}"
    for c in (
        "paragraph",
        "quote",
        "unparsed",
        "not_in_quote",
        "era",
        "single_year",
        "type",
        "unresolved",
    )
)

CODES = frozenset(
    {
        REPLY_INVALID,
        REPLY_MISSING,
        SCHEMA_ITEM,
        STANCE_INVALID,
        RELATION_NOT_ALLOWED,
        PARAGRAPH_OUT_OF_WINDOW,
        QUOTE_NOT_FOUND,
        QUOTE_TOO_SHORT,
        TYPE_MISMATCH,
        QUALIFIER_INVALID,
        STATEMENT_REFUSED,
        ENTITY_TYPE,
        ENTITY_NO_TYPE,
        ENTITY_AMBIGUOUS,
        ENTITY_INVALID,
        MODEL_TIMEOUT,
        MODEL_SCHEMA,
        MODEL_UNAVAILABLE,
        MODEL_BUDGET,
        MODEL_REFUSED,
    }
    | DATING_CODES
)

_ENTITY = {"type": ENTITY_TYPE, "no_type": ENTITY_NO_TYPE, "ambiguous": ENTITY_AMBIGUOUS}


def code_for(reason: str) -> str:
    """Код по причине: ``entity:*`` и ``dating:*`` — по префиксу, код перечня — он сам, иное —
    ``statement_refused``."""
    prefix, _, rest = reason.partition(":")
    if prefix == "entity" and rest:
        return _ENTITY.get(rest, ENTITY_INVALID)
    if prefix == "dating" and f"dating_{rest}" in DATING_CODES:
        return f"dating_{rest}"
    return reason if reason in CODES else STATEMENT_REFUSED
