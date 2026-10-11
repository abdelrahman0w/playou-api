import re


USERNAME = re.compile(r"^[a-z][a-z0-9_.]{2,29}$")
RESERVED = frozenset(
    {
        "about",
        "account",
        "accounts",
        "admin",
        "api",
        "help",
        "home",
        "library",
        "me",
        "messages",
        "people",
        "playou",
        "privacy",
        "search",
        "settings",
        "shared",
        "shares",
        "sign-in",
        "support",
        "terms",
        "welcome",
    },
)


class InvalidUsernameError(ValueError):
    pass


def clean_username(raw: str) -> str:
    username = raw.strip().removeprefix("@").lower()
    if not USERNAME.match(username):
        raise InvalidUsernameError(
            "A username is 3 to 30 letters, digits, _ or ., starting with a letter",
        )
    if username.endswith(".") or ".." in username:
        raise InvalidUsernameError("A username can't end with . or have .. in it")
    if username in RESERVED:
        raise InvalidUsernameError("That username is taken")

    return username
