"""Give every workspace a neutral, immutable practice model.

Revision ID: 0021
Revises: 0016
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

revision: str = "0021"
down_revision: str | None = "0016"
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
        "FEED_MAIN": "Main power supply",
        "FEED_C2": "Power supply to floor 2",
        "CB_MAIN_1": "Main breaker",
        "CB_C2_5": "Lighting breaker for floors 2 and 3",
        "CB_C2_7": "Equipment room 2 breaker",
        "LIGHT_IDF2": "Equipment room 2 lights",
        "NVR_C2": "Security camera recorder in equipment room 2",
        "SOCKETS_F2": "Power sockets in work areas on floor 2",
        "SOCKETS_F3": "Power sockets in work areas on floor 3",
        "ISP_LINK": "Internet provider connection",
        "ONT": "Fibre connection box",
        "GATEWAY": "Internet router",
        "DHCP": "Service that gives devices network addresses",
        "DNS": "Service that helps websites load by name",
        "SW_CORE": "Main network switch",
        "SW_C2": "Network switch in equipment room 2",
        "AP_1A": "Wi-Fi access point 1A",
        "AP_2A": "Wi-Fi access point 2A",
        "AP_2B": "Wi-Fi access point 2B",
        "AP_3A": "Wi-Fi access point 3A",
        "AP_3B": "Wi-Fi access point 3B",
    }
    components = result.get("components")
    if isinstance(components, list):
        failure_copy = {
            "FEED_C2": "Power supply to floor 2 interrupted",
            "CB_MAIN_1": "Main breaker tripped",
            "CB_C2_5": "Lighting breaker for floors 2 and 3 tripped",
            "CB_C2_7": "Equipment room 2 breaker tripped",
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
        "DISPATCH_ELECTRICIAN_DB_C2": "Facilities technician: check the floor 2 electrical panel",
        "ESCALATE_FACILITIES_POWER": "Ask the facilities team to check the floor 2 power supply",
        "DISPATCH_ELECTRICIAN_MAIN": "Facilities technician: check the main breaker",
        "IT_ONSITE_SW_C2": "Network technician: replace the switch in equipment room 2",
        "IT_ONSITE_CORE": "Network technician: check the main switch or internet router",
        "IT_REPLACE_AP_1A": "Replace Wi-Fi access point 1A",
        "IT_REPLACE_AP_2A": "Replace Wi-Fi access point 2A",
        "IT_REPLACE_AP_2B": "Replace Wi-Fi access point 2B",
        "IT_REPLACE_AP_3A": "Replace Wi-Fi access point 3A",
        "IT_REPLACE_AP_3B": "Replace Wi-Fi access point 3B",
        "IT_FIX_DHCP": "Restore the service that gives devices network addresses",
        "IT_FIX_DNS": "Restore the service that helps websites load by name",
        "ESCALATE_ISP": "Report a problem to the internet provider",
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
                    "Site Wi-Fi on the phone",
                    "Open your phone's Wi-Fi list. Do you see the site's network, "
                    "is it still connecting, or is it connected?",
                    "फ़ोन की वाई-फ़ाई सूची खोलें। क्या साइट का नेटवर्क दिख रहा है, "
                    "जुड़ने की कोशिश कर रहा है, या जुड़ चुका है?",
                    "Phone ki Wi-Fi list kholiye. Kya site ka network dikh raha hai, "
                    "connecting hai, ya connected hai?",
                    "फोनची वाय-फाय यादी उघडा. साइटचे नेटवर्क दिसत आहे, कनेक्ट होत आहे, की कनेक्ट झाले आहे?",
                ),
                "web_by_ip": (
                    "Internet test page opens",
                    "Please open the saved internet test page on your phone. "
                    "Does it open? Yes or no?",
                    "फ़ोन पर सेव किया हुआ इंटरनेट जाँच पेज खोलें। क्या वह खुलता है? हाँ या नहीं?",
                    "Phone par saved internet test page kholiye. Kya woh khulta hai? Haan ya nahi?",
                    "फोनवर जतन केलेले इंटरनेट तपासणीचे पान उघडा. ते उघडते का? हो की नाही?",
                ),
                "ap_light": (
                    "Network device light",
                    "At {place}, look for the small network device on the ceiling. "
                    "Is its light on or off?",
                    "{place} में छत पर लगे छोटे नेटवर्क उपकरण को देखें। उसकी बत्ती चालू है या बंद?",
                    "{place} mein chhat par lage chhote network device ko dekhiye. "
                    "Uski light on hai ya off?",
                    "{place} मध्ये छतावरचे छोटे नेटवर्क उपकरण पाहा. त्याचा दिवा चालू आहे की बंद?",
                ),
                "breaker_c2_7": (
                    "Equipment room 2 breaker position",
                    "At {place}, without touching anything, is the equipment room 2 "
                    "breaker up or tripped down?",
                    "{place} पर, बिना कुछ छुए, उपकरण कक्ष 2 का ब्रेकर ऊपर है या ट्रिप होकर नीचे?",
                    "{place} par, bina kuch chhue, equipment room 2 ka breaker "
                    "upar hai ya trip hokar neeche?",
                    "{place} येथे, कशालाही हात न लावता, उपकरण कक्ष 2 चा ब्रेकर वर आहे की ट्रिप होऊन खाली?",
                ),
                "breaker_c2_5": (
                    "Lighting breaker position",
                    "At {place}, without touching anything, is the lighting breaker "
                    "up or tripped down?",
                    "{place} पर, बिना कुछ छुए, लाइटों का ब्रेकर ऊपर है या ट्रिप होकर नीचे?",
                    "{place} par, bina kuch chhue, lights ka breaker upar hai ya "
                    "trip hokar neeche?",
                    "{place} येथे, कशालाही हात न लावता, दिव्यांचा ब्रेकर वर आहे की ट्रिप होऊन खाली?",
                ),
                "breaker_main_1": (
                    "Main breaker position",
                    "At {place}, without touching anything, is the main breaker up "
                    "or tripped down?",
                    "{place} पर, बिना कुछ छुए, मुख्य ब्रेकर ऊपर है या ट्रिप होकर नीचे?",
                    "{place} par, bina kuch chhue, main breaker upar hai ya trip hokar neeche?",
                    "{place} येथे, कशालाही हात न लावता, मुख्य ब्रेकर वर आहे की ट्रिप होऊन खाली?",
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
