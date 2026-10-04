import html

from src.actions.auth.emails import Email


COPY = {
    "en": {
        "subject": "Reconnect {platform} to keep it in PlaYou",
        "lead": "Your {platform} connection to PlaYou ends in {days}.",
        "why": (
            "{platform} asks you to approve PlaYou again from time to time, "
            "it takes a click, and nothing else changes."
        ),
        "button": "Reconnect {platform}",
        "after": "If you do not, PlaYou stops syncing with {platform} until you do.",
        "dir": "ltr",
    },
    "ar": {
        "subject": "أعد ربط {platform} ليبقى في PlaYou",
        "lead": "ينتهي ربط {platform} بـ PlaYou خلال {days}.",
        "why": (
            "يطلب {platform} موافقتك على PlaYou من حين لآخر، "
            "الأمر يستغرق نقرة، ولن يتغير شيء آخر."
        ),
        "button": "أعد ربط {platform}",
        "after": "إن لم تفعل، يتوقف PlaYou عن المزامنة مع {platform} حتى تفعل.",
        "dir": "rtl",
    },
}


DISCONNECTED = {
    "en": {
        "subject": "{platform} was disconnected from PlaYou",
        "lead": "PlaYou can no longer reach your {platform} account.",
        "why": (
            "The access was removed on {platform}'s side, or it ended. "
            "Until you reconnect, your likes and playlists stop syncing with it, "
            "and playing from it is paused."
        ),
        "button": "Reconnect {platform}",
        "after": (
            "If you don't reconnect within {days}, PlaYou unlinks {platform} "
            "and removes the songs and playlists that came only from it."
        ),
        "kept": "If you removed it on purpose, you can unlink {platform} in PlaYou.",
        "dir": "ltr",
    },
    "ar": {
        "subject": "تم فصل {platform} عن PlaYou",
        "lead": "لم يعد بإمكان PlaYou الوصول إلى حسابك على {platform}.",
        "why": (
            "أُزيل الإذن من جهة {platform} أو انتهى. "
            "إلى أن تعيد الربط، تتوقف مزامنة إعجاباتك وقوائم التشغيل معه، "
            "ويتوقف التشغيل منه."
        ),
        "button": "أعد ربط {platform}",
        "after": (
            "إن لم تُعد الربط خلال {days}، يلغي PlaYou ربط {platform} ويحذف "
            "الأغاني والقوائم التي جاءت منه وحده."
        ),
        "kept": "إن أزلته عن قصد، يمكنك إلغاء ربط {platform} في PlaYou.",
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
    return _email(
        COPY.get(locale, COPY["en"]),
        {"platform": platform, "days": days_left(days, locale=locale)},
        url=url,
    )


def disconnected_email(
    platform: str,
    *,
    days: int | None,
    url: str,
    locale: str,
) -> Email:
    copy = DISCONNECTED.get(locale, DISCONNECTED["en"])
    if days is None:
        copy = copy | {"after": copy["kept"]}

    return _email(
        copy,
        {"platform": platform, "days": days_left(days or 0, locale=locale)},
        url=url,
    )


def _email(
    copy: dict[str, str],
    values: dict[str, str],
    *,
    url: str,
) -> Email:
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
