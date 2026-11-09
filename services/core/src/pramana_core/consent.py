"""Email one-time consent links through the configured Gmail mailer."""

from __future__ import annotations

import asyncio
from typing import Literal

from .mail import Mailer
from .observability import log

ConsentDelivery = Literal["sent", "failed", "not_configured", "no_email"]
SEND_TIMEOUT_S = 6.0


def _message(language: str, link: str) -> tuple[str, str]:
    if language == "hi":
        return (
            "Pramana se sawal paane ki aapki marzi",
            "साइट टीम जानना चाहती है कि जाँच के दौरान Pramana आपसे वेब पर सवाल पूछ सकता है या नहीं.\n\n"
            f"Apna faisla dene ke liye yahan kholen:\n{link}\n\n"
            "Aap haan ya mana kar sakte hain. Faisla aapka hai.",
        )
    if language == "mr":
        return (
            "Pramana kadun prashna milavnyasathi tumchi parvangi",
            "तपासादरम्यान Pramana तुम्हाला वेबवर प्रश्न विचारू शकतो का, हे साइट टीमला जाणून घ्यायचे आहे.\n\n"
            f"Tumcha nirnay denyasathi hi link ughada:\n{link}\n\n"
            "Tumhi ho kiwa nahi mhanu shakta. Nirnay tumcha aahe.",
        )
    return (
        "Choose whether Pramana may ask you questions",
        "The site team would like to know whether Pramana may ask you questions on the web "
        "during an investigation.\n\n"
        f"Open this link to choose:\n{link}\n\n"
        "You can agree or refuse. The choice is yours.",
    )


async def email_consent_request(
    mailer: Mailer | None,
    link_base: str | None,
    to: str | None,
    link_path: str,
    language: str,
    request_id: str,
) -> ConsentDelivery:
    """Try Gmail without logging the recipient or secret link; manual copy remains available."""
    if not to:
        return "no_email"
    if mailer is None or not link_base:
        return "not_configured"
    subject, body = _message(language, f"{link_base.rstrip('/')}{link_path}")
    try:
        await asyncio.wait_for(asyncio.to_thread(mailer.send, to, subject, body), SEND_TIMEOUT_S)
    except Exception as exc:
        log.warning(
            "consent_request_email_not_confirmed",
            error=type(exc).__name__,
            request=request_id,
        )
        return "failed"
    return "sent"
