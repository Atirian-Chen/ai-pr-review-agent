from src.profile import display_name


class User:
    display_name = "Ada"


def test_display_name_handles_missing_user():
    assert display_name(None) == "Anonymous"


def test_display_name_returns_user_name():
    assert display_name(User()) == "Ada"
