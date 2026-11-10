# PRODUCT.md - Pramana: an AI that investigates what it cannot see

> **Working name.** *Pramāṇa* (प्रमाण, Sanskrit/Hindi/Marathi): "proof", "a valid means of knowledge". Nyāya epistemology lists perception (*pratyakṣa*), inference (*anumāna*), comparison (*upamāna*) and testimony from a reliable person (*śabda*). That maps directly onto this product: people perceive, they testify by voice, the machine infers, and each testimony is weighted by how reliable that person has proven to be. You can rename it. Check availability of the name before publishing.

| | |
|---|---|
| Version | 1.0, 2026-11-04 (planning day) |
| Team | Darshan, Nikhil (two-person team) |
| Status | Authoritative product spec. PLAN.md is the authoritative engineering plan. |
| Supporting docs | `docs/RESEARCH.md`, `docs/COMPETITORS.md`, `docs/USP_LAB.md`, `docs/EVALUATION.md`, `docs/DEMO.md` |

**Evidence labels used throughout**
- **[V]** verified against a primary source on 2026-11-04.
- **[C]** a company's own claim, not independently verified.
- **[I]** our inference.
- **[H]** a hypothesis we will test.
- **[T]** a target, not a result.
- No performance number in this document is a measured result unless it is labelled [V] and cites its source.

---

## 0. One-screen summary

**What we build.** A closed-loop investigation system for physical-world problems that sensors and dashboards do not cover. Someone reports a symptom by voice, for example "Wi-Fi is dead on floor 3". Pramana then:

1. Builds a probability distribution over possible causes from a model of the site: what depends on what, including power, network and access.
2. Computes which person, at which location, should make which safe observation next. It chooses by **value of information per unit of human effort and time**.
3. Phones several consenting people in parallel through browser voice calls, in their own language (Marathi, Hindi, English or Hinglish), using Gnani **Prisma** (speech-to-text) and **Timbre** (text-to-speech).
4. Turns each spoken answer into typed evidence. Each piece of evidence records its provenance, a hedge level and an inferred reliability.
5. Updates the belief exactly with Bayes' rule. It infers each person's reliability *jointly* with the fault, from physical consistency.
6. Re-plans live, which can cancel or rewrite questions already in flight. It stops when the *action* is determined (who to dispatch, what to fix), or **abstains** and states what evidence would settle the question.
7. Asks an authorized human to approve any consequential action.
8. **Verifies the outcome with a held-out "risky prediction"**: a consequence the diagnosis implies that was not used to make the diagnosis.

**Design rule: LLMs translate, math decides, humans verify.** LLMs work only at the language boundary: parsing the report, phrasing questions, extracting answers, explaining decisions. All selection, belief and stopping decisions come from deterministic, inspectable code.

**The four capabilities we will ship** (chosen from 17 candidates; see §11–13 and `docs/USP_LAB.md`):

| # | Capability | One line |
|---|---|---|
| C1 | **Ask-the-World Planner** | Chooses *who* to ask, *what* to observe, *how* to phrase it and *when to stop*. It uses decision-focused information gain per unit cost and abstains constructively. |
| C2 | **Testimony Engine** | Treats every answer as evidence, never as truth. It infers fault and per-person reliability jointly from physical consistency, resolves contradictions with "reconciliation" hypotheses, and checks claimed physical presence with challenge questions. |
| C3 | **Conversation Swarm** | Runs several parallel voice calls driven by one shared belief state, with live preemption. It confirms an answer only when the decision hinges on it, and conditions speech recognition on the question just asked. |
| C4 | **Causal Closure** | Gates actions on authorization, uses safe diagnostic interventions when passive observation cannot distinguish the hypotheses, and verifies the fix with a risky prediction. |

**What is real and what is simulated.**
- *Real:* the AI, the voice calls, the people, their languages, the reasoning and the timing.
- *Simulated, and labelled as such:* the building, its faults and what each participant "sees". This comes from a simulator whose hidden ground truth the agent cannot access.
- The demo opens with a sealed fault, committed by hash, and reveals it at the end.

**Hackathon fit [V]:**
- Open brief.
- The project must make genuine use of Gnani models or APIs.
- Awards we target:
  - **Jugaad Genius**: most creative or unexpected use of Gnani models. Here, speech APIs become instruments of a Bayesian sensor network.
  - **Two-Person Army**: best team of two.
  - **Demo Day Drop**: best 60-second demo.
- Secondary fit: **Mixed Vibes** (code-mixed voice). A team can win at most one award.
- The internship shortlist is decided by **verified engagement** on the nominated LinkedIn/X posts, followed by individual interviews.

---

## 1. Executive product thesis

AI agents are strong where the world is already digitized: APIs, logs, dashboards. A great deal of operational reality is not digitized. That includes uninstrumented hostels, hospital wings, warehouses, retail branches, village water schemes and the long tail of buildings whose only "sensors" are the people inside them.

When something breaks there, a human coordinator does an investigation by phone. They call people, ask questions, compare answers, eliminate possibilities and finally dispatch someone. That process is slow, depends on the coordinator's skill, and is especially weak at night, across languages, and when reports conflict.

**Thesis [H]:** an AI can run this investigation better than a fixed checklist, and better than an LLM improvising questions, if it does five things:
- (a) reasons over an explicit causal model of the site;
- (b) treats humans as noisy, costly, mobile, consent-based sensors;
- (c) picks observations by their value for the *decision*;
- (d) handles unreliable and conflicting testimony in a principled way;
- (e) closes the loop by verifying predictions.

Voice is the right interface because the people who can observe are guards, electricians, housekeeping staff and students. They are walking, their hands are busy, and many are not comfortable typing in English.

The strongest version of the product is **not** "a voice bot that troubleshoots". It is **an active-sensing system whose sensors are people**. It decides which questions the world should be asked, and it can prove it is not following a script: change any answer and its plan changes in a way you can predict.

---

## 2. Problem definition

**Scope of v1.** Diagnose service outages in a multi-floor building where:
- the documented dependency structure is known (power circuits → equipment → network segments → services);
- the current fault state is hidden;
- there is little or no telemetry, or the person coordinating has no access to it;
- 2–6 people are physically present at different locations, with different permissions, skills and languages;
- every observation costs human time, and observers can be wrong, hedge, relay hearsay, become unavailable, or (rarely) mislead.

**Formal problem.**
- Given the documented site model *M*, a prior over faults, a set of participants with affordances, and a stream of spoken answers:
  - choose a sequence (or parallel batches) of *(participant, observation, question form)* actions that minimizes expected (time + human effort + cost of a wrong decision);
  - output either an action decision with calibrated confidence, or a justified abstention;
  - then verify the outcome after the authorized action is taken.

This is sequential Bayesian experimental design (decision-theoretic troubleshooting) with heterogeneous, unreliable, human-mediated sensors and a speech channel in the loop.

**Out of scope for v1:**
- autonomous physical action;
- real phone (PSTN) calls;
- real facility deployment;
- telemetry integrations (beyond an optional simulated "machine probe").

---

## 3. Evidence that the problem exists

We have **not yet interviewed customers**. The evidence below is indirect, and we label how strong it is.

| Evidence | Source | Type | Strength | Supports | Does not support |
|---|---|---|---|---|---|
| Fully remote IT leads designate in-office staff as "remote hands" and use services like Field Nation or MSPs for physical work, "usually not same-day" | [r/sysadmin snapshot, May 2026](https://reddit.sentinel-team.org/posts/1tctoxt/snapshots/2026-05-15T20%3A01%3A25.013733Z) | Practitioner anecdote | Weak | Physical observation by non-IT people is already how remote incidents get handled | Frequency, cost, willingness to pay |
| Sysadmins describe the job as drawing out the real symptom from non-technical users instead of "the internet is down" | [DC GLUG thread](https://www.dcglug.org.uk/archive/2014/01/msg00528.html) | Anecdote | Weak | Elicitation quality matters | Scale |
| 14% of truck rolls are unnecessary; a failed first visit adds ~2 visits and ~14 days (157 organizations, 21M service events) | [Aquant 2025 benchmark summary](https://www.aquant.ai/resources/post/2025-service-benchmark-report-insights) | Vendor report [C] | Medium | Cost of dispatching without good diagnosis | Our segment (campuses) specifically |
| Truck-roll cost estimates range from about $150 to $500 | [CareAR](https://carear.com/blog/what-is-a-truck-roll-how-to-reduce-them), [Smarty](https://www.smarty.com/articles/truck-roll-costs) | Vendor blogs [C] | Weak (wide range) | That dispatches are expensive | Indian on-campus costs, which are lower in ₹ but still cost staff time |
| 61% of engineers say up to half of their network documentation is out of date | [NetBrain survey, 2017](https://businesswire.com/news/home/20170613005215/en/NetBrain-Technologies-Survey-Reveals-Efficiency-Collaboration-Challenges) | Vendor survey [C], dated | Medium-weak | Site models are imperfect, so "map drift" matters | Current figures |
| Indian hostels have repeated Wi-Fi disruption complaints and protests (JNU; Dayananda Sagar University; DAV Chandigarh, Apr 2026) | [Logical Indian](https://thelogicalindian.com/dayananda-sagar-hostel-protest-125052/), [uLektz/JNU](https://news.ulektz.com/?p=70935) | News | Medium for salience | The pain is felt by students and is relatable to judges | Root causes, frequency, budget |
| Electric utilities have used **customer phone calls as distributed sensors** for decades. OMS "trouble call analysis" rolls calls up the network topology to infer which protective device operated, and confidence grows as calls arrive | [US5568399](https://patents.google.com/patent/US5568399), [ETAP outage prediction](https://etap.com/de/product/outage-analysis) | Patents, vendor product | **Strong** for the underlying mechanism | Human reports + topology inference has real commercial value | That *active* questioning beats passive aggregation, which is our [H] |

**What this means.** The mechanism (humans as sensors, with topology-based inference) is commercially proven in utilities, in a *passive* form. The pain (slow, expensive, error-prone physical diagnosis) is widely reported, but our evidence for it is anecdotal or vendor-sourced.

**Before any commercial claim** we must interview 5+ facility or IT managers. That is planned, best-effort, in PLAN.md §33.

---

## 4. Target users and buyers

| Role | Who (v1 wedge: Indian multi-building campuses such as universities with hostels, hospitals, IT parks, hotels) | Relationship |
|---|---|---|
| **Buyer** | Head of Facilities / IT Head / Estate Officer | Pays to cut time-to-diagnose and wrong dispatches; wants a record of what happened |
| **Primary user** | Duty manager / night supervisor / helpdesk coordinator | Runs investigations in the console and approves actions |
| **Observers (lay)** | Students, residents, housekeeping staff, receptionists | Answer 1–3 short questions; consent per call |
| **Observers (with access)** | Security guards with keys, lab assistants | Can reach closets and read panels; observe only |
| **Authorized actors** | Electricians, IT technicians, vendor engineers | Perform diagnostic interventions and repairs after approval |
| **Reporters** | Anyone affected | Start investigations by voice |

**Later segments [H]:**
- multi-site retail and quick-service chains, where store staff are sensors for head-office IT;
- ISPs and telcos, where customers are probes for last-mile faults;
- DISCOMs, where 1912 complaints get *active* trouble-call analysis;
- rural water schemes, where operators and residents observe in Marathi.

---

## 5. Jobs to be done

1. *When something stops working across my buildings and I can't see why,* help me find what and where, using whoever is already there, without sending the wrong technician.
2. *When people tell me contradictory things,* tell me who is probably right, why, and what single check would settle it.
3. *When I must act at 2 a.m.,* give me a decision with honest confidence, or tell me plainly that we don't know yet and the cheapest way to find out.
4. *When the fix is done,* prove it is actually fixed, not just that someone said "it's working".
5. *For the people I ask (observer's job),* make it quick, in my language, never make me do something unsafe, and tell me when my answer helped.

---

## 6. Current alternatives

| Alternative | How it works today | Typical users |
|---|---|---|
| Phone calls + WhatsApp groups | Coordinator broadcasts "is it working on your floor?" and reads replies | Every Indian campus/facility [I] |
| Static SOPs and checklists | Fixed sequence: reboot the router, check the cable, call the vendor | Helpdesks, MSPs |
| Ticketing / helpdesk | User files a ticket, technician visits | Corporate IT, colleges |
| Dispatch first ("truck roll") | Send a person to look | Field service, facilities |
| Instrumentation | Synthetic-user sensors (e.g., [HPE Aruba UXI](https://www.hpe.com/int/en/products/networking/user-experience-insight.html)), NMS/SNMP, BMS | Well-funded enterprises |
| Remote visual support | Video call where an expert looks through a user's camera (TechSee, CareAR, Blitzz) | Telcos, appliance makers |
| AI SRE agents | LLM agents over logs, metrics and traces (PagerDuty SRE Agent, Resolve AI, Traversal, Cleric) | Cloud/software teams |
| Voice-first technician copilots | One technician talks to an AI that ranks causes and suggests checks (Quintess, Aquant "Roger", NOSO Labs) | Fleet/field maintenance |
| Utility OMS trouble-call analysis | Passive aggregation of customer calls by topology | Electric utilities |

---

## 7. Why existing alternatives are insufficient

- **WhatsApp/phone coordination.** No model of dependencies, so people get asked redundant questions. Conflicting answers get resolved by gut feel. Nothing is recorded or calibrated. Quality depends on the coordinator, and the coordinator is the bottleneck. [I]
- **Checklists.** They don't adapt to the answers, the participants or the cost. They ask the same questions whatever the evidence says, and cannot exploit cross-domain clues like "the CCTV in that closet is also dark".
- **Sensors.** They cost hardware and subscriptions per location and only cover what they measure (UXI tests the network the way a user would, not why the closet lost power). Much of the long tail will stay uninstrumented. Pramana *uses* telemetry where it exists: a sensor is just a very reliable participant (PLAN.md §9).
- **Remote video and technician copilots.** These guide *one* person who is already the right person in the right place. They do not choose *whom* to involve, coordinate several observers in parallel, or model testimony reliability.
- **AI SRE agents.** These require telemetry. Benchmarks also show digital root-cause analysis (RCA) is hard even with full telemetry:
  - [OpenRCA](https://microsoft.github.io/OpenRCA): best reported 11.34% fully correct [V].
  - ITBench (2025): 11.4% of SRE scenarios resolved.
  - [ITBench-AA](https://artificialanalysis.ai/articles/itbench-aa-launch) (May 2026): best 47% [V].
- **OMS trouble-call analysis.** It is passive: it waits for calls and does not choose whom to call or what to ask.

---

## 8. Competitive landscape (summary)

Full analysis, including 12-question breakdowns per competitor: `docs/COMPETITORS.md`.

| Product | Needs telemetry? | Chooses next observation? | Multiple humans in parallel? | Explicit probabilistic reliability? | Voice, Indian languages? | Verifies outcome how? |
|---|---|---|---|---|---|---|
| [Astyr](https://astyr.app/product) | Yes (live feeds, alarms) + documents | Proposes "a hypothesis and a safe test" [C] | No: "picks ONE tech" [C] | Confidence gate; no method stated [C] | No voice stated; iOS app | Human field verdict gates the fix [C] |
| [Quintess](https://www.quintess.ai/) | No live telemetry stated; manuals + CMMS + technician readings | Yes, "suggests the next check", "cheapest checks first" [C] | No; shift handover and expert escalation | "Ranked" causes; method not stated [C] | Voice-first; languages not stated | Leaves repair verification to the customer's process [C] |
| [PagerDuty SRE Agent](https://www.pagerduty.com/blog/product/the-path-to-autonomous-operations-pagerduty-spring-26-release/) | Yes | Runs diagnostics on systems | Agent-to-agent (MCP), not humans | n/a | No | System signals |
| Resolve AI / Traversal / Cleric | Yes | Over telemetry | No | n/a | No | Telemetry |
| Utility OMS (trouble-call analysis) | Partial (SCADA/AMI) + calls | No (passive) | Passive aggregation of many callers | Heuristics plus call volume [V] | IVR | Restoration calls |
| [RentAHuman](https://www.indiatvnews.com/technology/news/rentahuman-ai-lets-ai-agents-hire-humans-for-real-world-tasks-2026-02-05-1028987) / [Humwork](https://ycombinator.com/companies/humwork) | n/a | The agent hires a human for a task or advice | Marketplace | Not stated | No | Not stated |
| **Pramana** | **No** (uses it if present) | **Yes: decision-focused VOI per unit cost, across people** | **Yes: parallel calls with belief-driven preemption** | **Yes: joint Bayesian fault × reliability** | **Yes (Gnani Prisma/Timbre; Marathi, Hindi, English, Hinglish)** | **Held-out risky prediction** |

---

## 9. Specific differentiation

Every ingredient below has prior art (see §10 and §36). What we claim is the **combination in this setting**. Our searches on 2026-11-04 found no product or paper combining all five (search log in `docs/RESEARCH.md`; absence of evidence is not proof):

1. **Respondents are multiple heterogeneous humans in different physical places.** Action selection is over *(person, observation, question form)*. It respects permissions, location, travel time, language and fatigue. Most question-asking AI work selects questions for *one* respondent (UoT, BED-LLM, MedClarify, MediQ, AMIE).
2. **Reliability is inferred within a single incident, jointly with the fault, from physical consistency.** We integrate out each person's reliability (Beta prior, numerical quadrature) under every fault hypothesis. No historical labels are needed. Prior art does this from redundancy across many claims ([Wang et al. 2012](https://www3.nd.edu/~sslab/pdf/tosn14.pdf)) and from physical constraints ([Wang et al., RTSS 2013](https://www3.nd.edu/~sslab/pdf/rtss13.pdf)), but not inside an active diagnostic loop with a causal dependency model.
3. **Selection is decision-focused.** We stop when the *dispatch decision* is determined, not when the exact cause is known. This follows decision-region determination ([Javdani et al., AISTATS 2014](https://proceedings.mlr.press/v33/javdani14.html)) and EVOI-based troubleshooting ([Heckerman et al.](https://www.microsoft.com/en-us/research/publication/decision-theoretic-troubleshooting/)).
4. **Speech-channel uncertainty is propagated into evidence weights and confirmations.** Prisma returns no confidence scores [V], so uncertainty comes from three places: hedge words, a second decode on a different configuration, and extraction ambiguity. We confirm an answer only when the decision would flip under the alternative reading.
5. **Closure by risky prediction.** After an authorized repair, we test a consequence that was not used during diagnosis and that differs between the leading and runner-up hypotheses.

**Could a Python script, a decision tree or a normal voice agent do this?**
- A script can follow a tree, but cannot re-plan when a new person becomes available, weigh contradictory testimony, or explain why it is asking a guard about CCTV.
- A voice agent can talk, but has no belief state; it will sound fluent while being uncalibrated.
- The test of this claim is our benchmark against a checklist and against a frontier LLM choosing from the *same* action menu (§29).

---

## 10. Scientific foundations (summary)

Detailed notes, including what each paper demonstrated, what remains unsolved and how feasible it is to implement: `docs/RESEARCH.md`.

| Need | Classic foundation | Recent LLM-era work | How we use it |
|---|---|---|---|
| Choose the next measurement | de Kleer & Williams, *Diagnosing Multiple Faults* (AI 1987): minimum-entropy measurement selection; Reiter 1987 | [UoT (NeurIPS 2024)](https://arxiv.org/abs/2402.03271), [BED-LLM (ICLR 2026)](https://arxiv.org/abs/2508.21184), [MedClarify (2026)](https://arxiv.org/abs/2602.17308) | Exact EIG over an enumerable hypothesis space, computed in code rather than by the LLM |
| Cost-aware troubleshooting | [Heckerman, Breese & Rommelse](https://www.microsoft.com/en-us/research/publication/decision-theoretic-troubleshooting/): observe only if expected repair cost falls | - | EVOI-based continue/stop rule |
| Noisy tests, near-optimality | [Golovin, Krause & Ray, EC² (NeurIPS 2010)](https://arxiv.org/abs/1010.3091): greedy information gain can fail under noise | - | Decision-focused gain; noise modelled explicitly |
| Decide, don't identify | [Javdani et al., HEC/DRD (AISTATS 2014)](https://proceedings.mlr.press/v33/javdani14.html) | - | Hypotheses grouped into *decision classes*; stop on class certainty |
| Parallel observations | Krause & Guestrin 2005 (UAI); Golovin & Krause 2011 (JAIR, adaptive submodularity) | - | Greedy batch selection with conditional gains |
| Localize faults from end-user observations | [Sherlock (SIGCOMM 2007, MSR)](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/sherlock_sigcomm_07.pdf): multi-level inference graph; SCORE, Shrink, Boolean network tomography | - | People act as "end hosts" in a multi-level dependency graph that spans power and network |
| Unreliable human sources | Dawid & Skene 1979 (EM over annotator errors); [social-sensing MLE (Wang et al.)](https://www3.nd.edu/~sslab/pdf/tosn14.pdf); [physical constraints (RTSS 2013)](https://www3.nd.edu/~sslab/pdf/rtss13.pdf) | - | Joint fault × reliability posterior |
| Asking well | Cognitive interview meta-analyses ([Köhnken 1999](https://informahealthcare.com/doi/abs/10.1080/10683169908414991); [Memon et al. 2010](https://works.bepress.com/christian_meissner/57/)): more correct detail, small error increase; Loftus & Palmer 1974 (wording distorts reports); [Saris et al. 2010](https://ojs.ub.uni-konstanz.de/srm/article/view/2682): item-specific beats agree/disagree | [MediQ (NeurIPS 2024)](https://arxiv.org/abs/2406.00922): naive question-asking *hurts* without abstention | Non-leading, observation-first questions; acquiescence modelled for yes/no forms |
| Know when to ask or abstain | - | [KnowNo (CoRL 2023)](https://arxiv.org/abs/2307.01928): conformal "ask for help"; MediQ abstention | Constructive abstention; calibration checked in evaluation |
| Untrusted input → tool use | - | [CaMeL (DeepMind 2025)](https://arxiv.org/abs/2503.18813): dual LLM, control/data separation | The extractor is quarantined and outputs typed data only; the planner is not an LLM |
| Multi-party speech | - | [MultiPartyTurnBench (Oct 2026)](https://arxiv.org/abs/2610.20172): selective interruption near chance; [Speak or Stay Silent](https://arxiv.org/abs/2603.11409); [JarvisBench](https://arxiv.org/abs/2608.14870) | We avoid shared-floor conversation: isolated 1:1 calls coordinated by a belief state, which also keeps observations independent |
| Closed-loop discovery | Autonomous labs (Coscientist, A-Lab; Nature 2023) | [AgentRCA (2026)](https://arxiv.org/abs/2607.22385): digital twin + LLM evidence-gathering | Hypothesis → experiment → update → verification |

---

## 11. Radical USP candidates (12 shown; 17 evaluated in `docs/USP_LAB.md`)

| # | Candidate | What it does | Surprise factor | Decision |
|---|---|---|---|---|
| U1 | **Value-of-Information Router** | Picks *(person, observation, phrasing)* that maximizes decision-relevant information per second of human effort, respecting permissions, travel and fatigue | It sends the guard to the closet and lets the student stay in bed, for quantified reasons | **Build (C1)** |
| U2 | **Decision-Sufficient Stopping + Constructive Abstention** | Stops when the *action* is certain; otherwise says "can't tell; cheapest resolver is X" | It stops before knowing everything, on purpose | **Build (C1)** |
| U3 | **Physics-Consistent Testimony Weighting** | Joint posterior over fault and each person's reliability, from consistency with the causal model | It works out who is probably wrong without being told, within one incident | **Build (C2)** |
| U4 | **Contradiction Resolver with Reconciliation Hypotheses** | On conflict, considers "one is wrong", "both right in different contexts (different AP/time/device)" and "the world changed"; designs a tie-break | Treats contradictions as clues, not noise | **Build (C2)** |
| U5 | **Belief-Synchronized Parallel Calls + Live Preemption** | 2–3 simultaneous calls; one answer re-scores the others' pending questions; questions are cancelled or rewritten mid-call | Changes its question mid-call because someone else just answered | **Build (C3, P1)** |
| U6 | **Decision-Critical Confirmation** | Confirms an answer only if the decision would flip under the alternative reading (hedge, second ASR decode, extraction ambiguity) | Confirms the one answer that matters and skips the rest | **Build (C3, P1)** |
| U7 | **Question-Conditioned Speech Recognition** | Per question, passes the spoken question as `previous_text` and the expected answer vocabulary as `keyterms` to Prisma v3.0 | Uses Gnani's context hints as a dialogue-state prior | **Build (C3, P1)**, internal ablation only (EULA, §22) |
| U8 | **Proof-of-Presence Challenge** | Before trusting a decision-critical observation from a restricted place, asks for a detail visible only there (label suffix) | Catches a "false claim of being there" naturally | **Build (C2, P1)** |
| U9 | **Risky-Prediction Verification** | After the repair, tests a non-obvious implied consequence that was not used in diagnosis (the NVR shows a fresh boot) | Popperian closure instead of "is it fixed?" | **Build (C4)** |
| U10 | **Interventional Disambiguation** | When hypotheses are observationally equivalent, proposes a safe, reversible, authorized intervention (swap AP port) with predicted outcomes | Does an experiment, not just a survey | **Simplify (C4, P1)**: one intervention type |
| U11 | **Map-Drift Discovery** | Detects that the documented topology is wrong and localizes the documentation error from testimony | The AI corrects the building's own documentation | **Stretch (P2)** |
| U12 | **Investigation Forecast & Dispatch Advisor** | Monte Carlo rollouts of its own policy: expected calls, minutes, P(resolve without dispatch); "dispatch now or keep investigating?" | Forecasts its own investigation | **Stretch (P2)** |

Evaluated but not selected (details in USP_LAB):
- Open-World Hypothesis Induction ("LLM proposes, Bayes disposes"): defer.
- Non-Leading Elicitation Protocol: folded into C2/C3.
- Silent-Witness Harvesting of volunteered observations: folded into the extractor.
- Speculative next-question pre-synthesis: latency engineering, P1.
- Consent-first human sensor network with effort budgets: minimal version in P0.

---

## 12. Ruthless prioritization

Scores are 1–5 (5 = best; for "Cost", 5 = cheapest). Full rationale is in `docs/USP_LAB.md`.

| Candidate | Orig. | Useful | Depth | Demo | Reliab. | Cost | Differ. | Feasible by Nov 10 | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| U1 VOI Router | 4 | 5 | 5 | 4 | 4 | 3 | 4 | 4 | **Core** |
| U2 Decision stop + abstain | 4 | 5 | 4 | 4 | 4 | 4 | 4 | 5 | **Core** |
| U3 Testimony weighting | 4 | 4 | 5 | 4 | 4 | 4 | 4 | 4 | **Core** |
| U4 Contradiction/reconciliation | 4 | 4 | 4 | 5 | 4 | 4 | 4 | 4 | **Core** |
| U9 Risky-prediction verification | 4 | 5 | 4 | 5 | 4 | 4 | 4 | 4 | **Core** |
| U5 Parallel calls + preemption | 5 | 4 | 4 | 5 | 3 | 2 | 5 | 3 | **P1** (after the sequential loop works) |
| U8 Proof-of-presence | 4 | 3 | 2 | 5 | 4 | 5 | 4 | 5 | **P1** (cheap, memorable) |
| U6 Decision-critical confirmation | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 4 | **P1** |
| U7 Question-conditioned ASR | 3 | 4 | 3 | 2 | 4 | 4 | 3 | 5 | **P1** |
| U10 Interventional disambiguation | 3 | 4 | 4 | 4 | 3 | 3 | 3 | 3 | **P1 simplified** |
| U11 Map-drift discovery | 5 | 4 | 4 | 5 | 3 | 2 | 5 | 2 | **P2** |
| U12 Forecast/dispatch advisor | 4 | 4 | 3 | 3 | 4 | 3 | 4 | 3 | **P2** |

**Why these and not more.**
- U1–U4 and U9 are one engine viewed from different angles. Building one makes the others cheap.
- U5, U6, U7 and U8 are what make the *voice* part essential rather than decorative.
- U11 is the most surprising feature, but it needs topology-variant hypotheses and its own scenarios. If it is half-built, it would weaken the demo.

---

## 13. Final selected product capabilities

Every capability below follows the same template: problem → story → behavior → algorithms → I/O → dependencies → happy path → failure path → acceptance → demo → novelty → priority.

### C1. Ask-the-World Planner

- **User problem.** Coordinators ask the wrong people the wrong questions in the wrong order, and don't know when to stop.
- **User story.** As a duty manager, I want the system to decide whom to call and what to ask, with a visible reason, so the fault is found with the fewest calls and no unnecessary dispatch.
- **Exact behavior.**
  1. Enumerate feasible actions *a = (participant k, probe p, elicitation variant v)*. Feasibility rules:
     - the participant has consented and is available;
     - they are at, or can reach, the probe's location;
     - they hold the probe's required role/permission;
     - they have not exceeded the per-incident question budget;
     - the probe is safe for their role;
     - the language pair is supported.
  2. For each action, compute **decision-focused expected information gain** `EIG_D(a)` (over decision classes) plus a small hypothesis-entropy term `η·EIG_H(a)`. Both come from exact enumeration of outcomes and hypotheses with participant-specific noise.
  3. Cost `c(a)` is in seconds-equivalent: call setup if not already on a call, plus travel time to the location, plus execution time, plus a fatigue penalty.
  4. Choose a **batch** of up to `K` actions (one per participant) greedily by conditional joint gain per unit cost.
  5. After every committed observation, re-plan.
  6. Stopping:
     - **Decide** if `P(d*) ≥ 0.95`, or if no action has positive net value (EVOI − λ·cost ≤ 0) and `P(d*) ≥ 0.80`.
     - **Abstain** if `P(OPEN_WORLD) ≥ 0.25`, or if no action has positive net value and `P(d*) < 0.80`.
     - On abstention, output the best *infeasible* actions ("needs someone with the IDF-2 key; estimated 4 min").
  7. Every decision emits a `PlanComputed` trace: top candidates, gains, costs, feasibility reasons, and the counterfactual belief for each outcome.
- **Agents/algorithms.** Planner (deterministic), Belief Engine (deterministic), Participant Router (feasibility, inside the Planner).
- **Inputs.** Belief state, domain pack, participant registry (location, roles, languages, availability, budget), call states.
- **Outputs.** `PlanComputed`, `CallRequested` / `ProbeAssigned` commands, `DecisionReached` or `Abstained`.
- **Dependencies.** Domain pack with probes, outcome spaces, costs and decision classes; Belief Engine; Call Runtime.
- **Happy path.** S1 (closet breaker trip) is resolved to the decision `DISPATCH_ELECTRICIAN(DB-C2)` after 4–6 probes across 2–3 people.
- **Failure path.**
  - No feasible informative action → constructive abstention.
  - A participant becomes unavailable → actions are re-scored without them.
  - Planner exception → the investigation pauses with an `EngineError` event and the console shows "manual mode". Calls are kept and the operator can ask manually.
- **Acceptance criteria [T]** (measured in the logic-level benchmark, `docs/EVALUATION.md`):
  - ≥ 90% correct decision class on identifiable scenarios with mean observer reliability 0.9;
  - ≥ 30% fewer probes than the checklist baseline at equal or better accuracy;
  - planning step p95 < 100 ms for ≤ 1,000 hypotheses and ≤ 200 candidate actions;
  - abstention recall ≥ 70% on unidentifiable scenarios, with abstention false-positive rate ≤ 10% on identifiable ones.
- **Demo scenario.** The guard is sent to closet IDF-2 rather than asking the student to "restart the router". The "Why this question?" popover shows gains and costs.
- **Novelty.**
  - Quintess runs "cheapest checks first" for one technician [C].
  - Astyr picks one test for one technician [C].
  - Ours selects across *people* with explicit decision-focused VOI.
  - Research systems (UoT, BED-LLM) select questions for one respondent with an LLM-derived belief. Ours computes belief from a causal model.
- **Priority.** P0 (sequential, K=1), P1 (batch, K≤3).

### C2. Testimony Engine

- **User problem.** People mishear, guess, relay rumours, misread LED colours, or claim to be somewhere they are not. Contradictions stall investigations.
- **User story.** As a duty manager, I want every answer weighted by how believable it is, so contradictions get resolved by evidence and not by whoever speaks loudest.
- **Exact behavior.**
  1. Every answer becomes an **Observation** with:
     - provenance: who, where, when, call/turn id, transcript;
     - outcome (from the probe's enum);
     - **hedge** level: certain / probable / unsure;
     - **directness**: direct / hearsay / assumption;
     - observed-at time ("10 min ago");
     - modality: voice / tap / machine.
  2. Likelihood model: `P(o | h) = Σ_y P(y | h, context) · M_k,c(o | y; r)`. Here `M` is participant *k*'s confusion model for probe class *c* with reliability `r ~ Beta(α, β)`. Errors are structured (amber↔green is more likely than amber↔off). Yes/no questions to lay participants carry an acquiescence skew.
  3. Hedge, hearsay and staleness reduce weight by **mixing toward uniform**, with weights 1.0 / 0.7 / 0.35; hearsay ×0.5 (initial values, calibrated in evaluation).
  4. Reliability is **integrated out per participant** with 21-point Beta quadrature. Each participant's reliability posterior is reported as **"consistency with the physical evidence"** (never as "honesty").
  5. **Contradiction detection.** Two observations conflict if no modelled hypothesis with r=1 explains both. The UI shows three explanation families:
     - someone erred (reliability);
     - both were right in different contexts (*reconciliation hypotheses*: different AP association, different band, a mobile-data confusion);
     - the world changed between the two observations (time).
     The Planner then picks a tie-break.
  6. **Proof-of-presence.** For observations from restricted locations that are decision-critical, the Planner may issue a challenge: "read me the last three characters on the white label of the switch". A pass sets presence to verified. A fail marks location-bound observations from that person as *unverified* (weight 0.2) and routes elsewhere.
  7. Claims of identity, role or authority made in speech are recorded as **Claims** and never change permissions.
- **Agents/algorithms.** Answer Extractor (LLM, quarantined), Belief Engine evidence model (deterministic), Challenge planning (Planner), Contradiction detector (deterministic).
- **Inputs.** Transcript and question context; participant profile; domain pack noise priors; registry presence tokens.
- **Outputs.** `ObservationCommitted`, `ContradictionDetected`, `ChallengeIssued/Passed/Failed`, reliability posteriors.
- **Dependencies.** Extractor schema; domain pack error structures; Planner.
- **Happy path.** S2: Aarav (Room 205) says Wi-Fi works and Neha (Room 210) says it doesn't. The engine raises a reconciliation hypothesis: Aarav is on AP-2B, Neha on AP-2A, and AP-2A is down. The tie-break question to Aarav is "what's the Wi-Fi name and the number after it on your Wi-Fi details screen?", which reveals the AP. Resolved.
- **Failure path.**
  - Extractor returns `unknown` → the dialogue policy re-asks once with a different variant.
  - Still unknown → the observation is dropped with reason `unparseable`.
  - A participant fails a challenge → nobody is accused. Copy: "I couldn't confirm the location; I'll ask someone else."
- **Acceptance criteria [T]:**
  - With one adversarial participant (r≈0.3) among three, decision accuracy drops ≤ 10 points versus all-honest;
  - posterior reliability of the adversarial participant < 0.5 in ≥ 80% of runs;
  - extractor outcome accuracy ≥ 95% on the 150-utterance test set (Hinglish/Marathi/Hindi/English);
  - injection attempts never change permissions or decisions (100%, tested).
- **Demo scenario.**
  - Long demo: a contradiction between two students, resolved by a tie-break.
  - 60-second demo: the guard's presence challenge (2 seconds of screen time).
- **Novelty.** Truth-discovery prior art uses redundancy across many claims or historical data (Dawid–Skene, Wang et al.). Ours works inside one incident using causal consistency plus active tie-breaks. We found no competitor that models observer reliability.
- **Priority.** P0 (reliability quadrature, hedges, contradiction detection); P1 (reconciliation UI, presence challenges, acquiescence modelling).

### C3. Conversation Swarm

- **User problem.** Human answers are slow (30–90 s per question). Sequential calling wastes minutes. Voice errors on short answers ("haan"/"nahi", "302"/"312") silently corrupt evidence.
- **User story.** As a duty manager, I want the system to talk to several people at once in their languages and to stop bothering someone when their answer is no longer needed.
- **Exact behavior.**
  1. Each participant gets an **isolated 1:1 browser voice call**. Isolation keeps observations independent: participants don't hear each other, which avoids herding.
  2. Calls are driven by commands from the investigation actor: `Ask(probe, variant)`, `Clarify`, `Challenge`, `Preempt(new_probe | none)`, `Close(thanks, outcome)`.
  3. **Preemption.** When a committed observation lowers an in-flight probe's value below 30% of its value at issue time, the call runtime acts at the next safe point:
     - before the question has been spoken: the question is swapped silently;
     - while the question is being spoken: TTS stops and the agent says "Sorry, one moment… actually, could you instead check …";
     - after the question, while listening: the agent lets the person finish, then thanks them and skips follow-ups.
  4. **Decision-critical confirmation.** For each extracted answer, alternatives are generated:
     - hedge-induced;
     - extractor second-best;
     - for short decision-critical answers only, a **second Prisma decode** of the buffered utterance with a different configuration (REST, ≤30 s).
     The arbiter re-runs the decision with each alternative. If `argmax d` changes, or `P(d*)` moves by more than 0.15, it asks a confirmation in an item-specific, non-leading form ("Which colour was the light: green, orange or none?"). Otherwise it accepts silently.
  5. **Question-conditioned ASR.** The STT session for each question carries, as Prisma v3.0 headers:
     - `language_code` from the participant's language candidates (e.g., `mr-IN,hi-IN`);
     - `format=codemix` for Hinglish speakers;
     - `keyterms` with the answer vocabulary and site names in all relevant scripts;
     - `previous_text` set to the question as spoken;
     - `topic`.
  6. TTS uses Timbre v3.0 (one voice persona that speaks all 10 languages [V]) or v2.5 per-language voices, decided by the initial listening test. Audio tags such as `<pauses>` give natural pacing.
- **Agents/algorithms.** Call Runtime (deterministic state machine, Darshan), Dialogue Policy and Question Realizer (templates + LLM paraphrase + linter, Nikhil), Confirmation Arbiter (deterministic), Voice Gateway (Darshan).
- **Inputs.** Commands from the actor; participant language profile; probe templates; audio frames.
- **Outputs.** Turns, transcripts, `ObservationProposed`, call state events, latency metrics.
- **Dependencies.** Gnani STT/TTS access, concurrency limits (unknown [V] → initial spike), LLM extractor latency.
- **Happy path.**
  1. Riya (Hinglish) and Mahesh (Marathi) are called in parallel.
  2. Mahesh's answer ("ground floor Wi-Fi works") arrives first. Riya's pending follow-up ("check the ground floor") is preempted and replaced with "does your phone show NAVA-WiFi?".
  3. One borderline answer ("सगळं बंद आहे" / "everything's off") is checked against a second decode; it is consistent, so no confirmation is asked.
- **Failure path.**
  - Concurrency cap hit → fall back to sequential calls or the STT multiplexer (PLAN.md §12).
  - Participant silent for 8 s → one gentle re-prompt; after another 12 s, mark unavailable.
  - Disconnect → mark unavailable and re-plan; retry once after 60 s if the person is still useful.
  - TTS error → play a cached phrase and retry once.
- **Acceptance criteria [T]:**
  - p50 end-of-speech → agent-speech-start ≤ 1.5 s, p95 ≤ 2.5 s (staging, India region);
  - 3 concurrent calls stable for 10 minutes;
  - preemption executed within 1 s of the triggering commit;
  - confirmations asked in ≤ 25% of answers while catching ≥ 80% of injected decision-critical ASR substitutions in the audio-level eval.
- **Demo scenario.** Two call cards are active at once. The pending question in one card visibly changes when the other answers.
- **Novelty.**
  - Multi-party speech research focuses on floor control inside one shared conversation (MultiPartyTurnBench; Speak or Stay Silent). Ours coordinates *isolated* conversations through a shared belief.
  - Confirmation gated by decision sensitivity, rather than ASR confidence alone, is an unusual combination [I].
- **Priority.** P0 (sequential multi-participant voice); P1 (parallel + preemption, confirmation arbiter, question-conditioned ASR).

### C4. Causal Closure

- **User problem.** Teams declare victory when someone says "it works now". Wrong fixes get discovered hours later. Some hypotheses can't be separated by just looking.
- **User story.** As a duty manager, I want proof that the fix addressed the actual cause, and a safe experiment when looking isn't enough.
- **Exact behavior.**
  1. **Authorization gate.** Actions come in three types:
     - `OBSERVE`: anyone, with consent;
     - `DIAGNOSTIC_INTERVENTION`: reversible, low-risk; needs the role plus approval;
     - `REPAIR`: needs the role plus approval.
     The approver (console) receives an `ApprovalRequested` with rationale, risk class, reversibility and expected effect. Approval mints a **signed capability token** (Ed25519; scoped to action, target, investigation, a 5-minute expiry and a nonce). The simulator refuses interventions without a valid token. The LLM never holds tokens.
  2. **Interventional disambiguation (P1, one type).** When the top two hypotheses predict identical outcomes for every feasible observation (observational equivalence) and the decision depends on them, the Planner considers interventions from the pack's safe list ("move AP-3B's cable to spare port 12" by the IT technician). It predicts the outcomes under each hypothesis, ranks by EIG/cost, and requests approval.
  3. **Risky-prediction verification.** After a repair, the system:
     - computes post-action predictions for each hypothesis;
     - picks 1–2 verification probes that maximize I(Fixed; O). It prefers probes **not used during diagnosis** whose expected outcome is improbable under the alternatives (a "risky" prediction);
     - declares VERIFIED if `P(Fixed) ≥ 0.97`;
     - otherwise reopens the investigation with the repaired component's state updated and the alternatives promoted.
  4. Closing: the system thanks participants and tells each one, in their language, how their answer helped (one sentence).
- **Agents/algorithms.** Safety & Authorization Gate (deterministic), Verification Designer (deterministic), Planner (intervention ranking), Explainer (LLM, grounded).
- **Inputs.** Decision, belief, pack actions (risk/reversibility/roles), approvals.
- **Outputs.** `ApprovalRequested/Granted/Denied`, capability token, `VerificationPlanned`, `VerificationResult`, `InvestigationClosed` or `Reopened`.
- **Happy path.** In S1, after the breaker reset, the system predicts "the CCTV recorder in IDF-2 shows a boot screen" (true only if closet power was restored) and "NAVA-WiFi is visible again on floor 3". Both are confirmed → VERIFIED. The sealed fault is then revealed and matches.
- **Failure path.**
  - Approval denied → the investigation closes with the decision and no action.
  - Verification fails → REOPENED; the belief is recomputed with the repair applied.
  - Capability expired → re-request.
- **Acceptance criteria [T]:**
  - zero interventions executed without a valid token (enforced by tests);
  - verification catches ≥ 90% of injected "wrong repair" cases in the benchmark;
  - verification adds ≤ 2 probes on average.
- **Demo scenario.** The CCTV boot-screen prediction, then the reveal.
- **Novelty.**
  - Astyr requires a human field verdict before prescribing a fix [C]; Quintess leaves verification to the customer [C].
  - Ours selects the verification *test* to discriminate between hypotheses, and prefers held-out consequences.
- **Priority.** P0 (approval + capability + verification); P1 (one diagnostic intervention type).

### Proof layer (required for credibility, P0/P1)

- **Glass-box console.** Live belief bars, an entropy meter in bits, a decision-class bar, "Why this question?" counterfactual previews, an evidence ledger with provenance chips, approvals, and **replay** (P1).
- **Sealed-fault mode.**
  - The fault is chosen at random or by a judge.
  - Its SHA-256 commitment (`H(scenario_id ‖ fault_spec ‖ salt)`) is shown at the start; fault and salt are revealed at the end.
- **Benchmark.**
  - 500+ randomized scenarios.
  - Policies compared: checklist, random, greedy entropy, **frontier LLM choosing from the same action menu**, ours, plus an oracle bound.
  - Ablations, calibration, and stress tests (noise, adversary, unavailability, change).
  - See `docs/EVALUATION.md`.

---

## 14. Complete user journeys

**J1 - Duty manager (primary)**
1. Opens the console → **New investigation** → selects site "Hostel Block C (simulated)" → sees the participant directory with presence, role and language.
2. Either a reporter's voice report arrives (J2), or the manager types or speaks the report.
3. The console shows affected areas tinted, 8–15 initial hypotheses, and the first plan with reasons.
4. Watches up to 3 call cards with live captions in the original language, plus an English gloss.
5. Hypothesis bars move as evidence arrives. Contradictions appear as amber banners with the planned tie-break.
6. Receives **Decision**: "Dispatch electrician to DB-C2 (93%)". Reads the rationale and evidence list, then clicks **Approve breaker check & reset (Imran)**.
7. Watches verification. Gets **Verified** (or **Reopened**). Exports the investigation record and can replay it.

**J2 - Reporter.** Opens the "Report a problem" link/QR → consents → speaks naturally ("Floor 3 pe WiFi bilkul nahi chal raha") → hears a short acknowledgement and an estimated time → may be asked 1–2 follow-ups → gets a closing message when the incident is resolved.

**J3 - Lay observer (student)**
1. Receives a call invitation in the browser, with a notification and ringtone.
2. Hears a consent line in their language, including that they can decline.
3. Answers 1–3 questions about what they can see on their phone or around them. Never asked to touch equipment.
4. Gets thanked, with how their answer helped.
5. Can say "baad mein" (later) to decline. The system respects it and re-plans.

**J4 - Observer with access (guard).** Gets the same call flow, plus:
- "Could you walk to the IDF-2 closet on floor 2? Tell me when you're there." The walking time is counted as cost; the guard taps "I'm here" or says so.
- Questions about LEDs and screens.
- Possibly a proof-of-presence challenge.
- Never asked to open panels or touch equipment.

**J5 - Authorized technician (electrician)**
1. Called with context: "The likely cause is breaker 7 in DB-C2."
2. Asked to *observe* first ("is breaker 7 up or down?").
3. On a finding, the system requests approval; once approved: "You're cleared to reset breaker 7."
4. The technician performs the action (simulator button gated by the capability token) and reports.

**J6 - Judge/evaluator (sealed mode)**
1. Picks or randomizes the hidden fault and sees only the commitment hash.
2. Optionally plays a participant and answers however they like, including lying.
3. Sees the plan adapt.
4. At the end, verifies the reveal against the hash and checks the ground-truth panel.

**J7 - First-time onboarding (site admin)**
1. Loads a domain pack: YAML for components, dependencies, locations, probes and actions. Bundled packs are available.
2. Adds participants: synthetic names, roles, languages, location or post.
3. Prints or shares QR invite links. Participants open them and grant microphone permission.
4. Runs the built-in self-test call (10 s).

---

## 15. End-to-end investigation workflow

```
INTAKE ──report──▶ HYPOTHESIZE ──prior+initial obs──▶ PLAN ──batch──▶ ENGAGE (calls)
   ▲                                                    ▲                │ answers
   │                                                    │                ▼
REOPEN ◀──fail── VERIFY ◀──done── ACT ◀──approved── APPROVE ◀── DECIDE ◀── UPDATE (Bayes)
                    │                                   │            ▲      │
                    └──pass──▶ CLOSE                    └─denied─▶ CLOSE    └─▶ ABSTAIN (with "what it would take")
```

1. **Intake.** The report (voice → Prisma → text) goes to the Intake Interpreter (LLM, quarantined). The output is initial observations (probe, outcome, location, source = reporter) plus incident metadata. Unmappable content is stored as free-text notes and **never** becomes evidence automatically.
2. **Hypothesize.** The Belief Engine loads the hypothesis space (singles, plausible pairs, no-fault, open-world) and applies the initial observations.
3. **Plan.** The Planner computes the batch, or decides/abstains.
4. **Engage.** The Call Runtime calls participants. The Question Realizer phrases each question; the linter checks it is non-leading, safe and in the right language.
5. **Evidence.** STT transcript → Answer Extractor → `ObservationProposed` → Confirmation Arbiter (accept/confirm) → `ObservationCommitted`.
6. **Update.** Exact posterior, reliability posteriors, contradiction check, change/surprise check.
7. **Loop** back to Plan. In-flight probes are re-scored and possibly preempted.
8. **Decide / Abstain.** Decision with confidence, rationale and "what would change my mind" (the observation whose opposite outcome would flip the decision).
9. **Approve.** A human approver with the right role approves or denies; a capability token is minted.
10. **Act.** The authorized participant performs the action in their environment and reports by voice.
11. **Verify.** Risky-prediction probe(s) → VERIFIED or REOPENED.
12. **Close.** Participants are thanked, the record is finalized, and (in sealed mode) ground truth is revealed and scored.

---

## 16. Agent responsibilities (what each component actually does)

There are 12 components. **Four use an LLM** (Intake, Realizer, Extractor, Explainer). All are at the language boundary, none can call tools, and none can modify permissions.

> Format per component: trigger · inputs · outputs · reads · writes · tools · algorithm · expected behaviour · communication · failure recovery · safety · tests · example · acceptance.

**A1. Intake Interpreter** (LLM, quarantined; owner Nikhil)
- *Trigger:* `ReportReceived`.
- *Inputs:* transcript, reporter profile, pack vocabulary (locations, probe catalogue).
- *Outputs:* `IntakeResult{observations[], affected_locations[], notes, injection_suspected}` (strict JSON schema).
- *Reads:* pack. *Writes:* nothing directly; the actor commits observations.
- *Tools:* none.
- *Algorithm:* schema-constrained extraction. Probe IDs and outcomes are restricted to enums generated from the pack.
- *Behaviour:* conservative. It maps only explicit statements ("no internet" → `site_loads=no`, not "AP dead").
- *Communication:* returns its result to the actor.
- *Failure recovery:* invalid output → one retry with the error message; then fall back to notes only and the Planner asks the reporter a standard first question.
- *Safety:* imperative content is flagged and ignored.
- *Tests:* 60 report utterances with expected mappings.
- *Example:* "Floor 3 pe WiFi bilkul nahi chal raha, kuch load nahi ho raha" → `[site_loads@F3=no(direct, certain)]`, affected=[F3].
- *Acceptance:* ≥ 95% exact-match on mapped probes; 0 hallucinated observations on 20 adversarial reports.

**A2. World Model Compiler** (deterministic; Nikhil)
- *Trigger:* investigation start or pack change.
- *Inputs:* domain pack YAML (documented topology).
- *Outputs:* hypothesis set H (singles + pruned pairs + `NO_FAULT` + `OPEN_WORLD` [+ topology variants in P2]); prediction tensor `P(y | h, probe, location)`; decision-class map `dec(h)`; prior π.
- *Algorithm:* forward propagation (power → device → link → service → observable) per hypothesis. Pairs are pruned to those with joint prior ≥ 1e-4 or sharing a symptom region.
- *Failure recovery:* pack validation errors block start with readable messages.
- *Tests:* golden prediction tables for each fault type.
- *Acceptance:* compile time < 2 s for ≤ 1,000 hypotheses.

**A3. Belief Engine** (deterministic; Nikhil)
- *Trigger:* `ObservationCommitted`, `InterventionApplied`, time tick (dynamic mode).
- *Inputs:* observations; prediction tensor; participant noise priors.
- *Outputs:* `BeliefUpdated{posterior top-k, P(decision classes), entropy bits, reliability posteriors, surprise}`; `ContradictionDetected`.
- *Reads/writes:* in-memory belief inside the investigation actor; snapshots go to the event log.
- *Algorithm:* §19. Log-space likelihoods, 21-point Beta quadrature per participant, mixing for hedge/hearsay/staleness, exact normalization. Surprise = −log P(o | data).
- *Failure recovery:* numerical underflow guarded by log-sum-exp. If every hypothesis has likelihood ≈ 0, `OPEN_WORLD` absorbs it, by design.
- *Tests:* hand-computed 2–3-hypothesis cases; property tests (posterior sums to 1; adding a duplicate consistent observation never decreases the true hypothesis's posterior when r > 0.5); deterministic replay.
- *Example:* see S1 trace in `docs/DEMO.md`.
- *Acceptance:* matches brute-force reference within 1e-9; update p95 < 20 ms.

**A4. Planner + Participant Router** (deterministic; Nikhil)
- *Trigger:* `BeliefUpdated`, participant availability change, call slot freed.
- *Inputs:* belief, feasible actions, costs, budgets, K.
- *Outputs:* `PlanComputed`, `ProbeAssigned`, `PreemptRequested`, `DecisionReached`, `Abstained`, `ChallengePlanned`, `InterventionProposed`.
- *Algorithm:* §19 (decision-focused EIG/cost, greedy batch, EVOI stop rule, abstention with infeasible-action report, fairness: max 4 questions per participant per incident, 60-s cool-down after a "later").
- *Failure recovery:* exception → manual mode.
- *Safety:* only pack-listed probes and actions; role checks are delegated to A10.
- *Tests:* toy cases with known optimal first probe; regression on seeds.
- *Acceptance:* see C1.

**A5. Question Realizer** (templates + LLM paraphrase + deterministic linter; Nikhil)
- *Trigger:* `ProbeAssigned`, clarify, challenge.
- *Inputs:* probe, variant, participant language/skill, location names, the agent's previous utterance.
- *Outputs:* `Utterance{text, language, ssml-free tags, keyterms[]}`.
- *Algorithm:*
  1. Choose a pre-written template per (probe, variant, language). Templates are hand-checked by native speakers on the team or among volunteers.
  2. Optionally apply an LLM paraphrase for naturalness, constrained to keep slots.
  3. Run the **linter**. It rejects the utterance if it mentions hypotheses or causes ("because the switch failed"), suggests an answer in an open-form variant, contains unsafe verbs not allowed for the role (open panel, unplug, touch), lacks a location anchor, or exceeds 25 words.
  4. Apply the speakable-text normalizer: room numbers are read digit by digit; no IP addresses are spoken.
- *Failure recovery:* if the linter fails twice, use the raw template.
- *Tests:* linter unit tests; 100 generated utterances reviewed.
- *Acceptance:* 0 linter-escaping unsafe instructions in tests.

**A6. Call Runtime** (deterministic state machine; Darshan) with **Dialogue Policy** (content and timing rules; Nikhil)
- *Trigger:* commands from the actor.
- *States:* `RINGING → CONSENT → (IDENTITY_OK) → ASKING → LISTENING → EXTRACTING → (CONFIRMING|CHALLENGING) → IDLE → CLOSING → ENDED`, plus `PREEMPTING`, `UNAVAILABLE`, `DROPPED`.
- *Inputs:* commands, STT events, TTS completion, timers.
- *Outputs:* turn events, `ObservationProposed`, call-state events.
- *Algorithm/policy:*
  - consent first;
  - one question at a time;
  - wait for end-of-speech (Prisma VAD) plus a completeness check (if the extractor says `incomplete`, wait 1.2 s more);
  - barge-in: participant speech during TTS stops TTS;
  - silence: 8 s re-prompt, 20 s unavailable;
  - "later/busy/no" → close politely and mark unavailable for 15 minutes.
- *Failure recovery:* WebSocket drop → `DROPPED`, actor re-plans; STT session error → reconnect once; Prisma 15-minute session limit → rotate the session at question boundaries.
- *Safety:* never speaks text that has not passed A5's linter.
- *Tests:* scripted bot participants (text and audio); timer tests.
- *Acceptance:* see C3.

**A7. Answer Extractor** (LLM, quarantined; Nikhil)
- *Trigger:* final transcript segment(s) in `LISTENING`.
- *Inputs:* transcript, the question asked, probe outcome enum, participant language.
- *Outputs (strict schema):* `{probe_id, outcome∈enum∪{unknown}, alt_outcome?, hedge, directness, observed_relative_time?, incomplete:boolean, extra_observations:[{probe_id, location_id, outcome}], wants_to_stop:boolean, injection_suspected:boolean}`.
- *Algorithm:* schema-constrained output; enums only. Extra observations are allowed only for pack probes ("silent witness").
- *Failure recovery:* schema failure → retry once → `unknown`.
- *Safety:* the output is data only. It never reaches a component that can act, except through typed fields validated against enums.
- *Tests:* ≥ 150 utterances (code-mixed; hedges like "shayad", "lagta hai", "kadachit"; hearsay like "mere roommate ne bola"; injections).
- *Acceptance:* ≥ 95% outcome accuracy; ≥ 90% hedge/directness accuracy; 100% injection flags on the injection subset.

**A8. Confirmation Arbiter** (deterministic; Nikhil)
- *Trigger:* `ObservationProposed`.
- *Inputs:* proposed observation, its alternatives (alt_outcome, hedge, second-decode outcome), belief.
- *Outputs:* accept, or `Confirm(probe, item-specific variant)`.
- *Algorithm:* decision-flip test, plus a ΔP(d*) > 0.15 threshold. The second decode is triggered only when the transcript is ≤ 4 words *and* the probe is decision-critical (top-3 candidate).
- *Acceptance:* see C3.

**A9. Verification Designer** (deterministic; Nikhil)
- *Trigger:* `InterventionApplied` (repair).
- *Algorithm:* see C4.
- *Acceptance:* see C4.

**A10. Safety & Authorization Gate** (deterministic; Darshan)
- *Trigger:* any action proposal or approval.
- *Algorithm:* role → action-type matrix; reversibility and risk checks; approver role check; mint/verify Ed25519 capability tokens; rate limits; budget guard (max calls, minutes, credits).
- *Tests:* exhaustive role × action matrix tests; token replay and expiry tests.
- *Acceptance:* 100% denial of unauthorized paths.

**A11. Explainer** (LLM, grounded; Nikhil)
- *Trigger:* `PlanComputed`, `DecisionReached`, on demand.
- *Inputs:* the structured trace only: numbers, the observation list, hypothesis names.
- *Outputs:* ≤ 2-sentence English rationale (+ optional Hindi/Marathi spoken summary for technicians).
- *Safety:* may not introduce facts outside the trace. A post-check verifies that every hypothesis or observation it mentions exists in the trace.
- *Acceptance:* 0 ungrounded entity mentions in 100 checks.

**A12. Recovery Supervisor** (deterministic; Darshan)
- Watches timeouts, dropped calls, engine errors and budget exhaustion. Emits recovery commands: re-plan, retry once, manual mode, graceful close.
- Reconstructs actors from the event log after a process restart.

---

## 17. Agent tools and permissions

| Actor | Can read | Can write / do | Cannot |
|---|---|---|---|
| LLM roles (A1, A5, A7, A11) | Their input payload only | Return schema-validated data | Call tools, see other calls, see the belief (except A11 sees its trace), mint tokens, speak unlinted text |
| Planner / Belief Engine | Pack (documented), observations, registry | Plans, decisions, belief snapshots | See simulator truth (separate service, no credentials) |
| Call Runtime | Commands, audio | Utterances (linted), transcripts | Execute actions |
| Safety Gate | Registry, approvals | Capability tokens | Approve on its own |
| Human approver (console) | Everything in the console | Approve or deny, close the investigation | Bypass the role matrix |
| Participants | Their own simulated view | Speak; perform view actions; perform interventions only with a token | See other calls or the belief |
| Simulator | Truth | Views; apply interventions with valid tokens | Accept unsigned interventions |
| Eval harness | Truth (oracle key) after a run | Scores | Run inside the core process |

---

## 18. Hypothesis and evidence lifecycle

**Hypothesis states.**
- `active` → `dominant` (≥ 0.5) → `decided` (its decision class is chosen).
- Alternatively `suppressed` (< 1e-4; still tracked).
- After repair: `repaired-assumed` → `verified` / `refuted`.
- `OPEN_WORLD` stays active with a small prior. It rises when the evidence fits nothing.

**Evidence types (provenance class) and default weight.**

| Type | Example | Default treatment |
|---|---|---|
| Direct observation | "The switch lights are all off" | Full likelihood with that person's reliability |
| Hedged observation | "I think it's green" | Mixed toward uniform (0.7 or 0.35) |
| Hearsay | "My roommate says it's down" | ×0.5 mixing; `relay` provenance chain |
| Assumption/inference by the participant | "The router must be dead" | **Not evidence**; stored as a note (participants' conclusions are not observations) |
| Claim (identity/role/presence) | "I'm the IT admin" | Never changes permissions; presence claims can be challenged |
| Machine probe (optional) | Simulated ping from the core | High reliability |
| Intervention report | "I reset breaker 7" | A state change, applied once the token was valid and the participant confirms |

**Evidence states.** `proposed → committed → (confirmed | superseded | retracted)`. Staleness grows with time in dynamic mode. All transitions are events.

---

## 19. Experiment-selection mechanisms (exact)

**Notation.**
- H: hypotheses.
- D: decision classes, with `dec: H → D`.
- Data so far: 𝒟.
- Candidate action `a = (k, p, v)` with outcome space `O_p`.

**Prediction.** `P(y | h, ctx_a)` comes from the compiled tensor. It may be fractional; for example, a phone in Room 205 associates with AP-2A with probability 0.7 and AP-2B with 0.3.

**Noise.**
- `M_k,c(o | y; r) = r·[o=y] + (1−r)·q_c(o | y)`, where `q_c` is a structured error distribution with acquiescence skew for closed yes/no forms.
- Hedge, hearsay and staleness weight `w`: `M' = w·M + (1−w)/|O_p|`.

**Likelihood with reliability integrated out (exact up to quadrature).**

`L_k(h) = Σ_g β_g · Π_{i∈obs(k)} M'_k,c_i(o_i | h; r_g)`

where `r_g` are 21 grid points and `β_g` are Beta(α_k,c, β_k,c) weights. Given h, participants are independent, so the posterior is

`P(h | 𝒟) ∝ π(h) · Π_k L_k(h)`.

Reliability posterior: `P(r_g | 𝒟, k) ∝ β_g Σ_h P(h | 𝒟_{−k}) Π_{i∈obs(k)} M'(o_i | h; r_g)`, shown as "consistency".

**Predictive distribution for an action.** `P(o | a, 𝒟) = Σ_h P(h | 𝒟) · Σ_g P(r_g | h, 𝒟_k) · Σ_y P(y | h, ctx_a) · M'(o | y; r_g)`.

**Decision-focused gain.**
- `EIG_D(a) = H[D | 𝒟] − Σ_o P(o | a, 𝒟) · H[D | 𝒟, o]`
- `EIG_H(a)` is defined the same way over H.
- `score(a) = (EIG_D(a) + η·EIG_H(a)) / c(a)` with η = 0.1. The η term breaks plateaus where no single observation moves the decision; this is the myopia problem noted by Golovin et al.

**Cost.** `c(a) = setup_k (15 s if not on a call) + travel(k → loc_p) + exec(p, v) + fatigue_k`, where fatigue is 5 s × the number of questions already asked to k.

**Batch (parallel calls).**
- Greedy: `S ← ∅`; repeat up to K times: `a* = argmax_{a ∉ S, part(a) ∉ part(S)} [I(D; O_{S∪a}) − I(D; O_S)] / c(a)`.
- Joint mutual information is computed by enumerating joint outcomes (≤ 4³) × |H|.
- Mutual information is submodular for observations that are conditionally independent given h (Krause & Guestrin 2005), which justifies the greedy method. With reliability coupling, that is approximate [I].

**Stop / decide / abstain.**
- `d* = argmax P(d | 𝒟)`.
- Expected loss of acting now: `L_now = Σ_h P(h | 𝒟) · loss(d*, h)`, using the pack's loss matrix in minutes-equivalent.
- `EVOI(a) = L_now − E_o[min_d Σ_h P(h | 𝒟, o) loss(d, h)]`.
- Rules:
  - Decide if `P(d*) ≥ 0.95`.
  - Else continue if `max_a (EVOI(a) − λ·c(a)) > 0`.
  - Else decide with a "moderate confidence" flag if `P(d*) ≥ 0.80`.
  - Else abstain, reporting the top infeasible actions.
  - Abstain immediately if `P(OPEN_WORLD) ≥ 0.25`.

**Preemption.** For an in-flight action `a` issued with score `s₀`, re-score `s₁` after each commit. Preempt if `s₁ < 0.3·s₀` and `a` has not yet been answered.

**Verification.**
- `F = {h : repair resolves the symptoms of h}`.
- Choose probe `p` maximizing `I(F; O_p)` + 0.2·[p unused in diagnosis] + 0.2·riskiness, where `riskiness = 1 − P(o_expected | ¬F)`.

**Change detection (dynamic mode).**
- Staleness weight `w_t = exp(−λ Δt)`, with λ = 1/30 min⁻¹ when enabled.
- If the surprise of the new observation exceeds 3 bits *and* it conflicts with evidence older than 10 minutes, raise `PossibleStateChange` and plan a refresh of the most decision-critical stale observation.
- This is a heuristic, not a full HMM. It is labelled as such.

**Complexity.**
- |H| ≈ 400–900 for the campus pack.
- Candidates ≈ 50–150.
- Per plan: ≲ 10⁶ multiply-adds; numpy runs this in milliseconds [I], to be verified in tests.

---

## 20. Human-participant coordination

- **Consent.** Explicit per call ("Is it OK to ask you two quick questions about the Wi-Fi? You can say no."). Revocable at any time. Consent is logged.
- **Effort budgets.** At most 4 questions per person per incident; travel only with consent and an estimated time ("about 1 minute walk"). Never more than one walk request per person per incident without asking.
- **Fairness.** Load is spread (the fatigue term). The same person is not repeatedly chosen just because they are reliable; reliability affects weight, not who gets bothered.
- **Availability.** Directory status: available / busy / do-not-disturb windows. A "later" answer triggers a 15-minute cool-down.
- **Isolation.** 1:1 calls only. The system never tells one participant what another said, which keeps observations independent. Exception: technicians get the *hypothesis* (not people's names).
- **Languages.** Each person has STT language candidates (≤ 4 for Prisma v3.0 [V]) and a TTS language. Mid-call switching is handled because v3.0 detects among the candidates.
- **Closing the loop.** Every participant gets one sentence about how their answer helped, and the outcome.

---

## 21. Speech pipeline

```
Browser mic (getUserMedia: echoCancellation, noiseSuppression, autoGainControl ON)
 → AudioWorklet: resample to 16 kHz mono, Int16 LE, 512-sample (1,024-byte) frames every 32 ms
 → WSS to core (/ws/calls/{id}/audio) ─▶ Prisma v3.0 realtime WS per question (headers: model, language_code, format, keyterms, previous_text, topic, VAD)
 ← transcript events (final only; no interim [V]) ─▶ Extractor ─▶ Arbiter ─▶ Actor
Actor ─▶ Realizer ─▶ Timbre (WS/SSE; linear PCM 16/24 kHz) ─▶ core ─▶ browser AudioWorklet player (ring buffer)
Barge-in: Prisma `speech_start` or local VAD energy during playback → stop playback, cancel remaining TTS
```

- **VAD settings** (Prisma headers [V]):
  - `x-min-silence-ms` 600 (conversation);
  - `x-min-segment-ms` 100, because higher values silently drop short answers like "yes" [V];
  - `x-min-speech-ms` 100;
  - `x-vad-threshold` 0.6;
  - `x-idle-timeout-sec` 120.
  All tuned on Day 1.
- **Question-conditioned STT.** One STT session per question, opened when the question starts playing so the session is warm, closed after extraction. This avoids the 15-minute limit [V] and lets each question carry its own context headers.
- **Second decode** (Arbiter only). REST `POST /stt/v3` on the buffered utterance (≤ 30 s [V]) with an alternative configuration, for example no keyterms or a different language order.
- **Fallbacks:**
  - (a) REST-per-utterance with local Silero VAD, if realtime concurrency < needed calls;
  - (b) a single-stream multiplexer that serializes VAD-segmented utterances from several calls into one realtime session with `commit` markers;
  - (c) a text-input accessibility fallback, logged as `modality=tap`.
- **Latency budget [T].**

  | Stage | Budget |
  |---|---|
  | End-of-speech detection | 600 ms |
  | STT final | ≤ 400 ms (docs examples show 320–380 ms latency fields [V]) |
  | Extraction | ≤ 500 ms (model choice on Day 1) |
  | Plan | < 50 ms |
  | Next utterance | pre-realized/pre-synthesized speculatively (P1) |
  | TTS first audio | ≤ 300 ms ([C]: Gnani claims < 200 ms p95) |
  | **Total p50** | **≤ 1.5 s** |

---

## 22. Gnani AI integration

| Gnani technology | Status [V] | Our use | Why it is necessary rather than decorative |
|---|---|---|---|
| **Prisma v3.0 STT, realtime WebSocket** (`wss://api.vachana.ai/stt/v3/stream`, header `X-API-Key-ID`) | Released 22 Oct 2026; opt-in; 10 languages; `indic-auto` or up to 4 language candidates; `codemix`/`transliterate`; `keyterms` (≤200), `topic` (≤1,600 chars), `previous_text`; final transcripts only; 15-minute session cap; per-org concurrency cap (number unpublished) | Every participant utterance; per-question context; code-mixed Hinglish; Marathi/Hindi | The observers speak Marathi, Hindi and Hinglish on noisy devices. Short answers decide the diagnosis. |
| **Prisma REST** (`POST /stt/v3`, ≤ 30 s) | Available | Second-opinion decode for decision-critical short answers; fallback path | It is our only uncertainty signal, since no confidence scores are returned [V] |
| **Timbre TTS** (v3.0: 13 voices, each speaks 10 languages, audio tags; v2.5: 42 per-language voices including Marathi Zahira/Ishaan and Hinglish Poorvi `hi-en`) | Available; the programme page labels Timbre "Beta" | The agent's voice; a consistent persona across languages; `<pauses>` | Questions must be clear to non-English speakers |
| **Evon v3.3** (30B MoE, ~3.5B active; 128K context; 11 languages including Marathi; Apache-2.0; open weights; **not on the API platform**) | Self-host only (vLLM ≥ 0.12; H100/A100 class recommended) | **P1 "sovereign path"**: run the Extractor and Realizer on Evon if a Day-2 gate passes (accuracy and latency) | It makes the language layer sovereign. The decision layer is our own code already. |
| Python SDK `gnani-vachana`, `livekit-plugins-gnani`, `pipecat-gnani` | Available; docs inconsistent across pages (e.g., SDK STT shows no `model` param; LiveKit's own page lists only older Timbre versions) | Raw WebSocket/REST clients in our gateway; LiveKit plugin is plan B | Control over per-question headers and the multiplexer |
| Agent Builder / Inya | **Out of programme scope** ("we don't offer APIs for it yet") [V] | Not used | - |
| Warp (speech-to-speech) | Not on the API platform [I from programme FAQ: credits cover hosted models] | Not used | - |

**Compliance notes.**
- **EULA §16** says results of benchmark tests on the Gnani Product "may not be disclosed outside Your organization", and **§4.2(g)** prohibits disclosing "information relating to the performance or quality" [V] ([EULA](https://www.gnani.ai/legal/eula)). Therefore:
  - We publish **no** standalone Prisma/Timbre accuracy or latency numbers and **no** vendor comparisons.
  - We do publish our own system's diagnostic metrics.
  - ASR ablations (U7) stay internal, or go into the private submission to Gnani.
  - We ask on Gnani's Discord before publishing anything voice-quality-related.
- **Programme rule** [V]: synthetic data only. No real phone numbers, Aadhaar, PAN or recorded calls in the project or demo. Volunteers give written consent; display names are synthetic.

---

## 23. Environment simulator requirements

- **Separate service with sealed truth.**
  - The core has **no network route or credential** for truth endpoints.
  - The truth module is not importable from the core package; this is enforced by an import-linter contract in CI.
  - Truth is readable only with the oracle key, which only the eval harness and the operator's "reveal" step hold.
- **Two topologies.** *Documented* (the agent's) and *true* (the simulator's). They are identical except in map-drift scenarios.
- **Entities.**
  - Buildings, floors, rooms and closets, with walking times between them.
  - Power circuits and distribution boards.
  - Network devices: gateway, DHCP, DNS, auth, fibre link, switches, APs, wired ports.
  - Collateral devices: CCTV NVR, lift, corridor lights.
  - Participants with location, device (phone/laptop), roles and languages.
- **Faults.**
  - Breaker trips; device dead; switch port failure; PoE budget exceeded; AP dead; AP 5 GHz radio fault; fibre cut; DHCP exhaustion (time-dependent: new devices fail); DNS down; auth down; ISP/gateway down.
  - Unmodelled faults (truth only), e.g., an AP reboot loop with cycling LEDs.
  - Map drift.
  - Mid-run changes, either a self-recovery or someone resetting something.
- **Participant views.** A deterministic function `view(truth, participant, location, device)` of what the person can perceive:
  - Wi-Fi list; connect status text; "open bookmark: campus page" and "open bookmark: IP test page" results;
  - lights; fans; lift;
  - LEDs and screens in a closet *only if present*;
  - breaker states *only for* an electrician at the distribution board;
  - **presence tokens** (label suffixes) at closets.
  Views are rendered in the participant app, which is clearly marked "Simulation".
- **Actions.**
  - Move (with walking time); look; open bookmark.
  - Interventions with capability token: reset breaker, swap port, power-cycle device.
- **Scenarios.**
  - Generator with seeds: fault-set prior, participant mix, noise profiles, unavailability events, change events.
  - Sealed commitment hash.
  - A curated set S1–S8 (`docs/EVALUATION.md`).
- **Determinism.** Same seed + same answers → same truth evolution.

---

## 24. Data entities and state models

Key entities (full DDL in PLAN.md §7):

| Entity | Key fields |
|---|---|
| DomainPack | components, failure_modes, dependencies, locations (+walk graph), probes (outcomes, classes, preconditions, variants, costs, templates), actions (type, roles, risk, reversible), decision_classes, loss_matrix, priors, presence_tokens |
| Participant | id, display_name (synthetic), roles, permissions, languages {stt_candidates[], tts_lang, format}, skill, location, availability, consent_state, question_budget, reliability_priors |
| Investigation | id, site, status, reporter, created_at, decision, abstention, verification, sealed_commitment |
| Observation | id, inv_id, participant_id, probe_id, location_id, outcome, alt_outcome, hedge, directness, modality, observed_at, committed_at, call_id, turn_id, weight_terms, state |
| Claim / Challenge | id, participant_id, kind, content, verified?, challenge_token_id, result |
| Call / Turn | call: id, participant, state, language, started/ended; turn: speaker, text, lang, stt_segment_ids, timings, latency |
| PlanDecision | ts, candidates[{action, eig_d, eig_h, cost, score, feasible, reasons}], chosen[], stop_rule_state |
| ApprovalRequest / Capability | action, target, requested_by, approver_role, status, token(jti, exp, scope, sig) |
| Event (append-only) | seq, inv_id, type, payload JSONB, causation_id, correlation_id, ts |

**Investigation state machine:** `INTAKE → INVESTIGATING ⇄ AWAITING_APPROVAL → ACTING → VERIFYING → RESOLVED | REOPENED → INVESTIGATING`; plus `ABSTAINED`, `CLOSED_NO_ACTION`, `FAILED`.

---

## 25. Functional requirements

| ID | Requirement | Pri |
|---|---|---|
| FR-01 | Load and validate a domain pack; show validation errors | P0 |
| FR-02 | Create an investigation from a voice or text report | P0 |
| FR-03 | Map reports to initial observations (A1) | P0 |
| FR-04 | Maintain an exact posterior over H with reliability integrated out | P0 |
| FR-05 | Compute and display per-candidate gains, costs and the chosen action(s) | P0 |
| FR-06 | Call participants via browser voice with consent, in their language | P0 |
| FR-07 | Extract typed observations with hedge/directness/extra observations; flag injections | P0 |
| FR-08 | Decide/abstain per the stop rules; show "what would change my mind" | P0 |
| FR-09 | Approval workflow with role checks and capability tokens | P0 |
| FR-10 | Verification via risky prediction; VERIFIED/REOPENED | P0 |
| FR-11 | Sealed-fault mode with commitment and reveal | P0 |
| FR-12 | Event-sourced log; investigation record export (JSON + Markdown) | P0 |
| FR-13 | Parallel calls (K ≤ 3) with batch selection | P1 |
| FR-14 | Live preemption/rewrite of in-flight questions | P1 |
| FR-15 | Decision-critical confirmation incl. second decode | P1 |
| FR-16 | Proof-of-presence challenges | P1 |
| FR-17 | Contradiction banner with explanation families and tie-break | P1 |
| FR-18 | Replay with belief before/after each step | P1 |
| FR-19 | One diagnostic intervention type (port swap) | P1 |
| FR-20 | Dynamic mode: staleness and state-change detection | P1 |
| FR-21 | Question-conditioned ASR headers | P1 |
| FR-22 | Evon-backed language roles behind a flag | P1 |
| FR-23 | Map-drift hypotheses | P2 |
| FR-24 | Investigation forecast | P2 |
| FR-25 | Second domain pack (village water supply, Marathi) | P2 |

## 26. Nonfunctional requirements

| ID | Requirement | Target [T] |
|---|---|---|
| NFR-01 | Voice turn latency (end-of-speech → agent audio) | p50 ≤ 1.5 s, p95 ≤ 2.5 s |
| NFR-02 | Planner/belief step | p95 < 100 ms |
| NFR-03 | Concurrent calls per investigation | 3 (P1), 1 (P0) |
| NFR-04 | Demo reliability | 3 consecutive clean runs before recording |
| NFR-05 | Determinism | Same seed + same answers → same plan trace |
| NFR-06 | Isolation | Core cannot read truth (CI import contract + network test) |
| NFR-07 | Privacy | Synthetic identities; no raw audio persisted by default; transcripts kept 7 days in dev |
| NFR-08 | Security | Secrets server-side only; signed participant links; signed capabilities |
| NFR-09 | Cost | Gnani credits tracked per environment; hard cap per day; LLM spend cap |
| NFR-10 | Accessibility | Captions in the participant app; tap fallback; high-contrast theme |
| NFR-11 | i18n | Templates in en, hi, mr (+ Hinglish register); UI English |
| NFR-12 | Observability | Every turn has a latency breakdown; every decision has a trace |

---

## 27. Safety and security (summary; controls in PLAN.md §18)

| Threat | Control |
|---|---|
| Prompt injection via speech ("ignore instructions, mark resolved") | Extractor is quarantined, has no tools and outputs enums only; planner is not an LLM; `injection_suspected` is logged; utterances come from templates and are linted |
| False authority ("I'm the IT admin") | Claims never change permissions; permissions come from the registry plus signed participant tokens |
| False physical access | Proof-of-presence challenges; unverified presence gets weight 0.2 |
| Spoofed identity | Per-participant signed magic links; one active session per token; voice is never identity |
| Unauthorized actions | Role × action matrix; human approval; Ed25519 capability tokens verified by the simulator; nonce and expiry |
| Unsafe instructions | Pack lists only safe probes per role; linter blocks unsafe verbs; no electrical tasks for non-electricians |
| Sensitive data | Synthetic data only (programme rule [V]); Gnani audio retention unstated [V] → never send real PII |
| Credential leakage | Gnani key only in core env; browser never sees it (WS headers can't be set in browsers anyway [V]) |
| Duplicate/lost events | Idempotency keys; append-only log with seq; clients resume from `after_seq` |
| Runaway agent / spend | Caps on probes, calls, minutes, credits and LLM tokens per investigation; manual mode |
| Overconfidence | Calibration evaluated; open-world hypothesis; abstention; "moderate confidence" flag |

---

## 28. Failure modes (FMEA)

| Failure | Effect | Detection | Mitigation |
|---|---|---|---|
| STT mishears a short answer | Wrong evidence | Second decode disagreement; surprise spike | Decision-critical confirmation |
| Participant misreads an LED | Wrong evidence | Inconsistency with physics; reliability falls | Reliability integration; tie-break probe |
| Extractor misparses | Wrong evidence | Schema/enum checks; `unknown` | Re-ask with another variant |
| Model misspecification (unmodelled fault) | Wrong diagnosis | `P(OPEN_WORLD)` rises; low marginal likelihood | Abstain with "doesn't fit known causes" + recommended checks |
| Participant drops/declines | Lost probe | WebSocket close / "later" | Re-plan without them |
| Concurrency cap | Calls fail | 429 / rejection message | Sequential or multiplexer fallback |
| Credit exhaustion | Voice stops | 402 [V] | Credit meter; reserve; text mode for evaluation |
| Approval denied | No action | Event | Close with decision recorded |
| Wrong repair | Symptoms persist | Verification fails | Reopen |
| World changes mid-run | Apparent contradiction | Surprise + staleness | Refresh probe (dynamic mode) |
| Core restart | Lost in-memory state | Supervisor | Rebuild from event log; mark calls interrupted |

---

## 29. Evaluation methodology (summary; full spec in `docs/EVALUATION.md`)

- **Three levels:**
  - *Logic level*: structured answers from simulated participants with configured noise; thousands of runs; no voice cost.
  - *Language level*: LLM-written utterances with hedges and code-mixing, parsed by our extractor.
  - *Audio level*: small N; recorded volunteer audio plus 8 kHz/noise augmentation; internal only, per the EULA.
- **Policies, all on the same action menu and the same simulated answers:**
  - A: fixed checklist;
  - B: frontier LLM as the policy (sees topology, history and the feasible-action menu; chooses action or conclude + confidence);
  - C: random feasible;
  - D: greedy hypothesis-entropy (no cost, no decision focus);
  - **E: ours**;
  - O: oracle (minimal verifying probe set, knowing the truth; a bound).
- **Metrics:** decision accuracy (top-1, top-3); probes; people contacted; simulated time; cost; bits per probe; false-confidence rate (confidence ≥ 0.9 and wrong); abstention precision/recall; calibration (ECE, reliability diagram); robustness curves (observer reliability, adversary, unavailability, change); verification catch rate; live-run latency.
- **Ablations:** − reliability integration; − decision focus; − cost; − batching; − confirmation; − question-conditioned ASR (internal); − presence challenges; − verification.
- **Falsification:** the thesis is **falsified for this domain** if, on ≥ 300 paired scenarios, ours does not beat B on probes at equal accuracy *and* on false-confidence rate (95% bootstrap CI excludes 0). It is also falsified if accuracy collapses (> 20 points) at mean reliability 0.85. Either result will be reported if it happens.

## 30. Product acceptance criteria (submission gate)

1. A sealed-fault S1 voice run with 3 real people succeeds end-to-end, including approval, verification and reveal, 3 times in a row on the deployed staging environment.
2. The benchmark report is generated from frozen code with the stated policies and seeds. All numbers in public posts are copied from it.
3. The isolation test passes. Injection tests pass. The role × action matrix tests pass.
4. The 60-second video shows real interactions. Every time compression is labelled. The simulation is labelled.
5. The README states clearly what is simulated and what is real, and which Gnani models are used and how.

## 31. UX architecture

- **Identity.** "Field notebook meets mission control":
  - calm off-white "paper" or deep-ink dark theme;
  - one accent (indigo) for *agent intent*; amber = uncertainty/contradiction; green = verified; red = fault likelihood;
  - Geist/Inter for text and Geist Mono for numbers and IDs;
  - no gradient cards; motion only to show causation (evidence → bar movement).
- **Console layout (desktop).** This is an illustrative layout. Every number in it is a placeholder, not a result.

  ```
  ┌ Site: Hostel Block C (sim) ── Sealed #a91f… ── Status: INVESTIGATING ── 02:14 ┐
  │ BUILDING (floor stack, tinted by P(affected))   │ BELIEF                       │
  │  F3 ▓▓▓  AP-3A ○  AP-3B ○   Riya ◉(call)        │ Decision: Electrician→DB-C2  │
  │  F2 ▓▓   IDF-2 ▣ Mahesh ◉(walking 0:40)         │ ███████████░ 86%             │
  │  F1 ░    IDF-1 ▣                                 │ Breaker C2-7 trip   ████ 71% │
  │  power ─ ─ network ── (toggle edges)             │ SW-C2 dead          ██ 18%   │
  │                                                  │ AP-3A+3B dead       ▏ 2%     │
  │                                                  │ Unknown cause       ▏ 1%     │
  │                                                  │ H = 1.42 bits  ▼0.71 last    │
  ├ CONVERSATIONS ───────────────────────────────────┼ WHY THIS QUESTION? ─────────┤
  │ Mahesh (mr) ● listening "सगळे दिवे बंद आहेत"     │ Ask Mahesh: CCTV screen?     │
  │   gloss: "all the lights are off"                │ If ON  → SW-C2 dead 81%      │
  │ Riya (hi-en) ✓ done  "network hi nahi dikh raha" │ If OFF → Breaker C2-7 93%    │
  ├ LEDGER ──────────────────────────────────────────┴──────────────────────────────┤
  │ 02:01 Riya @F3 wifi_visible=NO direct·certain  w=1.0  consistency 0.97          │
  │ 02:09 Mahesh @IDF-2 switch_leds=NONE direct·certain presence✓  ΔH −0.71 bits    │
  └──────────────────────────────────────────────────────────────────────────────────┘
  ```
- **Participant app (phone-first):** incoming-call screen in their language; consent; big captions; a mic-state ring; a "Your surroundings (simulation)" card with the view and allowed actions; a "Later" button; a closing screen with "how you helped".
- **Uncertainty representation:** bars plus explicit numbers, an entropy in bits with its change per probe, "moderate confidence" badges, and the "Unknown cause" row always visible.
- **Evidence provenance:** chips show who / where / when / direct-hearsay / hedge / presence-verified / second-decode-agreed / weight.
- **Replay:** a timeline scrubber; at each step, belief before → after, plus the plan trace.
- **Onboarding:** an empty state explains the simulation; a "Run demo scenario" button; QR invites; a mic self-test.

## 32. Demonstration requirements (full storyboard in `docs/DEMO.md`)

- 60 s, captions burned in (social video autoplays muted), real voices and real-time reasoning, labelled time compression, sealed fault revealed.
- Must show:
  - a live spoken report;
  - the AI choosing an unexpected but explained observation (CCTV);
  - a meaningful answer;
  - replanning;
  - approval;
  - verification by risky prediction;
  - the reveal;
  - one line on why this is not a normal voice agent.
- A long version (3 min) shows parallel preemption, a contradiction, a presence challenge and abstention.

## 33. Success metrics

| Horizon | Metric | Target [T] |
|---|---|---|
| Submission | P0 + P1a shipped; acceptance §30 met | 100% |
| Submission | Benchmark: ours vs B and A (accuracy, probes, false confidence) | Report whatever we measure; targets in C1 |
| Public | Nominated posts: genuine comments with technical questions | ≥ 30 substantive comments (no pods/swaps) |
| Interviews | Each member can explain the whole system and defend decisions | Both pass a mock interview on Nov 9 |
| Product (post-hackathon) | Pilot with one campus IT/facilities team (consented, real) | Time-to-diagnose vs their baseline |

## 34. Technical feasibility risks

| Risk | Likelihood | Impact | Early test |
|---|---|---|---|
| Gnani concurrency cap (the docs example says "Only 1 active request is allowed at a time" [V]) | Medium-High | High for C3 | Initial spike: open 1→4 STT sessions; 1→3 TTS |
| Credits insufficient (no conversion published [V]) | Medium | High | Initial metering |
| Short-answer recognition in Marathi/Hinglish | Medium | High | Initial test with 20 short answers; tune `x-min-segment-ms`, keyterms |
| Timbre Hinglish quality (`hi-en` only in v2.5 [V]) | Medium | Medium | Listening test v3.0 vs v2.5 Poorvi |
| LLM extraction latency | Medium | Medium | Initial latency test per model |
| Evon hosting (64 GB BF16 class; GPU rental) | High | Low (P1) | Gate on Nov 6 noon |
| Browser echo/barge-in | Medium | Medium | Headphones for demo; echo gate |
| Simulator too simple → "toy" criticism | Medium | Medium | Open-world, map drift, changing world scenarios; honest framing |

## 35. Commercial viability hypotheses

- **H1 (wedge).** Indian campuses with hostels, hospitals and IT parks have frequent multi-location outages, little instrumentation, multilingual night staff, and coordinate by WhatsApp and phone. *Test:* 5 interviews; shadow one night shift.
- **H2 (value).** Fewer wrong dispatches and faster diagnosis are worth ₹X per site per month. *Test:* willingness-to-pay interview; pilot metrics.
- **H3 (adoption).** Staff will answer short AI calls in their language if calls are rare, polite and useful. *Test:* opt-in pilot response rate.
- **H4 (expansion).** The same engine transfers to retail chains, ISP last-mile and utilities, where "active trouble-call analysis" upgrades a passive practice used for decades. *Test:* a second pack built in ≤ 1 day.
- **H5 (defensibility).** Domain packs, calibrated observer priors (consented), and multilingual field-voice UX compound. *Risk:* incumbents (ServiceNow, PagerDuty) add outreach calls. Our edge is the inference engine and Indian-language field operations.
- **Falsifiers.**
  - Managers prefer WhatsApp polls (cheap and familiar).
  - Staff ignore AI calls.
  - Cheap sensors saturate the market.
  - Legal or HR objections to calling staff.

## 36. Honest novelty assessment

- **Not new:**
  - EIG test selection (1987);
  - decision-theoretic troubleshooting (1990s);
  - noisy-test active learning (2010);
  - truth discovery (1979, 2012–13);
  - contextual ASR biasing;
  - authorization gates;
  - LLM question-asking with EIG (2024–26).
- **New as a combination and setting [I]:** the five-part combination in §9, applied to multilingual voice coordination of physically distributed humans, with in-incident reliability inference and risky-prediction closure.
- **Unproven [H]:**
  - that it beats a frontier LLM policy in realistic noise;
  - that real staff tolerate the calls;
  - that site models can be authored cheaply.
- **Where we may be wrong:**
  - In real sites, model misspecification may dominate, so the open-world rate is high.
  - Humans may not follow walking requests.
  - A strong LLM might match our planner on small sites. If so, the benchmark will say so and we will report it.

## 37. Future research opportunities

- Open-world hypothesis induction: the LLM proposes failure modes with explicit predicted symptoms; a compiler validates them.
- Learning priors and observer error models across incidents (consented), with fairness constraints.
- Non-myopic planning (POMDP rollouts; adaptive-submodular guarantees with reliability coupling).
- Conformal calibration of decisions (KnowNo-style guarantees).
- Map learning: topology inference from testimony (tomography with humans as probes).
- Telephony at 8 kHz and WhatsApp voice notes as channels.
- Multi-incident disentanglement.
- A public benchmark ("FaultHunt") exposed via an MCP server so any agent can be evaluated on the same probe interface.

## 38. Explicit non-goals (v1)

- No real PSTN calls, real phone numbers or real facility deployment.
- No autonomous physical actions; humans perform all actions after approval.
- No general chatbot or FAQ.
- No telemetry ingestion beyond an optional simulated machine probe.
- No voice cloning.
- No knowledge graph database, vector DB, RAG, blockchain or LangGraph (no need identified).
- No fine-tuning.
- No claims of production readiness or real-world accuracy.

## 39. Open questions

1. Gnani realtime concurrency and credits-per-minute on the programme account. *(Owner: Darshan, Nov 4)*
2. Does Timbre v3.0 render Hinglish (Latin-script Hindi mixed with English) acceptably, or do we use v2.5 Poorvi? *(Darshan + volunteers, Nov 4–5)*
3. Which LLM meets the extraction latency budget: Opus 5.5 at low effort, Haiku 5.5, or Evon? *(Nikhil, Nov 5)*
4. Can we rent a GPU for Evon within budget? *(Darshan + Nikhil, Nov 6 noon gate)*
5. Can we publish any voice-pipeline numbers? *(Ask on Gnani Discord, Nov 5)*
6. Which teammate's account posts the nominated LinkedIn and X posts? Prefer the larger relevant network; the other reshares. *(Both, Nov 7)*
7. Volunteers: confirm 2–3 native Marathi/Hindi speakers for Nov 8 recording. *(Both, Nov 5)*

## 40. Sources and references

All links were accessed 2026-11-04. Full annotated list and search log: `docs/RESEARCH.md`.

- **Programme:** [gnani.ai/internship](https://www.gnani.ai/internship) · [registration & terms](https://www.gnani.ai/great-indian-ai-internship-registration-form) · [EULA](https://www.gnani.ai/legal/eula)
- **Gnani docs:** [llms.txt](https://docs.gnani.ai/llms.txt) · [Prisma v3](https://docs.gnani.ai/api/STT/models/prisma-v3.md) · [STT realtime](https://docs.gnani.ai/api/STT/stt-websocket.md) · [STT limits](https://docs.gnani.ai/api/STT/limits.md) · [errors](https://docs.gnani.ai/api/introduction/errors.md) · [changelog](https://docs.gnani.ai/api/introduction/changelog.md) · [TTS voices](https://docs.gnani.ai/api/TTS/available-voices.md) · [TTS realtime](https://docs.gnani.ai/api/TTS/tts-websocket.md) · [TTS normalization](https://docs.gnani.ai/api/TTS/tts-input-formating.md) · [LiveKit plugin](https://docs.gnani.ai/livekit/introduction.md) · [Pipecat plugin](https://docs.gnani.ai/pipecat/introduction.md) · [Python SDK](https://docs.gnani.ai/python-sdk/introduction.md) · [Evon v3.3 model card](https://huggingface.co/gnani/gnani-evon-v3.3-30B-A3B) · [models page](https://www.gnani.ai/models)
- **Competitors:** see `docs/COMPETITORS.md`
- **Research:** see §10 and `docs/RESEARCH.md`
