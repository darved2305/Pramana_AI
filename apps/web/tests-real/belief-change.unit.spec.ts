import { expect, test } from "@playwright/test";
import type { EventEnvelope, Observation } from "../src/lib/api/types";
import { latestBeliefChange, probeLabel } from "../src/lib/data/derive";

function event(seq: number, type: string, payload: Record<string, unknown>): EventEnvelope {
  return { seq, type, payload } as unknown as EventEnvelope;
}

test("belief changes resolve payload-only observation events from canonical state", () => {
  const before = { hypotheses: [{ id: "before", label: "Before", probability: 0.5 }] };
  const after = { hypotheses: [{ id: "after", label: "After", probability: 0.8 }] };
  const observations = [{
    id: "observation-1",
    participant_id: "participant-1",
    probe_id: "wifi_status",
    outcome: "works",
  }] as Observation[];
  const result = latestBeliefChange([
    event(1, "BeliefUpdated", before),
    event(2, "ObservationRecorded", {
      observation_id: "observation-1",
      evidence: { reason: "recorded answer", contradiction: false },
    }),
    event(3, "BeliefUpdated", after),
  ], observations);

  expect(result?.answers).toEqual([{ participant_id: "participant-1", probe_id: "wifi_status", outcome: "works" }]);
  expect(probeLabel(undefined, result?.answers[0]?.probe_id)).toBe("wifi status");
  expect(probeLabel(undefined, undefined)).toBe("Unknown check");
});

test("belief changes skip observation ids missing from canonical state", () => {
  const result = latestBeliefChange([
    event(1, "BeliefUpdated", { hypotheses: [] }),
    event(2, "ObservationRecorded", { observation_id: "missing" }),
    event(3, "BeliefUpdated", { hypotheses: [] }),
  ], []);

  expect(result).toBeNull();
});
