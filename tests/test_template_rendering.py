"""Jinja2 template-rendering behaviour tests.

Ported from the retired standalone ``notification-api`` service. Pins the
autoescape / strict-undefined / i18n behaviour that ``render_template_activity``
relies on (it builds an ``Environment`` the same way).
"""

from __future__ import annotations

from jinja2 import Environment, StrictUndefined, UndefinedError


def render(source: str, context: dict) -> str:
    env = Environment(autoescape=True, undefined=StrictUndefined)
    return env.from_string(source).render(**context)


def test_basic_variable_substitution():
    assert render("Hello {{ name }}!", {"name": "Alice"}) == "Hello Alice!"


def test_nested_variable():
    result = render(
        "Order {{ order.id }} for ${{ order.amount }}",
        {"order": {"id": "ORD-123", "amount": "99.99"}},
    )
    assert result == "Order ORD-123 for $99.99"


def test_xss_autoescape():
    result = render("Hello {{ name }}!", {"name": "<script>alert('xss')</script>"})
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_undefined_variable_raises():
    env = Environment(autoescape=True, undefined=StrictUndefined)
    try:
        env.from_string("Hello {{ unknown_var }}!").render()
        raise AssertionError("Should have raised UndefinedError")
    except UndefinedError:
        pass  # Expected — the activity catches this and falls back to raw source.


def test_conditional_block():
    result = render(
        "{% if amount > 100 %}High value order!{% else %}Standard order{% endif %}",
        {"amount": 250},
    )
    assert result == "High value order!"


def test_loop_in_template():
    result = render(
        "Items: {% for item in items %}{{ item }}{% if not loop.last %}, {% endif %}{% endfor %}",
        {"items": ["apple", "banana", "cherry"]},
    )
    assert result == "Items: apple, banana, cherry"


def test_spanish_characters():
    result = render("Hola {{ nombre }}, su pedido está listo.", {"nombre": "María García"})
    assert "María García" in result


def test_french_characters():
    result = render("Bonjour {{ prenom }}, votre commande est prête.", {"prenom": "François"})
    assert "François" in result
