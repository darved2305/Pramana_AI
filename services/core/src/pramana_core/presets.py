"""Small, documented scenarios used by the console and text runner."""

from __future__ import annotations

from pramana_contracts import CreateInvestigation, InvestigationPreset


def investigation_presets() -> list[InvestigationPreset]:
    return [
        InvestigationPreset(
            id="S2",
            title="Different Wi-Fi access points",
            description=(
                "Aarav's room 205 phone works on AP-2B while Neha's room 210 phone cannot "
                "connect to AP-2A. The tie-break reads the listed access point."
            ),
            request=CreateInvestigation.model_validate(
                {
                    "pack_id": "campus_block_c",
                    "participants": [
                        {
                            "id": "p_aarav",
                            "display_name": "Aarav",
                            "roles": ["student"],
                            "skill": "lay",
                            "location_id": "F2_R205",
                            "languages": {
                                "stt_candidates": ["en-IN"],
                                "template_language": "en",
                            },
                            "question_budget": 12,
                        },
                        {
                            "id": "p_neha",
                            "display_name": "Neha",
                            "roles": ["student"],
                            "skill": "lay",
                            "location_id": "F2_R210",
                            "languages": {
                                "stt_candidates": ["en-IN"],
                                "template_language": "en",
                            },
                            "question_budget": 12,
                        },
                    ],
                    "report": {
                        "text": "The internet works and common websites load in room 205.",
                        "reporter_id": "p_aarav",
                        "affected_location_id": "F2_R205",
                    },
                    "scenario": {
                        "seed": 2002,
                        "fault": {"faults": [{"component_id": "AP_2A", "mode": "dead"}]},
                    },
                }
            ),
        ),
        InvestigationPreset(
            id="S7",
            title="Guard presence check at IDF-2",
            description=(
                "Aarav reports that room 205 has no Wi-Fi. The guard is asked to read the "
                "switch lights in restricted closet IDF-2."
            ),
            adversarial_participant_id="p_mahesh",
            request=CreateInvestigation.model_validate(
                {
                    "pack_id": "campus_block_c",
                    "participants": [
                        {
                            "id": "p_aarav",
                            "display_name": "Aarav",
                            "roles": ["student"],
                            "skill": "lay",
                            "location_id": "F2_R205",
                            "languages": {
                                "stt_candidates": ["en-IN"],
                                "template_language": "en",
                            },
                            "question_budget": 10,
                        },
                        {
                            "id": "p_mahesh",
                            "display_name": "Mahesh",
                            "roles": ["guard"],
                            "skill": "access",
                            "location_id": "GUARD_DESK",
                            "languages": {
                                "stt_candidates": ["mr-IN", "hi-IN"],
                                "template_language": "mr",
                            },
                            "question_budget": 10,
                        },
                        {
                            "id": "p_suresh",
                            "display_name": "Suresh",
                            "roles": ["guard", "electrician"],
                            "skill": "access",
                            "location_id": "GUARD_DESK",
                            "languages": {
                                "stt_candidates": ["mr-IN", "hi-IN"],
                                "template_language": "mr",
                            },
                            "question_budget": 10,
                        },
                    ],
                    "report": {
                        "text": "There is no Wi-Fi in room 205 and websites do not load.",
                        "reporter_id": "p_aarav",
                        "affected_location_id": "F2_R205",
                    },
                    "scenario": {
                        "seed": 2007,
                        "fault": {"faults": [{"component_id": "CB_C2_7", "mode": "tripped"}]},
                    },
                }
            ),
        ),
    ]


def get_investigation_preset(preset_id: str) -> InvestigationPreset:
    for preset in investigation_presets():
        if preset.id == preset_id:
            return preset
    raise KeyError(preset_id)
