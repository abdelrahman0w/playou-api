import html

from src.actions.auth.emails import Email


COPY = {
    "en": {
        "subject": "Reconnect {platform} to keep it in Playou",
        "lead": "Your {platform} connection to Playou ends in {days}.",
        "why": (
            "{platform} asks you to approve Playou again from time to time, "
            "it takes a click, and nothing else changes."
        ),
        "button": "Reconnect {platform}",
        "after": "If you do not, Playou stops syncing with {platform} until you do.",
        "dir": "ltr",
    },
    "ar": {
        "subject": "أعد ربط {platform} ليبقى في Playou",
        "lead": "ينتهي ربط {platform} بـ Playou خلال {days}.",
        "why": (
            "يطلب {platform} موافقتك على Playou من حين لآخر، "
            "الأمر يستغرق نقرة، ولن يتغير شيء آخر."
        ),
        "button": "أعد ربط {platform}",
        "after": "إن لم تفعل، يتوقف Playou عن المزامنة مع {platform} حتى تفعل.",
        "dir": "rtl",
    },
}


def days_left(days: int, *, locale: str) -> str:
    if locale == "ar":
        if days == 1:
            return "يوم واحد"
        if days == 2:
            return "يومين"
        if days <= 10:
            return f"{days} أيام"

        return f"{days} يومًا"

    return "1 day" if days == 1 else f"{days} days"


def reconnect_email(
    platform: str,
    *,
    days: int,
    url: str,
    locale: str,
) -> Email:
    copy = COPY.get(locale, COPY["en"])
    values = {"platform": platform, "days": days_left(days, locale=locale)}
    lead, why, button, after = (
        copy[key].format(**values) for key in ("lead", "why", "button", "after")
    )
    text = f"{lead}\n\n{why}\n\n{button}: {url}\n\n{after}\n"
    box_style = "font-family:system-ui,sans-serif;color:#09090b;max-width:480px"
    button_style = (
        "display:inline-block;padding:10px 16px;border-radius:8px;"
        "background:#09090b;color:#ffffff;text-decoration:none;font-weight:600"
    )
    note_style = "color:#71717a;font-size:13px"
    body = "".join(
        (
            f'<div dir="{copy["dir"]}" style="{box_style}">',
            f"<p>{html.escape(lead)}</p>",
            f"<p>{html.escape(why)}</p>",
            f'<p><a href="{html.escape(url)}" style="{button_style}">',
            f"{html.escape(button)}</a></p>",
            f'<p style="{note_style}">{html.escape(after)}</p>',
            "</div>",
        ),
    )

    return Email(subject=copy["subject"].format(**values), text=text, html=body)
