/**
 * PREVIEW FIXTURES. Development sample data, never shown outside preview mode.
 *
 * These let every screen be inspected in a populated state without a running core.
 * They are hand-written to match the API schemas and the campus_block_c pack, but the
 * numbers are illustrative: they are not engine output and must never be presented as
 * results. Every screen that renders them shows a "Preview data" label.
 */
import type {
  Approval,
  BeliefSnapshot,
  EventEnvelope,
  InvestigationState,
  Observation,
  ParticipantSpec,
  PlanDecision,
  Question,
  SitePack,
} from "@/lib/api/types";

import { PREVIEW_ID } from "./ids";
export { PREVIEW_ID };

export const previewPack: SitePack = {
  id: "campus_block_c",
  version: "0.1.0",
  title: "Hostel Block C (simulated)",
  walking_roles: ["guard", "electrician", "it_tech", "housekeeping"],
  locations: [
    { id: "GUARD_DESK", floor: 1, kind: "desk", label: "the guard desk", restricted: false, access_roles: [] },
    { id: "MAINT_ROOM", floor: 1, kind: "room", label: "the maintenance room", restricted: false, access_roles: [] },
    { id: "F1_LOBBY", floor: 1, kind: "corridor", label: "the ground-floor lobby", restricted: false, access_roles: [] },
    { id: "IDF1", floor: 1, kind: "closet", label: "network closet IDF-1", restricted: true, access_roles: ["guard", "it_tech", "electrician"] },
    { id: "F2_CORRIDOR", floor: 2, kind: "corridor", label: "the second-floor corridor", restricted: false, access_roles: [] },
    { id: "F2_R205", floor: 2, kind: "room", label: "room 205", restricted: false, access_roles: [] },
    { id: "F2_R210", floor: 2, kind: "room", label: "room 210", restricted: false, access_roles: [] },
    { id: "IDF2", floor: 2, kind: "closet", label: "network closet IDF-2", restricted: true, access_roles: ["guard", "it_tech", "electrician"] },
    { id: "DB_C2_PANEL", floor: 2, kind: "panel", label: "distribution board DB-C2", restricted: true, access_roles: ["electrician", "guard"] },
    { id: "F3_CORRIDOR", floor: 3, kind: "corridor", label: "the third-floor corridor", restricted: false, access_roles: [] },
    { id: "F3_R304", floor: 3, kind: "room", label: "room 304", restricted: false, access_roles: [] },
    { id: "F3_R310", floor: 3, kind: "room", label: "room 310", restricted: false, access_roles: [] },
  ],
  probes: [
    { id: "internet_works", label: "Internet works on the hostel Wi-Fi", outcomes: ["yes", "no"], roles: ["any"], locations: [] },
    { id: "wifi_status", label: "Wi-Fi status on the phone", outcomes: ["no_network", "stuck_connecting", "connected"], roles: ["any"], locations: [] },
    { id: "web_by_ip", label: "IP test page loads", outcomes: ["yes", "no"], roles: ["any"], locations: [] },
    { id: "corridor_lights", label: "Corridor lights", outcomes: ["on", "off"], roles: ["any"], locations: [] },
    { id: "ap_light", label: "Access-point status light", outcomes: ["on", "off"], roles: ["any"], locations: [] },
    { id: "switch_leds", label: "Network switch lights", outcomes: ["green", "amber", "off"], roles: ["guard", "it_tech", "electrician"], locations: ["IDF2", "IDF1"] },
    { id: "nvr_screen", label: "CCTV recorder screen", outcomes: ["on", "off"], roles: ["guard", "it_tech", "electrician"], locations: ["IDF2"] },
    { id: "closet_light", label: "Closet ceiling light", outcomes: ["on", "off"], roles: ["guard", "it_tech", "electrician"], locations: ["IDF2"] },
    { id: "wan_led", label: "Gateway internet light", outcomes: ["green", "red", "off"], roles: ["guard", "it_tech"], locations: ["IDF1"] },
    { id: "breaker_c2_7", label: "Breaker C2-7 position", outcomes: ["up", "tripped"], roles: ["electrician"], locations: ["DB_C2_PANEL"] },
  ],
  decision_classes: [
    { id: "DISPATCH_ELECTRICIAN_DB_C2", label: "Send the electrician to panel DB-C2" },
    { id: "ESCALATE_FACILITIES_POWER", label: "Escalate the DB-C2 supply loss to facilities" },
    { id: "DISPATCH_ELECTRICIAN_MAIN", label: "Send the electrician to breaker MAIN-1" },
    { id: "IT_ONSITE_SW_C2", label: "IT on site: replace switch SW-C2" },
    { id: "IT_ONSITE_CORE", label: "IT on site: core switch or gateway in IDF-1" },
    { id: "IT_REPLACE_AP_3A", label: "IT: replace access point 3A" },
    { id: "IT_REPLACE_AP_3B", label: "IT: replace access point 3B" },
    { id: "IT_FIX_DHCP", label: "IT (remote): restore the DHCP service" },
    { id: "ESCALATE_ISP", label: "Raise a ticket with the ISP" },
    { id: "NO_ACTION_USER_SIDE", label: "No building fault: help the reporter with their device" },
  ],
};

export const previewParticipants: ParticipantSpec[] = [
  {
    id: "p_riya",
    display_name: "Riya",
    roles: ["student"],
    skill: "lay",
    location_id: "F3_R304",
    languages: { stt_candidates: ["hi-IN", "en-IN"], template_language: "hi-en", codemix: true },
  },
  {
    id: "p_mahesh",
    display_name: "Mahesh",
    roles: ["guard"],
    skill: "access",
    location_id: "GUARD_DESK",
    languages: { stt_candidates: ["mr-IN", "hi-IN"], template_language: "mr", codemix: false },
  },
  {
    id: "p_imran",
    display_name: "Imran",
    roles: ["electrician"],
    skill: "technician",
    location_id: "MAINT_ROOM",
    languages: { stt_candidates: ["hi-IN"], template_language: "hi", codemix: false },
  },
  {
    id: "p_asha",
    display_name: "Asha",
    roles: ["housekeeping"],
    skill: "lay",
    location_id: "F2_CORRIDOR",
    languages: { stt_candidates: ["mr-IN"], template_language: "mr", codemix: false },
  },
];

const T0 = Date.parse("2026-11-04T09:12:00Z");
const at = (s: number) => new Date(T0 + s * 1000).toISOString();

function obs(
  n: number,
  p: string,
  loc: string,
  probe: string,
  outcome: string,
  s: number,
  extra: Partial<Observation> = {},
): Observation {
  return {
    id: `o${n}`,
    participant_id: p,
    location_id: loc,
    probe_id: probe,
    outcome,
    committed_at: at(s),
    directness: "direct",
    hedge: "certain",
    modality: "voice",
    extraction_method: "rules",
    question_id: `q${n}`,
    state: "committed",
    transcript: null,
    ...extra,
  };
}

const observations: Observation[] = [
  obs(1, "p_riya", "F3_R304", "wifi_status", "no_network", 48, {
    transcript: "WiFi list mein NAVA-WiFi dikh hi nahi raha.",
  }),
  obs(2, "p_mahesh", "GUARD_DESK", "internet_works", "yes", 131, {
    transcript: "हो, इथे इंटरनेट चालू आहे.",
  }),
  obs(3, "p_asha", "F2_CORRIDOR", "corridor_lights", "on", 205, { modality: "tap", extraction_method: "structured" }),
  obs(4, "p_asha", "F2_CORRIDOR", "ap_light", "off", 262, {
    hedge: "probable",
    transcript: "मला वाटतं दिवा बंद आहे.",
  }),
  obs(5, "p_riya", "F3_R304", "wifi_status", "connected", 330, {
    hedge: "unsure",
    directness: "hearsay",
    transcript: "Mere roommate ka phone connected dikha raha hai shayad.",
    state: "superseded",
  }),
];

const belief: BeliefSnapshot = {
  observations_used: 4,
  hypothesis_entropy_bits: 2.31,
  decision_entropy_bits: 1.74,
  open_world_probability: 0.014,
  expected_loss_now_min: 11.6,
  map_decision: "DISPATCH_ELECTRICIAN_DB_C2",
  map_decision_probability: 0.47,
  hypotheses: [
    { id: "CB_C2_7.tripped", label: "Breaker C2-7 tripped", decision_class: "DISPATCH_ELECTRICIAN_DB_C2", probability: 0.43 },
    { id: "SW_C2.dead", label: "Switch SW-C2 dead", decision_class: "IT_ONSITE_SW_C2", probability: 0.22 },
    { id: "AP_2A.dead", label: "Access point 2A dead", decision_class: "IT_REPLACE_AP_2A", probability: 0.11 },
    { id: "AP_3A.dead", label: "Access point 3A dead", decision_class: "IT_REPLACE_AP_3A", probability: 0.09 },
    { id: "FEED_C2.lost", label: "Upstream power interruption to DB-C2", decision_class: "ESCALATE_FACILITIES_POWER", probability: 0.06 },
    { id: "CB_C2_5.tripped", label: "Breaker C2-5 tripped", decision_class: "DISPATCH_ELECTRICIAN_DB_C2", probability: 0.04 },
    { id: "DHCP.down", label: "DHCP service down", decision_class: "IT_FIX_DHCP", probability: 0.022 },
    { id: "NO_FAULT", label: "No building fault", decision_class: "NO_ACTION_USER_SIDE", probability: 0.004 },
  ],
  decisions: [
    { id: "DISPATCH_ELECTRICIAN_DB_C2", label: "Send the electrician to panel DB-C2", probability: 0.47 },
    { id: "IT_ONSITE_SW_C2", label: "IT on site: replace switch SW-C2", probability: 0.22 },
    { id: "IT_REPLACE_AP_2A", label: "IT: replace access point 2A", probability: 0.11 },
    { id: "IT_REPLACE_AP_3A", label: "IT: replace access point 3A", probability: 0.09 },
    { id: "ESCALATE_FACILITIES_POWER", label: "Escalate the DB-C2 supply loss to facilities", probability: 0.06 },
    { id: "IT_FIX_DHCP", label: "IT (remote): restore the DHCP service", probability: 0.022 },
  ],
  repair: null,
};

const plan: PlanDecision = {
  kind: "ask",
  rule: "positive_value",
  reason:
    "The decision is split mainly between the electrician at DB-C2 (47%) and IT replacing SW-C2 (22%). Mahesh can check the switch lights in IDF-2: green points away from power, off points to breaker C2-7. That separates the two leading decisions for about 3 minutes of his time, more than any other available question.",
  action: { participant_id: "p_mahesh", probe_id: "switch_leds", location_id: "IDF2", requires_move: true },
  decision_class: null,
  decision_probability: null,
  candidates: [
    {
      action: { participant_id: "p_mahesh", probe_id: "switch_leds", location_id: "IDF2", requires_move: true },
      eig_decision_bits: 0.92,
      eig_hypothesis_bits: 1.21,
      cost_s: 190,
      net_value_min: 6.8,
      score: 0.29,
      outcomes: [
        { outcome: "off", probability: 0.55, decision: "DISPATCH_ELECTRICIAN_DB_C2", decision_probability: 0.82, top_hypothesis: "CB_C2_7.tripped", top_hypothesis_probability: 0.76 },
        { outcome: "green", probability: 0.33, decision: "IT_REPLACE_AP_2A", decision_probability: 0.41, top_hypothesis: "AP_2A.dead", top_hypothesis_probability: 0.33 },
        { outcome: "amber", probability: 0.12, decision: "IT_ONSITE_SW_C2", decision_probability: 0.88, top_hypothesis: "SW_C2.dead", top_hypothesis_probability: 0.88 },
      ],
    },
    {
      action: { participant_id: "p_imran", probe_id: "breaker_c2_7", location_id: "DB_C2_PANEL", requires_move: true },
      eig_decision_bits: 0.71,
      eig_hypothesis_bits: 0.98,
      cost_s: 240,
      net_value_min: 4.1,
      score: 0.18,
      outcomes: [
        { outcome: "tripped", probability: 0.43, decision: "DISPATCH_ELECTRICIAN_DB_C2", decision_probability: 0.97, top_hypothesis: "CB_C2_7.tripped", top_hypothesis_probability: 0.97 },
        { outcome: "up", probability: 0.57, decision: "IT_ONSITE_SW_C2", decision_probability: 0.39, top_hypothesis: "SW_C2.dead", top_hypothesis_probability: 0.39 },
      ],
    },
    {
      action: { participant_id: "p_riya", probe_id: "corridor_lights", location_id: "F3_CORRIDOR", requires_move: true },
      eig_decision_bits: 0.18,
      eig_hypothesis_bits: 0.34,
      cost_s: 45,
      net_value_min: 1.2,
      score: 0.07,
      outcomes: [
        { outcome: "on", probability: 0.9, decision: "DISPATCH_ELECTRICIAN_DB_C2", decision_probability: 0.49, top_hypothesis: "CB_C2_7.tripped", top_hypothesis_probability: 0.45 },
        { outcome: "off", probability: 0.1, decision: "DISPATCH_ELECTRICIAN_DB_C2", decision_probability: 0.62, top_hypothesis: "CB_C2_5.tripped", top_hypothesis_probability: 0.4 },
      ],
    },
  ],
  infeasible: [
    { participant_id: "p_asha", probe_id: "switch_leds", location_id: "IDF2", reasons: ["needs role guard, it_tech or electrician", "IDF-2 is restricted"] },
    { participant_id: "p_riya", probe_id: "breaker_c2_7", location_id: "DB_C2_PANEL", reasons: ["needs role electrician"] },
  ],
};

const pending: Question = {
  id: "q6",
  kind: "probe",
  language: "mr",
  status: "pending",
  asked_at: at(352),
  outcomes: ["green", "amber", "off"],
  action: plan.action!,
  text: "तुम्ही नेटवर्क कपाट IDF-2 पर्यंत जाऊ शकाल का? तिथे पोहोचल्यावर: स्विचवरचे दिवे हिरवे, नारिंगी की बंद आहेत?",
};

const approvals: Approval[] = [];

export const previewInvestigation: InvestigationState = {
  id: PREVIEW_ID,
  pack_id: "campus_block_c",
  status: "investigating",
  created_at: at(0),
  sealed_commitment: "9f2c4e1ab07d6c35e18f0b2a4d7c9e6158a3b0f4c2d1e7a9b6f8c3d5e0a1b2c4",
  report: { text: "Floor 3 pe WiFi nahi chal raha", reporter_id: "p_riya", affected_location_id: "F3_R304" },
  participants: previewParticipants,
  observations,
  belief,
  plan,
  pending_question: pending,
  approvals,
  questions_asked: 6,
  ground_truth: null,
  presence_checks_enabled: true,
  presence_checks: [
    { question_id: "q_preview_check", observation_id: "obs_preview_3", participant_id: "p_imran", location_id: "DB_C2_PANEL", token_id: "db_c2_door_label", status: "passed" },
  ],
  disagreements: [
    {
      observation_id: "obs_preview_5",
      earlier: { participant_id: "p_riya", probe_id: "wifi_status", location_id: "F3_R304", outcome: "no_network", p_mistaken: 0.31 },
      new: { participant_id: "p_riya", probe_id: "wifi_status", location_id: "F3_R304", outcome: "connected", p_mistaken: 0.12 },
      kind: "one_mistaken",
      p_both_right: 0,
      reconciling_hypothesis: null,
      reconciling_label: null,
      only_one_depends: [],
      explanation: "No likely cause makes both answers right. If one of them is mistaken, it is more likely the first reading (31%).",
    },
  ],
};

/** A short event log matching the story above, for the replay screen. */
export const previewEvents: EventEnvelope[] = (() => {
  const ev: EventEnvelope[] = [];
  let seq = 0;
  const push = (s: number, type: string, payload: Record<string, unknown>) =>
    ev.push({ investigation_id: PREVIEW_ID, seq: ++seq, ts: at(s), type, payload });
  const snap = (pairs: [string, number][], ow: number, used: number): BeliefSnapshot => {
    const hyps = belief.hypotheses.map((h) => {
      const hit = pairs.find(([id]) => id === h.id);
      return { ...h, probability: hit ? hit[1] : h.probability * 0.4 };
    });
    hyps.sort((a, b) => b.probability - a.probability);
    return { ...belief, hypotheses: hyps, open_world_probability: ow, observations_used: used };
  };
  const recorded = (o: Observation) => ({
    evidence: {
      participant_id: o.participant_id,
      probe_id: o.probe_id,
      location_id: o.location_id,
      outcome: o.outcome,
      hedge: o.hedge,
      directness: o.directness,
      modality: o.modality,
    },
  });
  push(0, "InvestigationCreated", { pack_id: "campus_block_c", sealed_commitment: previewInvestigation.sealed_commitment });
  push(1, "ReportReceived", previewInvestigation.report as unknown as Record<string, unknown>);
  push(2, "BeliefUpdated", snap([["AP_3A.dead", 0.21], ["CB_C2_7.tripped", 0.17], ["SW_C2.dead", 0.14], ["NO_FAULT", 0.12]], 0.02, 0) as unknown as Record<string, unknown>);
  push(3, "QuestionAsked", { id: "q1", participant_id: "p_riya", probe_id: "wifi_status", location_id: "F3_R304" });
  push(48, "ObservationRecorded", recorded(observations[0]));
  push(49, "BeliefUpdated", snap([["CB_C2_7.tripped", 0.24], ["AP_3A.dead", 0.23], ["SW_C2.dead", 0.19], ["NO_FAULT", 0.02]], 0.018, 1) as unknown as Record<string, unknown>);
  push(50, "QuestionAsked", { id: "q2", participant_id: "p_mahesh", probe_id: "internet_works", location_id: "GUARD_DESK" });
  push(131, "ObservationRecorded", recorded(observations[1]));
  push(132, "BeliefUpdated", snap([["CB_C2_7.tripped", 0.31], ["SW_C2.dead", 0.25], ["AP_3A.dead", 0.17]], 0.016, 2) as unknown as Record<string, unknown>);
  push(205, "ObservationRecorded", recorded(observations[2]));
  push(206, "BeliefUpdated", snap([["CB_C2_7.tripped", 0.36], ["SW_C2.dead", 0.24], ["AP_3A.dead", 0.12], ["CB_C2_5.tripped", 0.05]], 0.015, 3) as unknown as Record<string, unknown>);
  push(262, "ObservationRecorded", recorded(observations[3]));
  push(263, "BeliefUpdated", belief as unknown as Record<string, unknown>);
  push(330, "ObservationRecorded", recorded(observations[4]));
  push(331, "ObservationConfirmed", { observation_id: "o1", agreed: false });
  push(351, "PlanComputed", plan as unknown as Record<string, unknown>);
  push(352, "QuestionAsked", pending as unknown as Record<string, unknown>);
  return ev;
})();

/** Sample summary.json in the shape eval/runner.py writes, for previewing the evaluation screen. */
export const previewEvaluation = {
  git_sha: "preview",
  python: "n/a",
  seeds: [10000, 10039],
  scenario_mix: { single: 35, pair: 3, no_fault: 1, access_limited: 1 },
  policies: {
    E_ours: {
      n: 40, failed_runs: 0, success_rate: 0.7, decision_accuracy: 0.88, decided: 33, accuracy_on_identifiable: 0.74,
      false_confidence_rate: 0.03, abstention_recall: 0.5, abstention_precision: 0.4, probes_mean: 6.2, probes_median: 6,
      effort_s_mean: 220, people_mean: 2.8, hit_step_limit: 0,
    },
    A_checklist: {
      n: 40, failed_runs: 0, success_rate: 0.45, decision_accuracy: 0.7, decided: 38, accuracy_on_identifiable: 0.6,
      false_confidence_rate: 0.2, abstention_recall: 0, abstention_precision: null, probes_mean: 11.4, probes_median: 11,
      effort_s_mean: 410, people_mean: 3.6, hit_step_limit: 2,
    },
  },
};
