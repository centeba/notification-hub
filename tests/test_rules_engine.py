"""Rules-engine condition evaluator tests.

Ported from the retired standalone ``notification-api`` service (package was
refactored ``app.`` → ``integration_hub_backend.api.``); the evaluator itself
is unchanged and is what ``evaluate_rules_activity`` calls at dispatch time.
"""

from __future__ import annotations

from integration_hub_backend.api.core.rules_engine import evaluate_conditions


def test_no_conditions_passes():
    assert evaluate_conditions(None, {"key": "value"}) is True
    assert evaluate_conditions([], {"key": "value"}) is True


def test_eq_condition_match():
    conditions = [{"field": "status", "operator": "eq", "value": "active"}]
    assert evaluate_conditions(conditions, {"status": "active"}) is True


def test_eq_condition_no_match():
    conditions = [{"field": "status", "operator": "eq", "value": "active"}]
    assert evaluate_conditions(conditions, {"status": "inactive"}) is False


def test_gt_condition():
    conditions = [{"field": "amount", "operator": "gt", "value": 100}]
    assert evaluate_conditions(conditions, {"amount": 150}) is True
    assert evaluate_conditions(conditions, {"amount": 50}) is False


def test_nested_field_dot_notation():
    conditions = [{"field": "order.total", "operator": "gte", "value": 500}]
    assert evaluate_conditions(conditions, {"order": {"total": 600}}) is True
    assert evaluate_conditions(conditions, {"order": {"total": 200}}) is False


def test_contains_condition():
    conditions = [{"field": "email", "operator": "contains", "value": "@admin.com"}]
    assert evaluate_conditions(conditions, {"email": "user@admin.com"}) is True
    assert evaluate_conditions(conditions, {"email": "user@gmail.com"}) is False


def test_in_condition():
    conditions = [{"field": "role", "operator": "in", "value": ["admin", "superuser"]}]
    assert evaluate_conditions(conditions, {"role": "admin"}) is True
    assert evaluate_conditions(conditions, {"role": "user"}) is False


def test_multiple_conditions_and():
    conditions = [
        {"field": "amount", "operator": "gt", "value": 100},
        {"field": "status", "operator": "eq", "value": "paid"},
    ]
    assert evaluate_conditions(conditions, {"amount": 200, "status": "paid"}) is True
    assert evaluate_conditions(conditions, {"amount": 200, "status": "pending"}) is False
    assert evaluate_conditions(conditions, {"amount": 50, "status": "paid"}) is False


def test_unknown_operator_returns_false():
    conditions = [{"field": "x", "operator": "nonsense", "value": "y"}]
    assert evaluate_conditions(conditions, {"x": "y"}) is False


def test_missing_field_returns_false():
    conditions = [{"field": "nonexistent", "operator": "eq", "value": "x"}]
    assert evaluate_conditions(conditions, {"other": "y"}) is False
