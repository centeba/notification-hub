"""Rules engine: evaluate conditions against event payloads."""

from collections.abc import Callable
from typing import Any

import structlog

log = structlog.get_logger(__name__)

OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "contains": lambda a, b: b in str(a),
    "in": lambda a, b: a in b if isinstance(b, list) else str(a) in str(b),
    "not_in": lambda a, b: a not in b if isinstance(b, list) else str(a) not in str(b),
    "starts_with": lambda a, b: str(a).startswith(str(b)),
    "ends_with": lambda a, b: str(a).endswith(str(b)),
}


def _get_nested(obj: dict[str, Any], field_path: str) -> Any:
    """Support dot-notation field paths like 'order.amount'."""
    keys = field_path.split(".")
    current: Any = obj
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


def evaluate_conditions(
    conditions: list[dict[str, Any]] | None,
    payload: dict[str, Any],
) -> bool:
    """
    Evaluate a list of conditions (ANDed together) against an event payload.
    Returns True if all conditions pass (or conditions is None/empty).
    """
    if not conditions:
        return True

    for cond in conditions:
        field = cond.get("field", "")
        operator = cond.get("operator", "eq")
        expected = cond.get("value")

        actual = _get_nested(payload, field)
        op_fn = OPERATORS.get(operator)
        if op_fn is None:
            log.warning("unknown_operator", operator=operator)
            return False

        try:
            if not op_fn(actual, expected):
                return False
        except (TypeError, ValueError) as e:
            log.warning("condition_eval_error", field=field, operator=operator, error=str(e))
            return False

    return True
