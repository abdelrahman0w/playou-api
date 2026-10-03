import html
from dataclasses import dataclass


@dataclass(frozen=True)
class Email:
    subject: str
    text: str
    html: str


COPY = {
    "en": {
        "subject": "{code} is your PlaYou code",
        "lead": "Your code to sign in to PlaYou:",
        "expires": "It works for {minutes} minutes, and only once.",
        "ignore": (
            "If you did not ask for it, ignore this email, "
            "no one can sign in without it."
        ),
        "dir": "ltr",
    },
    "ar": {
        "subject": "{code} رمز الدخول إلى PlaYou",
        "lead": "رمز الدخول إلى PlaYou:",
        "expires": "يعمل لمدة {minutes} دقائق، ومرة واحدة فقط.",
        "ignore": "إن لم تطلبه، تجاهل هذه الرسالة، فلا يمكن لأحد الدخول بدونه.",
        "dir": "rtl",
    },
}


def code_email(code: str, *, locale: str, minutes: int) -> Email:
    copy = COPY.get(locale, COPY["en"])
    expires = copy["expires"].format(minutes=minutes)
    text = f"{copy['lead']}\n\n{code}\n\n{expires}\n{copy['ignore']}\n"
    code_style = (
        "font-size:32px;font-weight:600;letter-spacing:6px;"
        "font-family:ui-monospace,monospace"
    )
    box_style = "font-family:system-ui,sans-serif;color:#09090b;max-width:480px"
    note_style = "color:#71717a;font-size:13px"
    body = "".join(
        (
            f'<div dir="{copy["dir"]}" style="{box_style}">',
            f"<p>{html.escape(copy['lead'])}</p>",
            f'<p style="{code_style}" dir="ltr">{code}</p>',
            f"<p>{html.escape(expires)}</p>",
            f'<p style="{note_style}">{html.escape(copy["ignore"])}</p>',
            "</div>",
        ),
    )

    return Email(subject=copy["subject"].format(code=code), text=text, html=body)
