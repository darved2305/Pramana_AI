"""The equipment library: what each kind of equipment can do wrong and how people can check it.

Site authors never write physics rules. Like an asset register in maintenance software, they
list their equipment, pick each item's type from this library and say what it depends on. Each
type brings its failure modes (in the spirit of ISO 14224's per-class failure modes: fails to
run, tripped, closed), the checks a person can make on it, and the repair that clears a fault.
``builder.py`` turns that register into a validated investigation model.

Text is written once per language with ``{name}`` (the equipment's name) and ``{place}`` (where
it is). Hindi and Marathi wording needs native review before real use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Skill = Literal["lay", "access", "technician"]
Lang = Literal["en", "hi", "mr", "hi-en"]
Text = dict[Lang, str]
StateRule = Literal["alive", "not_tripped", "not_closed", "display"]


@dataclass(frozen=True)
class FailureSpec:
    id: str
    label: str
    """English label; ``{name}`` is the equipment's name."""
    prior: float
    local: bool = False


@dataclass(frozen=True)
class CheckSpec:
    """A safe observation of one piece of equipment, made where it is."""

    id: str
    label: str
    outcomes: tuple[str, str]
    """(the outcome when the rule holds, the outcome otherwise)."""
    rule: StateRule
    probe_class: Literal["visual", "panel"]
    skill: Skill
    """The least skilled person who can make this check reliably."""
    exec_s: int
    question: Text


@dataclass(frozen=True)
class RepairSpec:
    id: str
    label: str
    fixes: str
    trade: str
    """The role id preferred for the repair ("electrician"); any technician otherwise."""
    risk: Literal["low", "medium", "high"]
    reversible: bool
    verb: str
    """For decision labels: "Send the electrician to {verb} {name}"."""
    instructions: Text


@dataclass(frozen=True)
class EquipmentType:
    id: str
    label: str
    failures: tuple[FailureSpec, ...]
    checks: tuple[CheckSpec, ...] = ()
    repairs: tuple[RepairSpec, ...] = ()
    escalation: str = "Call the vendor or service team for {name}"
    """Decision label for faults with no on-site repair."""
    keywords: tuple[str, ...] = field(default=())


def _running(noun_en: str = "running") -> CheckSpec:
    return CheckSpec(
        id="running",
        label=f"{{name}} is {noun_en}",
        outcomes=("running", "stopped"),
        rule="alive",
        probe_class="visual",
        skill="access",
        exec_s=20,
        question={
            "en": "In {place}, please look at {name}. Is it running, or stopped?",
            "hi-en": "{place} mein {name} dekhiye. Woh chal raha hai, ya band hai?",
            "hi": "{place} में {name} देखिए। वह चल रहा है, या बंद है?",
            "mr": "{place} मध्ये {name} बघा. ते चालू आहे, की बंद आहे?",
        },
    )


POWER_LIGHT = CheckSpec(
    id="power_light",
    label="Power light on {name}",
    outcomes=("on", "off"),
    rule="alive",
    probe_class="visual",
    skill="access",
    exec_s=15,
    question={
        "en": "In {place}, look at the power light on {name}. Is it on, or off?",
        "hi-en": "{place} mein {name} ki power light dekhiye. Woh on hai, ya off?",
        "hi": "{place} में {name} की पावर लाइट देखिए। वह जल रही है, या बंद है?",
        "mr": "{place} मध्ये {name} चा पॉवर दिवा बघा. तो चालू आहे, की बंद?",
    },
)

DISPLAY = CheckSpec(
    id="display",
    label="Display of {name}",
    outcomes=("lit", "blank"),
    rule="display",
    probe_class="visual",
    skill="access",
    exec_s=10,
    question={
        "en": "In {place}, look at the screen of {name}. Is it lit, or blank?",
        "hi-en": "{place} mein {name} ki screen dekhiye. Woh jal rahi hai, ya blank hai?",
        "hi": "{place} में {name} की स्क्रीन देखिए। वह जल रही है, या खाली है?",
        "mr": "{place} मध्ये {name} ची स्क्रीन बघा. ती चालू आहे, की कोरी आहे?",
    },
)

BREAKER_POSITION = CheckSpec(
    id="position",
    label="Position of {name}",
    outcomes=("up", "tripped"),
    rule="not_tripped",
    probe_class="panel",
    skill="technician",
    exec_s=20,
    question={
        "en": "At {place}, find {name}. Is its switch up, or down and tripped?",
        "hi-en": "{place} pe {name} dhoondiye. Uska switch upar hai, ya neeche trip hua hai?",
        "hi": "{place} पर {name} ढूँढिए। उसका स्विच ऊपर है, या नीचे ट्रिप हुआ है?",
        "mr": "{place} वर {name} शोधा. त्याचा स्विच वर आहे, की खाली ट्रिप झालाय?",
    },
)

VALVE_POSITION = CheckSpec(
    id="handle",
    label="Handle of {name}",
    outcomes=("open", "closed"),
    rule="not_closed",
    probe_class="panel",
    skill="access",
    exec_s=20,
    question={
        "en": "In {place}, find {name}. Is its handle along the pipe (open) or across it (closed)?",
        "hi-en": (
            "{place} mein {name} dhoondiye. "
            "Handle pipe ke saath seedha hai (khula) ya aada hai (band)?"
        ),
        "hi": "{place} में {name} ढूँढिए। हैंडल पाइप के साथ सीधा है (खुला) या आड़ा है (बंद)?",
        "mr": "{place} मध्ये {name} शोधा. हँडल पाइपच्या बाजूने सरळ आहे (उघडा) की आडवा आहे (बंद)?",
    },
)

CONTENTS = CheckSpec(
    id="contents",
    label="{name} has water",
    outcomes=("has_water", "empty"),
    rule="alive",
    probe_class="visual",
    skill="access",
    exec_s=40,
    question={
        "en": "At {place}, please look inside {name}. Is there water in it, or is it empty?",
        "hi-en": "{place} pe {name} ke andar dekhiye. Usme paani hai, ya khaali hai?",
        "hi": "{place} पर {name} के अंदर देखिए। उसमें पानी है, या ख़ाली है?",
        "mr": "{place} वर {name} च्या आत बघा. त्यात पाणी आहे, की रिकामे आहे?",
    },
)

SUPPLY_IN = CheckSpec(
    id="incoming",
    label="Supply arriving from {name}",
    outcomes=("yes", "no"),
    rule="alive",
    probe_class="visual",
    skill="access",
    exec_s=25,
    question={
        "en": "At {place}, check the incoming {name}. Is supply arriving? Yes or no?",
        "hi-en": "{place} pe aane wali {name} check kijiye. Supply aa rahi hai? Haan ya nahi?",
        "hi": "{place} पर आने वाली {name} जाँचिए। सप्लाई आ रही है? हाँ या नहीं?",
        "mr": "{place} वर येणारी {name} तपासा. पुरवठा येतोय का? हो की नाही?",
    },
)


def _instructions(verb_en: str, verb_hien: str, verb_hi: str, verb_mr: str) -> Text:
    return {
        "en": f"You are cleared to {verb_en} {{target}} at {{place}}. "
        "Please confirm once it is done.",
        "hi-en": f"Aapko {{place}} pe {{target}} {verb_hien} ki permission mil gayi hai. "
        "Ho jaye toh bataiye.",
        "hi": f"आपको {{place}} पर {{target}} {verb_hi} की अनुमति मिल गई है। हो जाए तो बताइए।",
        "mr": f"तुम्हाला {{place}} येथे {{target}} {verb_mr} परवानगी मिळाली आहे. झाल्यावर सांगा.",
    }


RESET = RepairSpec(
    id="reset",
    label="Reset a tripped breaker",
    fixes="tripped",
    trade="electrician",
    risk="medium",
    reversible=True,
    verb="reset",
    instructions=_instructions("reset", "reset karne", "रीसेट करने", "रीसेट करण्याची"),
)
OPEN_VALVE = RepairSpec(
    id="open",
    label="Open a closed valve",
    fixes="closed",
    trade="plumber",
    risk="low",
    reversible=True,
    verb="open",
    instructions=_instructions("open", "kholne", "खोलने", "उघडण्याची"),
)
RESTART = RepairSpec(
    id="restart",
    label="Restart a stopped unit",
    fixes="stopped",
    trade="technician",
    risk="low",
    reversible=True,
    verb="restart",
    instructions=_instructions("restart", "restart karne", "फिर से चालू करने", "पुन्हा सुरू करण्याची"),
)


def _t(
    tid: str,
    label: str,
    failures: list[FailureSpec],
    checks: list[CheckSpec],
    repairs: list[RepairSpec] | None = None,
    escalation: str = "Call the vendor or service team for {name}",
    keywords: tuple[str, ...] = (),
) -> EquipmentType:
    return EquipmentType(
        tid, label, tuple(failures), tuple(checks), tuple(repairs or ()), escalation, keywords
    )


DEAD = FailureSpec("failed", "{name} failed", 0.004)
STOPPED = FailureSpec("stopped", "{name} stopped working", 0.006)
"""For units a technician restarts. "Failed for good" looks the same to anyone looking, so it is
not a separate mode: if the restart does not hold, verification fails and the case reopens."""

LIBRARY: dict[str, EquipmentType] = {
    t.id: t
    for t in [
        _t(
            "utility_supply",
            "Outside supply (grid power, municipal water, internet line)",
            [FailureSpec("cut", "{name} cut off", 0.006)],
            [SUPPLY_IN],
            escalation="Report the outage of {name} to the provider",
            keywords=("grid", "municipal", "supply", "isp", "mains"),
        ),
        _t(
            "breaker",
            "Circuit breaker",
            [FailureSpec("tripped", "{name} tripped", 0.005)],
            [BREAKER_POSITION],
            [RESET],
            keywords=("breaker", "mcb", "fuse"),
        ),
        _t(
            "generator",
            "Backup generator or UPS",
            [DEAD],
            [_running()],
            escalation="Call the service team for {name}",
            keywords=("generator", "dg", "ups", "inverter"),
        ),
        _t(
            "pump",
            "Pump",
            [DEAD],
            [_running()],
            escalation="Send the plumber to repair {name}",
            keywords=("pump", "motor"),
        ),
        _t(
            "valve",
            "Valve",
            [FailureSpec("closed", "{name} left closed", 0.004)],
            [VALVE_POSITION],
            [OPEN_VALVE],
            keywords=("valve",),
        ),
        _t(
            "tank",
            "Tank or reservoir",
            [],
            [CONTENTS],
            keywords=("tank", "sump", "reservoir"),
        ),
        _t(
            "controller",
            "Control panel or controller",
            [
                FailureSpec("failed", "{name} failed", 0.003),
                FailureSpec(
                    "display_dead", "Display of {name} failed (rest unaffected)", 0.002, local=True
                ),
            ],
            [DISPLAY],
            keywords=("controller", "panel", "plc", "control"),
        ),
        _t(
            "air_handler",
            "Air handler, fan or AC unit",
            [STOPPED],
            [_running()],
            [RESTART],
            escalation="Call the HVAC technician for {name}",
            keywords=("ahu", "ac", "fan", "fcu", "hvac", "air"),
        ),
        _t(
            "chiller",
            "Chiller or compressor",
            [STOPPED],
            [_running(), DISPLAY],
            [RESTART],
            escalation="Call the HVAC vendor for {name}",
            keywords=("chiller", "compressor"),
        ),
        _t(
            "lift",
            "Lift or escalator",
            [STOPPED],
            [DISPLAY],
            [RESTART],
            escalation="Call the lift vendor for {name}",
            keywords=("lift", "elevator", "escalator"),
        ),
        _t(
            "network_device",
            "Network switch, router or gateway",
            [STOPPED],
            [POWER_LIGHT],
            [RESTART],
            escalation="IT on site: replace {name}",
            keywords=("switch", "router", "gateway", "modem", "ont"),
        ),
        _t(
            "access_point",
            "Wi-Fi access point",
            [DEAD],
            [POWER_LIGHT],
            escalation="IT: replace {name}",
            keywords=("ap", "access point", "wifi"),
        ),
        _t(
            "terminal",
            "Terminal or appliance (POS, kiosk, monitor, medical device)",
            [STOPPED],
            [DISPLAY],
            [RESTART],
            keywords=("pos", "terminal", "kiosk", "monitor", "device"),
        ),
        _t(
            "server",
            "Server or service",
            [STOPPED],
            [],
            [RESTART],
            escalation="IT (remote): restore {name}",
            keywords=("server", "dhcp", "dns", "service", "nvr"),
        ),
        _t(
            "distribution",
            "Distribution point (pipe riser, cable run, duct)",
            [FailureSpec("blocked", "{name} blocked or broken", 0.002)],
            [],
            escalation="Send a technician to trace {name}",
            keywords=("riser", "pipe", "duct", "cable"),
        ),
    ]
}
