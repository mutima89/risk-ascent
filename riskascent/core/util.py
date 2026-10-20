"""Small shared helpers: safe formula evaluation, text templating, money formatting."""

from __future__ import annotations

import ast
import math
import operator
import re
from typing import Any

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}
_UN = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"min": min, "max": max, "abs": abs, "round": round, "sqrt": math.sqrt,
          "log": math.log, "exp": math.exp}


def safe_eval(expr: str, variables: dict[str, float]) -> float:
    """Evaluate an arithmetic expression from content files.

    Only numbers, variables, + - * / ** %, parentheses and a few math
    functions are allowed. No attribute access, no calls to arbitrary code.
    """
    tree = ast.parse(expr, mode="eval")

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"Unknown variable '{node.id}' in formula")
            return variables[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            return _BIN[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
            return _UN[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        if isinstance(node, (ast.List, ast.Tuple)):
            return [ev(e) for e in node.elts]
        raise ValueError(f"Disallowed expression element: {type(node).__name__}")

    return float(ev(tree))


CURRENCY_SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€", "SAR": "SAR ", "AED": "AED "}


def fmt_money(amount: float, currency: str = "USD", compact: bool = True) -> str:
    sym = CURRENCY_SYMBOLS.get(currency, currency + " ")
    neg = amount < 0
    a = abs(amount)
    if compact and a >= 1_000_000_000:
        s = f"{a / 1_000_000_000:.2f}bn"
    elif compact and a >= 1_000_000:
        s = f"{a / 1_000_000:.2f}m"
    elif compact and a >= 10_000:
        s = f"{a / 1_000:.0f}k"
    else:
        s = f"{a:,.0f}"
    return f"-{sym}{s}" if neg else f"{sym}{s}"


_TOKEN = re.compile(r"\{(m|p|sh|shr):([^{}]+)\}|\{(org|cur|player|industry|title|city|regulator)\}")


def render(text: str, ctx: dict) -> str:
    """Fill content placeholders.

    {org} {cur} {player} {industry} {title} {city} {regulator}
    {m:250000}  money, scaled by ctx['money_scale'] and formatted in ctx['currency']
    {p:0.25}    probability as a percentage
    {sh:cfo}    stakeholder name for a role;  {shr:cfo} name with role title
    """
    if not text or "{" not in text:
        return text

    def sub(m: re.Match) -> str:
        kind, arg, simple = m.group(1), m.group(2), m.group(3)
        if simple:
            return str(ctx.get(simple, m.group(0)))
        if kind == "m":
            try:
                v = float(arg) * ctx.get("money_scale", 1.0)
            except ValueError:
                return m.group(0)
            return fmt_money(v, ctx.get("currency", "USD"), compact=False)
        if kind == "p":
            try:
                return f"{float(arg) * 100:.0f}%"
            except ValueError:
                return m.group(0)
        people = ctx.get("stakeholders", {})
        person = people.get(arg)
        if not person:
            return arg.upper()
        if kind == "sh":
            return person["name"]
        return f"{person['name']} ({person['title']})"

    return _TOKEN.sub(sub, text)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def stable_seed(*parts: Any) -> int:
    """Deterministic seed from parts (Python's hash() is salted per process)."""
    h = 2166136261
    for ch in "|".join(str(p) for p in parts):
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h
