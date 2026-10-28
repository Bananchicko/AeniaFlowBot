from config import normalize_channel, Settings
from aeniaflow.core.games import score_word
from aeniaflow.core.calculator import safe_eval
import pytest


def test_duplicate_wordle_letters_not_overcounted():
    assert score_word("маска", "каска") == "⬛🟩🟩🟩🟩"
    assert score_word("сосна", "ососа") == "🟨🟨⬛🟨🟩"


@pytest.mark.parametrize("value", ["@AeniaFlow", "https://t.me/AeniaFlow", "t.me/AeniaFlow", "AeniaFlow"])
def test_channel_url_normalization(value):
    assert normalize_channel(value) == "@AeniaFlow"


def test_numeric_channel_and_bad_link():
    assert normalize_channel("-1001234567") == -1001234567
    assert normalize_channel("") == ""
    with pytest.raises(ValueError):
        normalize_channel("https://evil.example/channel")


@pytest.mark.parametrize(
    "expression", ["True+1", "().__class__", "[1,2][0]", "2**1000000", 'float("nan")', "1e309"]
)
def test_calculator_rejects_non_arithmetic_or_resource_abuse(expression):
    with pytest.raises((ValueError, SyntaxError, OverflowError)):
        safe_eval(expression)


def test_configuration_has_no_embedded_credentials(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings()
    assert settings.bot_token == "" and settings.openai_api_key == ""
    with pytest.raises(ValueError):
        settings.validate()
