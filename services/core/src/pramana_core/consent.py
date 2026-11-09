"""Build email content for one-time consent links."""

from __future__ import annotations

from .outbox import EmailEnvelope


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


def consent_request_email(
    *, email: str, link_base: str, link_path: str, language: str
) -> EmailEnvelope:
    """Build the message to store with its consent link in the durable email outbox."""
    subject, body = _message(language, f"{link_base.rstrip('/')}{link_path}")
    return EmailEnvelope(email, subject, body)
