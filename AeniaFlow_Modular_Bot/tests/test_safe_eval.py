from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aeniaflow.core.calculator import safe_eval


def test_arithmetic():
    assert safe_eval("(12 + 5) * 3") == 51
    assert safe_eval("2 ** 3") == 8


def test_rejects_python_calls():
    try:
        safe_eval('__import__("os").system("echo no")')
    except (ValueError, SyntaxError):
        pass
    else:
        raise AssertionError("arbitrary calls must be rejected")


if __name__ == "__main__":
    test_arithmetic()
    test_rejects_python_calls()
    print("Calculator tests passed")
