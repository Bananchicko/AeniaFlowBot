"""Safe arithmetic parser used by the .calc command."""

from __future__ import annotations
import ast


def safe_eval(expression: str) -> float | int:
    if len(expression) > 100:
        raise ValueError("Слишком длинное выражение.")
    tree = ast.parse(expression, mode="eval")
    allowed_bin = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    allowed_un = (ast.UAdd, ast.USub)

    def run(node: ast.AST):
        if isinstance(node, ast.Expression):
            return run(node.body)
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            if abs(node.value) > 10**12:
                raise ValueError("Число слишком большое.")
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, allowed_bin):
            left, right = run(node.left), run(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 8:
                raise ValueError("Степень слишком велика.")
            result = {
                ast.Add: lambda: left + right,
                ast.Sub: lambda: left - right,
                ast.Mult: lambda: left * right,
                ast.Div: lambda: left / right,
                ast.FloorDiv: lambda: left // right,
                ast.Mod: lambda: left % right,
                ast.Pow: lambda: left**right,
            }[type(node.op)]()
            if isinstance(result, complex) or abs(result) > 1e100:
                raise ValueError("Результат слишком велик.")
            return result
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, allowed_un):
            value = run(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        raise ValueError("Разрешены только числа, скобки и операции + − * / // % **.")

    return run(tree)
