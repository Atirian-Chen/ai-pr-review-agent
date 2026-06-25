from src.config import parse_config


def test_missing_settings_is_handled():
    assert parse_config({}) == "default"
