"""Give every workspace a neutral, immutable practice model.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEMPLATE_ID = uuid.UUID("019a5e00-0000-7000-8000-000000000017")
MODEL_NAMESPACE = uuid.UUID("019a5e00-0000-7000-8000-000000000018")
PRACTICE_SITE_NAME = "Practice site (simulated)"
OLD_SITE_NAME = "Sample hostel (simulated)"


def _neutral_spec(spec: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(spec)
    result["title"] = PRACTICE_SITE_NAME

    # Keep the model's stable ids and physics, but give new workspaces a practice scenario that
    # does not assume they run a hostel. Historical templates and published models stay untouched.
    result["roles"] = [
        {"id": "student", "skill": "lay", "label": "Site colleague"},
        {"id": "guard", "skill": "access", "label": "Site staff"},
        {"id": "electrician", "skill": "technician", "label": "Facilities technician"},
        {"id": "it_tech", "skill": "technician", "label": "Network technician"},
        {"id": "housekeeping", "skill": "access", "label": "Facilities staff"},
    ]

    location_copy = {
        "GUARD_DESK": ("the site reception", "साइट का रिसेप्शन", "site ka reception", "साइटचे रिसेप्शन"),
        "MAINT_ROOM": ("the equipment room", "उपकरण कक्ष", "equipment room", "उपकरण कक्ष"),
        "F1_LOBBY": (
            "the ground-floor lobby",
            "भूतल की लॉबी",
            "ground floor ki lobby",
            "तळमजल्याची लॉबी",
        ),
        "IDF1": (
            "equipment room 1",
            "पहले तल का उपकरण कक्ष",
            "first floor ka equipment room",
            "पहिल्या मजल्यावरील उपकरण कक्ष",
        ),
        "F2_CORRIDOR": (
            "the second-floor corridor",
            "दूसरे तल का गलियारा",
            "second floor ka corridor",
            "दुसऱ्या मजल्यावरील कॉरिडॉर",
        ),
        "F2_R205": ("work area 205", "कार्य क्षेत्र 205", "work area 205", "कामाची जागा 205"),
        "F2_R210": ("work area 210", "कार्य क्षेत्र 210", "work area 210", "कामाची जागा 210"),
        "IDF2": (
            "equipment room 2",
            "दूसरे तल का उपकरण कक्ष",
            "second floor ka equipment room",
            "दुसऱ्या मजल्यावरील उपकरण कक्ष",
        ),
        "DB_C2_PANEL": ("the electrical panel", "बिजली का पैनल", "electrical panel", "विद्युत पॅनेल"),
        "F3_CORRIDOR": (
            "the third-floor corridor",
            "तीसरे तल का गलियारा",
            "third floor ka corridor",
            "तिसऱ्या मजल्यावरील कॉरिडॉर",
        ),
        "F3_R304": ("work area 304", "कार्य क्षेत्र 304", "work area 304", "कामाची जागा 304"),
        "F3_R310": ("work area 310", "कार्य क्षेत्र 310", "work area 310", "कामाची जागा 310"),
    }
    locations = result.get("locations")
    if isinstance(locations, list):
        for location in locations:
            if not isinstance(location, dict):
                continue
            words = location_copy.get(str(location.get("id")))
            label = location.get("label")
            if words and isinstance(label, dict):
                label.update(dict(zip(("en", "hi", "hi_en", "mr"), words, strict=True)))

    component_copy = {
        "FEED_MAIN": "Electricity supply",
        "FEED_C2": "Power supply for floor 2",
        "CB_MAIN_1": "Main power switch",
        "CB_C2_5": "Power switch for the floor 2 and 3 lights",
        "CB_C2_7": "Power switch in equipment room 2",
        "LIGHT_IDF2": "Equipment room 2 light",
        "NVR_C2": "Security video recorder",
        "SOCKETS_F2": "Wall sockets in floor 2 work areas",
        "SOCKETS_F3": "Wall sockets in floor 3 work areas",
        "ISP_LINK": "Internet connection",
        "ONT": "Internet connection box",
        "GATEWAY": "Internet router",
        "DHCP": "Service that connects devices to the network",
        "DNS": "Service that helps websites open by name",
        "SW_CORE": "Main network device",
        "SW_C2": "Network device in equipment room 2",
        "AP_1A": "Ceiling network device in area 1A",
        "AP_2A": "Ceiling network device in area 2A",
        "AP_2B": "Ceiling network device in area 2B",
        "AP_3A": "Ceiling network device in area 3A",
        "AP_3B": "Ceiling network device in area 3B",
    }
    components = result.get("components")
    if isinstance(components, list):
        failure_copy = {
            "FEED_C2": "Power supply interrupted",
            "CB_MAIN_1": "Main power switch tripped",
            "CB_C2_5": "Lighting power switch tripped",
            "CB_C2_7": "Equipment room power switch tripped",
            "ISP_LINK": "Internet connection interrupted",
            "GATEWAY": "Internet router not working",
            "DHCP": "Devices cannot connect to the network",
            "DNS": "Websites cannot be found by name",
            "SW_CORE": "Main network device not working",
            "SW_C2": "Network device in equipment room 2 not working",
            "AP_1A": "Ceiling network device in area 1A not working",
            "AP_2A": "Ceiling network device in area 2A not working",
            "AP_2B": "Ceiling network device in area 2B not working",
            "AP_3A": "Ceiling network device in area 3A not working",
            "AP_3B": "Ceiling network device in area 3B not working",
        }
        for component in components:
            if not isinstance(component, dict):
                continue
            component_id = str(component.get("id"))
            if component_id in component_copy:
                component["label"] = component_copy[component_id]
            failures = component.get("failure_modes")
            if isinstance(failures, list) and component_id in failure_copy:
                for failure in failures:
                    if isinstance(failure, dict):
                        failure["label"] = failure_copy[component_id]

    decision_copy = {
        "DISPATCH_ELECTRICIAN_DB_C2": "Facilities technician: check the floor 2 power panel",
        "ESCALATE_FACILITIES_POWER": "Ask the facilities team to check the floor 2 power supply",
        "DISPATCH_ELECTRICIAN_MAIN": "Facilities technician: check the main power switch",
        "IT_ONSITE_SW_C2": "Network technician: check the network equipment in room 2",
        "IT_ONSITE_CORE": "Network technician: check the main network device or internet router",
        "IT_REPLACE_AP_1A": "Replace the ceiling network device in area 1A",
        "IT_REPLACE_AP_2A": "Replace the ceiling network device in area 2A",
        "IT_REPLACE_AP_2B": "Replace the ceiling network device in area 2B",
        "IT_REPLACE_AP_3A": "Replace the ceiling network device in area 3A",
        "IT_REPLACE_AP_3B": "Replace the ceiling network device in area 3B",
        "IT_FIX_DHCP": "Restore device access to the network",
        "IT_FIX_DNS": "Help websites open by name",
        "ESCALATE_ISP": "Contact the internet provider about an interruption",
        "NO_ACTION_USER_SIDE": "The site network works; help the person with their phone",
    }
    decisions = result.get("decision_classes")
    if isinstance(decisions, list):
        for decision in decisions:
            if isinstance(decision, dict) and decision.get("id") in decision_copy:
                decision["label"] = decision_copy[str(decision["id"])]

    probes = result.get("probes")
    if isinstance(probes, list):
        for probe in probes:
            if not isinstance(probe, dict):
                continue
            probe_id = str(probe.get("id"))
            probe_copy = {
                "internet_works": (
                    "Internet access on a phone",
                    "On your phone, does a normal website open? Please say yes or no.",
                    "क्या आपके फ़ोन पर कोई सामान्य वेबसाइट खुलती है? हाँ या नहीं बताइए।",
                    "Aapke phone par koi normal website khul rahi hai? Haan ya nahi batayiye.",
                    "तुमच्या फोनवर एखादी साधी वेबसाइट उघडते का? हो किंवा नाही सांगा.",
                ),
                "wifi_status": (
                    "Site network on the phone",
                    "On your phone, open the list of available networks. Is this site's "
                    "network missing, still connecting, or connected?",
                    "अपने फ़ोन पर उपलब्ध नेटवर्क की सूची खोलें। क्या साइट का नेटवर्क नहीं दिख रहा, "
                    "जुड़ने की कोशिश कर रहा है, या जुड़ चुका है?",
                    "Phone par available network ki list kholiye. "
                    "Kya site ka network nahi dikh raha, connect hone ki koshish kar raha hai, "
                    "ya connect ho chuka hai?",
                    "तुमच्या फोनवर उपलब्ध नेटवर्कची यादी उघडा. "
                    "साइटचे नेटवर्क दिसत नाही, जोडण्याचा प्रयत्न करत आहे, की जोडले आहे?",
                ),
                "web_by_ip": (
                    "Internet check page opens",
                    "Please open the test page on your phone. Does it load? Yes or no?",
                    "अपने फ़ोन पर जाँच वाला पेज खोलें। क्या वह खुलता है? हाँ या नहीं?",
                    "Phone par jaanch wala page kholiye. Kya woh khulta hai? Haan ya nahi?",
                    "तुमच्या फोनवर तपासणीचे पान उघडा. ते उघडते का? हो की नाही?",
                ),
                "ap_light": (
                    "Ceiling device light",
                    "Look at the small device on the ceiling. Is its light on or off?",
                    "छत पर लगे छोटे उपकरण को देखें। उसकी बत्ती चालू है या बंद?",
                    "Chhat par lage chhote device ko dekhiye. Uski light on hai ya off?",
                    "छतावरचे छोटे उपकरण पाहा. त्याचा दिवा चालू आहे की बंद?",
                ),
                "corridor_lights": (
                    "Corridor lights",
                    "Please look at the corridor nearby. Are its lights on or off?",
                    "पास के गलियारे में देखें। वहाँ की बत्तियाँ जल रही हैं या बंद हैं?",
                    "Paas ke corridor mein dekhiye. Wahan ki lights on hain ya off?",
                    "जवळच्या मार्गिकेत पाहा. तिथले दिवे चालू आहेत की बंद?",
                ),
                "switch_leds": (
                    "Network device lights",
                    "Look at the box with several network cables. "
                    "Are its small lights green, orange, or off?",
                    "कई नेटवर्क तारों वाले डिब्बे को देखें। उसकी छोटी बत्तियाँ हरी, नारंगी, या बंद हैं?",
                    "Kai network cables wale box ko dekhiye. "
                    "Uski chhoti lights green, orange, ya off hain?",
                    "अनेक नेटवर्क तारा जोडलेला डबा पाहा. त्याचे छोटे दिवे हिरवे, नारंगी, की बंद आहेत?",
                ),
                "nvr_screen": (
                    "Security camera screen",
                    "Look at the small screen used to view security cameras. Is it on or off?",
                    "सुरक्षा कैमरे देखने वाली छोटी स्क्रीन को देखें। वह चालू है या बंद?",
                    "Security cameras dekhne wali chhoti screen ko dekhiye. Woh on hai ya off?",
                    "सुरक्षा कॅमेरे पाहण्याची छोटी स्क्रीन पाहा. ती चालू आहे की बंद?",
                ),
                "closet_light": (
                    "Equipment room light",
                    "When you switch on the light, does the ceiling light come on?",
                    "बत्ती का स्विच चालू करने पर छत की बत्ती जलती है?",
                    "Light ka switch on karne par chhat ki light jalti hai?",
                    "दिवा लावल्यावर छताचा दिवा लागतो का?",
                ),
                "wan_led": (
                    "Internet router light",
                    "Look at the internet router. Is the light marked INTERNET green, red, or off?",
                    "इंटरनेट राउटर देखें। INTERNET लिखी बत्ती हरी, लाल, या बंद है?",
                    "Internet router dekhiye. INTERNET likhi light green, red, ya off hai?",
                    "इंटरनेट राउटर पाहा. INTERNET लिहिलेला दिवा हिरवा, लाल, की बंद आहे?",
                ),
                "breaker_c2_7": (
                    "Equipment room power switch position",
                    "Without touching anything, is the power switch for "
                    "equipment room 2 up or down?",
                    "बिना कुछ छुए, उपकरण कक्ष 2 का बिजली का स्विच ऊपर है या नीचे?",
                    "Bina kuch chhue, equipment room 2 ka power switch upar hai ya neeche?",
                    "कशालाही हात न लावता, उपकरण कक्ष 2 चा वीजेचा स्विच वर आहे की खाली?",
                ),
                "breaker_c2_5": (
                    "Lights power switch position",
                    "Without touching anything, is the power switch for the lights up or down?",
                    "बिना कुछ छुए, लाइटों का बिजली का स्विच ऊपर है या नीचे?",
                    "Bina kuch chhue, lights ka power switch upar hai ya neeche?",
                    "कशालाही हात न लावता, दिव्यांचा वीजेचा स्विच वर आहे की खाली?",
                ),
                "breaker_main_1": (
                    "Main power switch position",
                    "Without touching anything, is the main power switch up or down?",
                    "बिना कुछ छुए, मुख्य बिजली का स्विच ऊपर है या नीचे?",
                    "Bina kuch chhue, main power switch upar hai ya neeche?",
                    "कशालाही हात न लावता, मुख्य वीजेचा स्विच वर आहे की खाली?",
                ),
                "room_socket": (
                    "Wall socket power",
                    "Plug in a phone charger. Does the phone start charging?",
                    "फ़ोन का चार्जर लगाएँ। क्या फ़ोन चार्ज होने लगता है?",
                    "Phone charger lagaiye. Kya phone charge hone lagta hai?",
                    "फोनचा चार्जर लावा. फोन चार्ज व्हायला लागतो का?",
                ),
                "fibre_light": (
                    "Internet connection box light",
                    "Look at the internet connection box. Is its status light green, red, or off?",
                    "इंटरनेट कनेक्शन वाले डिब्बे को देखें। उसकी बत्ती हरी, लाल, या बंद है?",
                    "Internet connection box dekhiye. Uski status light green, red, ya off hai?",
                    "इंटरनेट जोडणीचा डबा पाहा. त्याची बत्ती हिरवी, लाल, की बंद आहे?",
                ),
            }.get(probe_id)
            if probe_copy:
                probe["label"] = probe_copy[0]
                probe["templates"] = dict(
                    zip(("en", "hi", "hi-en", "mr"), probe_copy[1:], strict=True)
                )

    move_templates = result.get("move_templates")
    if isinstance(move_templates, dict):
        move_templates.update(
            {
                "en": "Please go to {place}. When you get there: ",
                "hi": "कृपया {place} पर जाएँ। वहाँ पहुँचकर: ",
                "hi-en": "Kripya {place} par jaiye. Wahan pahunch kar: ",
                "mr": "कृपया {place} येथे जा. तिथे पोहोचल्यावर: ",
            }
        )

    presence_tokens = result.get("presence_tokens")
    if isinstance(presence_tokens, list):
        for token in presence_tokens:
            if not isinstance(token, dict):
                continue
            token["label"] = "Label on equipment in this room (last three characters)"
            token["templates"] = {
                "en": "Since you are in {place}, please read the last three characters "
                "on the equipment label.",
                "hi": "आप {place} में हैं। उपकरण के लेबल के आख़िरी तीन अक्षर पढ़िए।",
                "hi-en": "Aap {place} mein hain. Equipment ke label ke aakhri teen akshar padhiye.",
                "mr": "तुम्ही {place} मध्ये आहात. उपकरणावरील लेबलची शेवटची तीन अक्षरे वाचा.",
            }
    return result


def _digest(spec: dict[str, object]) -> bytes:
    canonical = json.dumps(
        spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(canonical).digest()


def upgrade() -> None:
    connection = op.get_bind()
    source = (
        connection.execute(
            sa.text(
                "select spec from model_templates where purpose = 'sandbox' "
                "order by version desc limit 1"
            )
        )
        .mappings()
        .one()
    )
    spec = _neutral_spec(source["spec"])
    digest = _digest(spec)

    templates = sa.table(
        "model_templates",
        sa.column("id", pg.UUID(as_uuid=True)),
        sa.column("name", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("purpose", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("spec", pg.JSONB()),
        sa.column("spec_sha256", sa.LargeBinary()),
    )
    connection.execute(
        templates.insert().values(
            id=TEMPLATE_ID,
            name=PRACTICE_SITE_NAME,
            kind="other",
            purpose="sandbox",
            version=2,
            spec=spec,
            spec_sha256=digest,
        )
    )

    sites = (
        connection.execute(
            sa.text("select id, org_id from sites where mode = 'sandbox' and archived_at is null")
        )
        .mappings()
        .all()
    )
    models = sa.table(
        "site_models",
        sa.column("id", pg.UUID(as_uuid=True)),
        sa.column("org_id", pg.UUID(as_uuid=True)),
        sa.column("site_id", pg.UUID(as_uuid=True)),
        sa.column("version", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("spec", pg.JSONB()),
        sa.column("spec_sha256", sa.LargeBinary()),
        sa.column("published_at", sa.DateTime(timezone=True)),
    )
    for site in sites:
        site_id = site["id"]
        org_id = site["org_id"]
        connection.execute(
            sa.text("select set_config('app.org_id', :org_id, true)"),
            {"org_id": str(org_id)},
        )
        latest = connection.execute(
            sa.text(
                "select coalesce(max(version), 0) from site_models "
                "where org_id = :org_id and site_id = :site_id"
            ),
            {"org_id": org_id, "site_id": site_id},
        ).scalar_one()
        model_id = uuid.uuid5(MODEL_NAMESPACE, f"{org_id}:{site_id}:sandbox-v2")
        connection.execute(
            models.insert().values(
                id=model_id,
                org_id=org_id,
                site_id=site_id,
                version=latest + 1,
                status="published",
                spec=spec,
                spec_sha256=digest,
                published_at=sa.func.now(),
            )
        )
        connection.execute(
            sa.text(
                "update sites set current_model_id = :model_id, name = :site_name, kind = 'other' "
                "where org_id = :org_id and id = :site_id and mode = 'sandbox'"
            ),
            {
                "model_id": model_id,
                "site_name": PRACTICE_SITE_NAME,
                "org_id": org_id,
                "site_id": site_id,
            },
        )
    connection.execute(sa.text("select set_config('app.org_id', '', true)"))


def downgrade() -> None:
    connection = op.get_bind()
    sites = (
        connection.execute(
            sa.text("select id, org_id from sites where mode = 'sandbox' and name = :site_name"),
            {"site_name": PRACTICE_SITE_NAME},
        )
        .mappings()
        .all()
    )
    for site in sites:
        connection.execute(
            sa.text("select set_config('app.org_id', :org_id, true)"),
            {"org_id": str(site["org_id"])},
        )
        model_id = uuid.uuid5(MODEL_NAMESPACE, f"{site['org_id']}:{site['id']}:sandbox-v2")
        connection.execute(
            sa.text(
                "update sites set current_model_id = ("
                "select id from site_models where org_id = :org_id and site_id = :site_id "
                "and id <> :model_id order by version desc limit 1), name = :old_name, "
                "kind = 'hostel' "
                "where org_id = :org_id and id = :site_id and current_model_id = :model_id"
            ),
            {
                "org_id": site["org_id"],
                "site_id": site["id"],
                "model_id": model_id,
                "old_name": OLD_SITE_NAME,
            },
        )
    connection.execute(sa.text("select set_config('app.org_id', '', true)"))
    op.execute("alter table site_models disable trigger site_models_immutable")
    for site in sites:
        model_id = uuid.uuid5(MODEL_NAMESPACE, f"{site['org_id']}:{site['id']}:sandbox-v2")
        connection.execute(
            sa.text("delete from site_models where id = :model_id"), {"model_id": model_id}
        )
    op.execute("alter table site_models enable trigger site_models_immutable")
    op.execute("delete from model_templates where id = '019a5e00-0000-7000-8000-000000000017'")
