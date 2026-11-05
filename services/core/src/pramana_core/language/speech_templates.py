"""Fixed voice prompts that do not belong to a domain pack."""

from pramana_contracts import TemplateLanguage

CONSENT_TEXT: dict[TemplateLanguage, str] = {
    "en": "Hello, this is Pramana, helping fix a Wi-Fi and power problem in your building. "
    "Is it OK to ask you two or three quick questions? You can say no.",
    "hi": "नमस्ते, मैं प्रमाण हूँ, आपकी बिल्डिंग में वाई-फ़ाई और बिजली की समस्या ठीक करने में "
    "मदद कर रहा हूँ। क्या मैं आपसे दो-तीन छोटे सवाल पूछ सकता हूँ? आप मना कर सकते हैं।",
    "hi-en": "Namaste, main Pramana hoon, building ki WiFi aur power problem theek karne mein "
    "madad kar raha hoon. Kya main aapse do-teen chhote sawaal pooch sakta hoon? Aap mana "
    "kar sakte hain.",
    "mr": "नमस्कार, मी प्रमाण, तुमच्या इमारतीतील वाय-फाय आणि वीजेची अडचण सोडवायला मदत करतोय. "
    "मी तुम्हाला दोन-तीन छोटे प्रश्न विचारू का? तुम्ही नाही म्हणू शकता.",
}
