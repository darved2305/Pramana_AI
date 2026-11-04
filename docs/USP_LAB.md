# USP_LAB.md — Every unconventional capability we considered

This lab started from the 10 seed ideas in our brief and extended them to 17 candidates. Every candidate was put through the same screening question:

> **"Could a basic Python script, a fixed decision tree, or a conventional voice agent accomplish essentially the same thing?"**

If the answer was yes, we strengthened the mechanism or dropped the candidate.

Scores run from 1 to 5, with 5 best. For engineering cost, 5 means cheapest. Section 18 has the scoring matrix.

---

### U1. Value-of-Information Router

- **Problem.** Coordinators ask whoever answers the phone. They don't ask whoever is best placed to settle the question.
- **UX.** The console shows: "Asking **Mahesh** (guard, ground floor) to walk to **IDF-2** and look at the switch lights. +0.71 bits, ~85 s." Hovering shows the runner-up actions and the reasons they lost ("Riya: no closet access"; "Imran: 4 min away").
- **What the agent does.**
  - Scores every feasible *(person, observation, phrasing)* by decision-focused expected information gain (EIG) divided by cost.
  - Cost includes travel, call setup and fatigue.
  - Feasibility checks permissions, location, consent, language and budget.
- **Why it is surprising.** It routes people the way a scheduler routes compute. For example, it will skip the reporter and send someone else, and it can explain why.
- **Closest existing work.**
  - Quintess runs "cheapest checks first" for a single technician.
  - Astyr picks one test for one technician.
  - GeoCrowd-style spatial crowdsourcing assigns tasks to people, but without diagnosis.
  - UoT and BED-LLM choose questions for a single respondent.
- **Does it genuinely differ?** Yes. The respondent itself is a decision variable, with heterogeneous ways to observe and permission constraints.
- **Mechanism.** PRODUCT §19: exact predictive distributions, EIG_D + η·EIG_H, a cost model, and a feasibility filter.
- **Dependencies.** The domain pack (probes, preconditions, walking graph) and the participant registry.
- **Failure cases.**
  - Wrong cost estimates bias routing. Mitigation: fatigue terms and caps.
  - Locations in the registry go stale. Mitigation: ask "where are you?" (a cheap probe).
- **Demo.** The guard is chosen over the student, with the explanation popover open.
- **Metric.** Probes and minutes needed to reach the correct decision, compared against Baselines A and B.
- **Complexity.** Medium.
- **Value to users.** High.
- **Hackathon differentiation.** High.
- **Decision.** **BUILD (C1, P0).**

### U2. Decision-Sufficient Stopping and Constructive Abstention

- **Problem.** Investigations either stop too early (overconfident) or drag on chasing the exact cause when the action is already clear.
- **UX.** "Decision: send the electrician to DB-C2 (93%). The exact cause is breaker 7 *or* breaker 3, but both are on the same board, so the dispatch is the same." Or, when abstaining: "I can't tell switch failure from closet power with the people available. Cheapest resolver: anyone with the IDF-2 key, about 4 min."
- **What the agent does.**
  - Groups hypotheses into decision classes.
  - Continues only while some action has positive net EVOI.
  - Abstains when P(open-world) is high, or when no feasible action helps.
  - When abstaining, reports the best actions it *cannot* currently take.
- **Why it is surprising.** It stops before it knows everything, deliberately and with stated reasons.
- **Closest existing work.**
  - Heckerman's EVOI troubleshooting.
  - Javdani et al.'s decision-region determination (HEC).
  - MediQ's abstention.
  - Astyr: "refuses to guess".
- **Does it genuinely differ?** As a product behaviour with operational decision classes and a "what it would take" output, yes. The underlying theory is established.
- **Mechanism.** A loss matrix, EVOI, thresholds, and an `OPEN_WORLD` hypothesis.
- **Failure cases.**
  - A badly specified loss matrix produces poor stopping. Mitigation: defaults expressed in minutes, configurable.
- **Demo.** The decision is reached at 93% with the exact cause still open. The abstention scenario (S4) appears in the long video.
- **Metric.** False-confidence rate, abstention precision and recall, and probes saved compared with "identify exactly".
- **Complexity.** Low–medium.
- **Decision.** **BUILD (C1, P0).**

### U3. Physics-Consistent Testimony Weighting

- **Problem.** Human answers are noisy. Majority voting is useless when only one person can see a given thing.
- **UX.** Each ledger row shows a weight and a "consistency" chip. The participant panel shows a consistency estimate, never a "trust" or "lie" label.
- **What the agent does.**
  - Integrates each person's reliability (Beta prior, 21-point quadrature) under every fault hypothesis.
  - Hypotheses that make a person's answers physically consistent gain weight.
  - The person's reliability posterior falls if their answers fit only the hypotheses that other evidence contradicts.
- **Why it is surprising.** It works out who is probably mistaken within a single incident, from physics rather than history.
- **Closest existing work.**
  - Dawid–Skene (EM across many items).
  - Wang et al. 2012 (social-sensing MLE).
  - **Wang et al., RTSS 2013**, which uses physical constraints. This is the closest prior art.
- **Does it genuinely differ?** In setting and integration, yes: an active diagnostic loop, a causal dependency model, one incident, per-class reliability, and combination with hedges and hearsay. The mechanism itself is a known family.
- **Mechanism.** PRODUCT §19, the likelihood with reliability integrated out.
- **Failure cases.**
  - Two people make the same mistake together (correlated error, e.g., both misread the same unclear LED). Mitigation: prefer independent modalities and item-specific options.
- **Demo.** An adversarial participant's consistency drops while the decision stays correct.
- **Metric.** Accuracy under one adversary versus none, and reliability AUC for flagging the adversary.
- **Complexity.** Medium.
- **Decision.** **BUILD (C2, P0).**

### U4. Contradiction Resolver with Reconciliation Hypotheses

- **Problem.** "Floor 2 Wi-Fi works" and "floor 2 Wi-Fi is down" stall a human coordinator.
- **UX.** An amber banner: "Contradiction: Aarav vs Neha. Possible explanations: (1) one is mistaken, (2) **they are on different access points** (AP-2A vs AP-2B), (3) something changed between 02:01 and 02:06. Tie-break: ask Aarav to read the number after 'NAVA-WiFi' on his Wi-Fi details screen."
- **What the agent does.**
  - Detects that no hypothesis explains both answers when reliability is assumed perfect.
  - Groups the probability mass into explanation families: reliability error, context (which AP, band or device), and time.
  - The planner then naturally selects the probe that separates them.
- **Why it is surprising.** It treats contradictions as clues, and sometimes concludes that *both people were right*.
- **Closest existing work.** Truth discovery resolves conflicts by voting or reliability. We found nothing that generates context-reconciliation hypotheses in diagnosis.
- **Does it genuinely differ?** Yes in behaviour. Mechanically it falls out of U3 plus probabilistic context in predictions (e.g., `wifi_assoc` per room).
- **Failure cases.**
  - The context variables are not modelled, so only "someone is mistaken" remains as an explanation. That is acceptable.
- **Demo.** S2 in the long video.
- **Metric.** Accuracy on contradiction scenarios, and the number of probes needed to resolve them.
- **Complexity.** Low–medium (mostly explanation UI).
- **Decision.** **BUILD (C2): detection P0, explanation UI P1.**

### U5. Belief-Synchronized Parallel Calls with Live Preemption

- **Problem.** Each person takes 30–90 s to answer, so sequential questioning wastes minutes.
- **UX.** Two or three call cards stream at the same time. When one answer lands, another card's pending question flips: "~~Is the ground floor Wi-Fi working?~~ → *Can you see NAVA-WiFi on your phone?*"
- **What the agent does.**
  - Greedily selects a batch by conditional joint gain.
  - After each commit, re-scores the probes already in flight.
  - Preempts a probe if its value has dropped below 30% of its value when it was issued.
  - The call runtime swaps, stops or apologises at a safe moment in the conversation.
- **Why it is surprising.** The agent changes its question mid-call because a different person just answered.
- **Closest existing work.**
  - HappyRobot makes many calls, but without a shared belief.
  - Multi-party speech research works on a shared conversational floor (MultiPartyTurnBench, Speak-or-Stay-Silent).
  - JarvisBench coordinates agents on behalf of one human.
  - We found no system that synchronizes isolated calls through a belief state.
- **Does it genuinely differ?** Yes.
- **Mechanism.** Batch EIG (PRODUCT §19), `rescore_inflight`, and call-runtime safe points.
- **Dependencies.** Gnani concurrency (unknown) and the gateway's fallbacks.
- **Failure cases.**
  - The concurrency cap is hit. Fallback: sequential calls.
  - Preempting too often annoys people. Mitigation: at most one preemption per call.
- **Demo.** The 60-second video, if a clean take exists.
- **Metric.** Simulated time-to-decision, sequential versus parallel, at equal accuracy.
- **Complexity.** Medium–high.
- **Decision.** **BUILD (C3, P1a).**

### U6. Decision-Critical Confirmation

- **Problem.** Prisma returns no confidence scores. Confirming every answer is annoying; confirming none is unsafe.
- **UX.** The agent asks "Just to be sure: was the light green, orange, or no light?" *only* when that answer would flip the decision.
- **What the agent does.**
  - Generates alternative readings of an answer: from hedges, from the extractor's second-best outcome, and from a second Prisma REST decode of short decision-critical answers.
  - Re-runs the decision under each alternative.
  - Asks for confirmation if the argmax changes, or if the decision probability shifts by more than 0.15.
- **Why it is surprising.** It skips confirmation on most answers and confirms exactly the one that matters.
- **Closest existing work.** Spoken dialogue systems choose explicit or implicit confirmation based on ASR confidence. Here confirmation is gated by *decision sensitivity*. [I]
- **Does it genuinely differ?** The combination is uncommon. The second-decode trick also works around a real gap in Gnani's API.
- **Failure cases.**
  - The second decode doubles REST cost. Mitigation: only for short, decision-critical answers.
- **Demo.** The long video: a hedged "shayad green" triggers a confirmation.
- **Metric.** Fraction of answers confirmed, against the fraction of injected decision-critical ASR errors caught (audio-level evaluation, internal).
- **Complexity.** Medium.
- **Decision.** **BUILD (C3, P1a).**

### U7. Question-Conditioned Speech Recognition

- **Problem.** Short code-mixed answers ("ho", "nahi re", "band aahe", "302") are hard to recognise without context.
- **UX.** Invisible to participants. The developer metrics page shows which hints were attached to each turn.
- **What the agent does.** Opens a fresh Prisma v3.0 session per question with:
  - `previous_text` set to the question as spoken;
  - `keyterms` set to the answer vocabulary in every relevant script, plus site names;
  - `language_code` set to the participant's candidate languages;
  - `format=codemix` for Hinglish speakers.
- **Why it is surprising.** It uses Gnani's context hints as a prior conditioned on the dialogue state. This fits the "Jugaad Genius" category.
- **Closest existing work.** Contextual biasing is a known ASR technique, and voice assistants condition on dialogue state.
- **Does it genuinely differ?** Not in research terms. It is a creative, *measurable* use of the platform.
- **Failure cases.**
  - Over-biasing produces false keyterm hits ("haan" heard where there was noise). Mitigation: keep the lists small, and let the extractor return `unknown`.
- **Demo.** Not shown on screen. Mentioned in the technical thread, without metrics because of the EULA.
- **Metric.** Internal ablation of slot accuracy with and without hints.
- **Complexity.** Low.
- **Decision.** **BUILD (C3, P1a).** Keep the evaluation numbers internal unless Gnani approves publishing them.

### U8. Proof-of-Presence Challenge

- **Problem.** "I'm in the server room, everything's green." Is that true?
- **UX.** "Great. Before I rely on that, could you read me the last three characters on the white label of the switch?" Correct: presence verified ✓. Wrong or can't: "No problem, I'll ask someone else," and the observation's weight drops to 0.2.
- **What the agent does.**
  - Holds presence tokens per restricted location in the registry.
  - The planner issues a challenge only when observations from that location are decision-critical.
- **Why it is surprising.** It catches false claims of physical access through ordinary conversation.
- **Closest existing work.** Knowledge-based authentication, and GPS or Wi-Fi fingerprint "proof of location" in crowdsourcing.
- **Does it genuinely differ?** Applied in a physical diagnosis dialogue, chosen by VOI, and modelled in the likelihood: yes.
- **Failure cases.**
  - A label is unreadable, giving a false failure. Mitigation: offer an alternative token.
  - A token leaks (photographed earlier). Accepted residual risk.
- **Demo.** A two-second moment in the 60-second video; a full scene (S7) in the long video.
- **Metric.** Adversary detection rate and decision accuracy in S7.
- **Complexity.** Low.
- **Decision.** **BUILD (C2, P1a).**

### U9. Risky-Prediction Verification

- **Problem.** "It's working now" is not proof of what was fixed. Wrong fixes resurface hours later.
- **UX.** "If the breaker was the cause, the CCTV monitor in IDF-2 should now show a boot screen. Checking with Mahesh." Then: ✓ Verified. Sealed fault revealed: matches.
- **What the agent does.**
  - Computes post-action predictions for every hypothesis.
  - Picks probes that maximise I(Fixed; O).
  - Prefers consequences that were held out of the diagnosis and that would be improbable if the fix were wrong.
- **Why it is surprising.** Popperian closure: the agent makes a falsifiable prediction about something it has not yet looked at.
- **Closest existing work.**
  - Astyr: a field verdict gates the fix.
  - Quintess: confirmed fixes are recorded.
  - Standard practice: "is it fixed?"
- **Does it genuinely differ?** Yes. The verification test is selected for discrimination and is held out of the diagnosis.
- **Failure cases.**
  - No discriminating probe is feasible. Fallback: a symptom-resolution check, labelled "weak verification".
- **Demo.** The climax of the 60-second video.
- **Metric.** Catch rate on injected wrong repairs; extra probes added by verification.
- **Complexity.** Low–medium.
- **Decision.** **BUILD (C4, P0).**

### U10. Interventional Disambiguation

- **Problem.** "AP dead" versus "switch port dead" look identical to anyone just observing.
- **UX.** "These two causes look the same from outside. Proposed safe experiment: IT technician moves AP-3B's cable to spare port 12 (reversible, about 2 min). If the AP's light comes on, the port is faulty. Approve?"
- **What the agent does.**
  - Detects observational equivalence over all feasible probes.
  - Ranks the pack's safe, reversible interventions by EIG per unit cost.
  - Requests approval, then models the intervention's effect.
- **Why it is surprising.** It runs an experiment rather than another survey question. This is the causal "do" operation.
- **Closest existing work.**
  - Heckerman's work treats repairs as actions.
  - Causal discovery uses interventions.
  - Astyr's "safe test".
- **Does it genuinely differ?** Partly.
- **Failure cases.**
  - The approver denies, so the agent abstains with a recommendation.
  - Unexpected side effects. Mitigation: only reversible, low-risk interventions are listed in the pack.
- **Demo.** Possibly the long video.
- **Metric.** Accuracy on scenarios that are observationally equivalent.
- **Complexity.** Medium.
- **Decision.** **SIMPLIFY (C4, P1b)**: one intervention type (port swap).

### U11. Map-Drift Discovery

- **Problem.** Documentation is wrong. A vendor survey found 61% of engineers say up to half of their network documentation is out of date ([NetBrain 2017](https://businesswire.com/news/home/20170613005215/en/NetBrain-Technologies-Survey-Reveals-Efficiency-Collaboration-Challenges)) [C].
- **UX.** "Evidence fits a *single* fault if AP-3B is actually wired to SW-C, not SW-C2 as documented (78%). Proposed documentation fix, with evidence."
- **What the agent does.** Adds topology-variant hypotheses (single-edge rewires, each with a small prior) and infers them jointly with the fault. Occam's razor applied with numbers: one fault plus a documentation error can beat two independent faults.
- **Why it is surprising.** The AI corrects the building's own documentation using what people told it.
- **Closest existing work.** Network topology inference and tomography from measurements.
- **Does it genuinely differ?** Yes, in that it is driven by testimony during an incident.
- **Failure cases.**
  - The hypothesis space multiplies. Mitigation: only allow edges flagged as uncertain.
- **Demo.** A strong long-video scene, if built.
- **Metric.** Drift-detection accuracy in S6.
- **Complexity.** Medium–high.
- **Decision.** **STRETCH (P2).** The most surprising candidate, but half-building it would weaken the demo.

### U12. Investigation Forecast and Dispatch Advisor

- **Problem.** "Should I send a technician now, or keep investigating?"
- **UX.** "Forecast: 2.4 more calls, about 3 min, 91% chance of resolving without a site visit. Dispatching now would waste the trip 38% of the time."
- **What the agent does.** Monte Carlo rollouts of its own policy over the current belief.
- **Why it is surprising.** It forecasts its own investigation.
- **Closest existing work.** None found as a product feature.
- **Failure cases.**
  - A biased simulation model makes the forecasts biased. They must be labelled as estimates.
- **Metric.** Forecast calibration against benchmark outcomes.
- **Complexity.** Medium.
- **Decision.** **STRETCH (P2).**

### U13. Open-World Hypothesis Induction ("the LLM proposes, Bayes disposes")

- **Problem.** The real fault may not be in the model at all.
- **What the agent does.**
  - When P(OPEN_WORLD) rises, an LLM proposes new failure modes together with explicit predicted symptoms.
  - A compiler validates the proposal against the pack schema and adds it to the hypothesis space.
  - The new mode is then tested like any other.
- **Why it is surprising.** It discovers causes nobody modelled.
- **Closest existing work.** LLM-guided scientific hypothesis generation (AI co-scientist-style systems); AgentRCA's hypothesis evaluation.
- **Failure cases.** Hallucinated physics; schema gaming; a much larger validation burden.
- **Complexity.** High.
- **Reliability.** Low.
- **Decision.** **DEFER** (future research). For v1 we keep the honest behaviour: abstain with "doesn't fit known causes".

### U14. Non-Leading Elicitation Protocol

- **Problem.** Leading questions contaminate testimony (Loftus & Palmer). Yes/no questions invite acquiescence (Krosnick; Saris et al.).
- **What the agent does.**
  - Uses observation-first and item-specific variants.
  - Runs a linter that bans mentions of causes and suggested answers in open forms.
  - Models acquiescence skew for closed yes/no forms.
- **Why it is surprising.** Interview science (the cognitive-interview meta-analyses) applied to an AI voice agent.
- **Does it genuinely differ?** It is a quality practice, not a standalone feature.
- **Decision.** **FOLD INTO C2/C3 (P0 linter, P1 acquiescence model).**

### U15. Silent-Witness Harvesting

- **Problem.** People volunteer useful facts that nobody asked for ("btw the lift is also stuck").
- **What the agent does.** The extractor emits `extra_observations` restricted to probes that exist in the pack. They enter the belief as hearsay or direct evidence depending on how they were phrased.
- **Why it is surprising.** Can trigger cross-domain hypotheses (power).
- **Decision.** **FOLD INTO the extractor (P0).**

### U16. Speculative Next-Question Pre-Synthesis

- **Problem.** Turn latency.
- **What the agent does.**
  - While the participant answers, the agent plans the next action for each of the 1–2 most likely outcomes.
  - It pre-synthesizes the TTS for those next questions and discards the unused ones.
- **Why it is surprising.** Speculative execution applied to conversation.
- **Cost.** Extra TTS credits, to be measured.
- **Decision.** **BUILD if credits allow (P1b).**

### U17. Consent-First Human Sensor Network

- **Problem.** People are not sensors. Their time and consent matter.
- **What the agent does.**
  - Asks for consent on every call.
  - Enforces per-person question budgets, cool-downs and walking consent.
  - Spreads load across people (a fatigue term).
  - Tells each person afterwards how their answer helped.
- **Decision.** **BUILD minimal (P0).** Necessary for the product, but not a differentiator.

---

## 18. Scoring matrix

| ID | Candidate | Orig | Useful | Depth | Demo | Reliab | Cost (5 = cheap) | Differ | Feasible | Total | Decision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| U1 | VOI Router | 4 | 5 | 5 | 4 | 4 | 3 | 4 | 4 | 33 | Build P0 |
| U2 | Decision stop / abstain | 4 | 5 | 4 | 4 | 4 | 4 | 4 | 5 | 34 | Build P0 |
| U3 | Testimony weighting | 4 | 4 | 5 | 4 | 4 | 4 | 4 | 4 | 33 | Build P0 |
| U4 | Contradiction / reconciliation | 4 | 4 | 4 | 5 | 4 | 4 | 4 | 4 | 33 | Build P0/P1 |
| U5 | Parallel + preemption | 5 | 4 | 4 | 5 | 3 | 2 | 5 | 3 | 31 | Build P1a |
| U6 | Decision-critical confirmation | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 4 | 30 | Build P1a |
| U7 | Question-conditioned ASR | 3 | 4 | 3 | 2 | 4 | 4 | 3 | 5 | 28 | Build P1a |
| U8 | Proof-of-presence | 4 | 3 | 2 | 5 | 4 | 5 | 4 | 5 | 32 | Build P1a |
| U9 | Risky-prediction verification | 4 | 5 | 4 | 5 | 4 | 4 | 4 | 4 | 34 | Build P0 |
| U10 | Interventional disambiguation | 3 | 4 | 4 | 4 | 3 | 3 | 3 | 3 | 27 | Simplify P1b |
| U11 | Map-drift discovery | 5 | 4 | 4 | 5 | 3 | 2 | 5 | 2 | 30 | Stretch P2 |
| U12 | Forecast / dispatch advisor | 4 | 4 | 3 | 3 | 4 | 3 | 4 | 3 | 28 | Stretch P2 |
| U13 | Open-world induction | 4 | 4 | 4 | 4 | 2 | 1 | 4 | 1 | 24 | Defer |
| U14 | Non-leading protocol | 3 | 4 | 2 | 2 | 5 | 5 | 3 | 5 | 29 | Fold in |
| U15 | Silent-witness harvesting | 2 | 4 | 2 | 3 | 4 | 4 | 2 | 5 | 26 | Fold in |
| U16 | Speculative pre-synthesis | 3 | 3 | 3 | 2 | 4 | 3 | 3 | 4 | 25 | P1b |
| U17 | Consent-first sensor network | 2 | 4 | 1 | 2 | 5 | 4 | 2 | 5 | 25 | Minimal P0 |

**How the candidates were combined into four capabilities:**
- **C1** = U1 + U2
- **C2** = U3 + U4 + U8, with U14 and U15 folded in
- **C3** = U5 + U6 + U7, with U16 if credits allow
- **C4** = U9 + U10 (simplified)

**Rejected or deferred, and why:**
- **U13**: too unreliable for 6 days. A failure in the demo would undermine trust.
- **U11 and U12**: valuable, but each needs its own scenarios and UI. Build them only after code freeze if the core is stable.
- **"Generic multilingual support", "memory", "summarization" and "dashboard"**: not differentiators, so they were never candidates.
