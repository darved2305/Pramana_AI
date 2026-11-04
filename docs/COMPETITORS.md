# COMPETITORS.md — Direct and adjacent competitors, gaps, honest novelty

Sources were accessed on 2026-11-04. Labels used throughout:

- **[V]** verified on the company's own page or a primary source
- **[C]** the company's own claim
- **[S]** secondary or aggregator source

We describe what each product **does**, not its marketing tagline. "Not stated" means we found nothing either way; it does not mean the product lacks the feature.

---

## 1. The 12-question analysis for the most relevant competitors

The twelve questions:

1. Product today
2. Customer
3. Workflow
4. Autonomy
5. Information sources
6. Chooses new observations?
7. Multiple humans?
8. Updates hypotheses dynamically?
9. Real-time voice?
10. Verification method
11. Apparent limitations
12. What we do materially differently

### 1.1 Astyr — [astyr.app/product](https://astyr.app/product), [/company](https://astyr.app/company)

1. **Product today.** "Intelligence for complex physical systems". A control room plus agents that go "from the alarm to a cited, verified fix" [C]. The site says it is pre-revenue and entering a design-partner phase [C].
2. **Customer.** First target is automotive Tier-1 plants in France. Buyer: reliability and maintenance manager. KPI: mean-time-to-diagnose [C].
3. **Workflow** [C]:
   1. A Watchdog monitors live feeds.
   2. An orchestrator routes the problem to specialist agents (correlation, root cause, responder matching, validation, remediation, cost/inventory/dispatch).
   3. Root cause "refuses to guess" when below a confidence threshold, and re-retrieves past breakdowns.
   4. Responder matching "picks ONE tech".
   5. A push notification goes to that technician's phone, and the technician returns a verdict.
   6. A refusal "pivots back to re-diagnose".
4. **Autonomy.** "It augments. It decides nothing physical." [C]
5. **Information sources.** Live telemetry and alarm storms, network topology, schematics/P&IDs, manuals, past breakdowns, safety procedures, spare-parts catalogs [C].
6. **Chooses new observations?** Partly: "hands the operator a hypothesis and a safe test" [C]. No information-gain or cost-based selection is described.
7. **Multiple humans?** No. One technician; one operator loop.
8. **Dynamic hypotheses?** Yes, with a confidence gate and re-diagnosis on refusal [C]. The method is not stated (no Bayesian or information-gain language).
9. **Voice?** Not stated. A native iOS operator app [C].
10. **Verification.** A human field verdict gates any prescription [C].
11. **Apparent limitations.** Requires telemetry and documentation. Single technician. No reliability modelling stated. Sold as an augmentation tool.
12. **Our difference.**
    - Works where no telemetry exists.
    - Routes observations across *several* people with different access and permissions.
    - Models each observer's reliability.
    - Voice in Indian languages.
    - Selects verification tests by how well they discriminate, rather than relying on a verdict.

> Context: Astyr reports wins at Anthropic's "Built with Opus 2026" and a podium at RAISE Summit (Vultr track) [C]. Judges may know it. **Do not describe Pramana as "the first AI that asks humans to run diagnostic tests."**

### 1.2 Quintess — [quintess.ai](https://www.quintess.ai/), [fleet page](https://www.quintess.ai/fleet-maintenance-troubleshooting)

1. **Product today.** "A voice-first AI troubleshooting agent that helps fleet and field maintenance technicians diagnose difficult equipment faults" [C]. "Live with fleet and field maintenance teams in the US and Europe" [C].
2. **Customer.** Technicians, maintenance managers and subject-matter experts in rail, bus and industrial operations [C].
3. **Workflow** [C]:
   1. The technician describes the fault by voice.
   2. Quintess asks follow-up questions and pulls manuals, schematics, work orders and fault history.
   3. It ranks causes and has the technician "run the cheapest checks first", comparing readings to tolerances.
   4. Confirmed fixes become knowledge.
   5. When confidence is low, it escalates to an expert.
4. **Autonomy.** Advisory. "Your technician leads the diagnosis." [C]
5. **Information sources.** Approved manuals, schematics, parts catalogs, fault-isolation procedures, EAM/CMMS history, technician readings, expert knowledge [C].
6. **Chooses new observations?** Yes. It "suggests the next check" and orders checks cheapest-first [C]. The method is not stated.
7. **Multiple humans?** Across time (shift handover, expert escalation, role-based permissions). Not multiple people at once [C].
8. **Dynamic hypotheses?** "Probable causes are ranked against the evidence" [C].
9. **Voice?** Yes, voice-first, hands-free [C]. Languages not stated.
10. **Verification.** "Your maintenance process governs review, repair verification, and return to service." [C]
11. **Apparent limitations.**
    - Assumes the right expert is already at the equipment.
    - Single respondent per session.
    - No observer-reliability model stated.
    - Verification is outsourced to the customer's own process.
12. **Our difference.**
    - Recruits whoever happens to be present (lay people, guards, technicians).
    - Runs several conversations in parallel.
    - Joint fault × reliability inference.
    - Decision-focused stopping.
    - Its own risky-prediction verification.
    - Indian-language code-mixing.

### 1.3 PagerDuty SRE Agent — [Spring '26 blog](https://www.pagerduty.com/blog/product/the-path-to-autonomous-operations-pagerduty-spring-26-release/), [Oct 2025 release](https://www.businesswire.com/news/home/20251008279706/en/)

1–3. A "virtual responder" that sits in on-call schedules. It detects anomalies (AIOps), assesses the stack, and runs diagnostics before paging a human. It learns from related incidents and recommends or runs remediations. Customers are software and ops teams [C].

4. **Autonomy.** Early access for "virtual responder"; a "fully autonomous responder" is planned [S/C].
5. **Information sources.** Telemetry and incident history [C].
6. **Chooses new observations?** Over systems, not people.
7. **Multiple humans?** It coordinates with humans in Slack/Teams. Agent-to-agent via MCP is planned [C].
8. **Dynamic hypotheses?** Implied.
9. **Voice?** No.
10. **Verification.** System signals.
11. **Limitations.** Digital-only.
12. **Our difference.** Physical-world evidence gathered from people. Complementary: a PagerDuty incident could trigger Pramana for a physical site.

### 1.4 AI SRE startups — Resolve AI, Traversal, Cleric, Causely

- **Resolve AI** reached a $1B valuation in its Series A (Dec 2025), with a reported $125M raise ([TechCrunch](https://techcrunch.com/2026/02/04/ai-sre-resolve-ai-confirms-125m-raise-unicorn-valuation/)) [V/S]. It runs autonomous investigation over production telemetry. In May 2026 it announced a new architecture that it says "roughly doubles root-cause accuracy" [C].
- **Traversal** raised a $48M Series A led by Kleiner Perkins, with Sequoia participating [S]. A Fortune 100 case study claims 82% RCA accuracy [C].
- **Cleric** is "read-only by design" per a comparison site [S].
- **Causely** raised an $8.8M seed in 2023 led by 645 Ventures ([BusinessWire](https://www.businesswire.com/news/home/20230629773124/en/)). It builds structured causal models of Kubernetes environments for root cause [C]. Its internals are not public. It is the closest in *method* (causal models), but works over telemetry only.

All four need telemetry, and none coordinates humans as sensors. They show investor appetite for "AI investigation" and set the bar for "causal" language. Our evaluation must be at least as honest as their case studies; most of theirs are vendor claims.

### 1.5 Utility Outage Management Systems: trouble-call analysis (TCA)

- **Product.** OMS prediction engines (e.g., [ETAP](https://etap.com/de/product/outage-analysis); patents such as [US5568399](https://patents.google.com/patent/US5568399)). They combine customer calls with network topology and protective-device schema to infer which device operated. Confidence rises with call volume, and heuristics such as "two customers on the same transformer" are used [V]. Modern versions add SCADA and AMI meter data [C].
- **Questions 6–9.** It does not choose whom to call (passive). It aggregates many humans, but passively. Hypotheses update with every call. Voice is limited to IVR.
- **Our difference.** *Active* trouble-call analysis: choosing who to ask what, with reliability inference and dialogue. **This is also our strongest commercial validation:** decades of utility investment show that human reports combined with topology inference are valuable.

### 1.6 Agent→human marketplaces — RentAHuman, Humwork

- **RentAHuman** launched Feb 2026 ([India TV](https://www.indiatvnews.com/technology/news/rentahuman-ai-lets-ai-agents-hire-humans-for-real-world-tasks-2026-02-05-1028987)) [S]. AI agents book and pay humans for physical tasks (deliveries, errands) via REST or MCP, paid in stablecoins. User and task counts are self-reported and inconsistent [S].
- **Humwork** is in YC's Spring 2026 batch ([YC](https://ycombinator.com/companies/humwork)). It is an "agent-to-person" marketplace where agents escalate to verified human experts via MCP [S].
- **Questions 6–12.** These systems decide *to involve a human* but do not decide which observation is most informative. Neither is diagnostic, has a reliability model, or uses voice. **Our difference:** we treat humans as calibrated sensors inside an inference loop, not as task labour or expert oracles.

### 1.7 Crowdsourced ground truth — Premise

Premise ([brochure](https://premise.com/wp-content/uploads/2019/11/WhyPremiseBrochure_2019.pdf), [StateScoop](https://statescoop.com/under-new-ceo-premise-brings-crowdsourced-research-to-government/)) runs a task marketplace of surveys, place visits and route walks. Contributors are paid per verified task, with ML quality control [C]. Customers include governments and NGOs. It has been criticized over the background data it collects [S].

It neither diagnoses nor runs adaptive, investigation-driven task design. **Our difference:** tasks are generated by the value of information for one live incident, and reliability is inferred from causal consistency.

### 1.8 Sensor alternative — HPE Aruba UXI ([HPE](https://www.hpe.com/int/en/products/networking/user-experience-insight.html))

Physical sensors and software agents run synthetic "end-user" tests in round-robin. Cellular sensors keep working when the Wi-Fi itself is down [C].

**This is the "just buy sensors" answer.** It costs hardware and a subscription per location, covers only network experience, and cannot see that the closet breaker tripped. **Our position:** a sensor is simply a highly reliable participant in our model (PLAN §9). Pramana covers the gaps between sensors and the sites that have none.

### 1.9 Technician voice copilots — Aquant ("Roger"), NOSO Labs, ECI GlobalEdge

- **Aquant**: a voice agent technicians call for guidance, piloted with Comfort Systems USA ([Aquant](https://www.aquant.ai/resources/post/comfort-systems-usa-is-redefining-service-with-voice-ai)) [C]. Aquant also publishes field-service benchmarks, e.g., "14% of truck rolls are unnecessary" ([Aquant](https://www.aquant.ai/resources/post/2025-service-benchmark-report-insights)) [C].
- **NOSO Labs** (YC S25): AI agents for home-services technicians ([YC](https://ycombinator.com/companies/noso-labs)) [S].
- **ECI GlobalEdge**: one-tap AI troubleshooting recommendations [S].

All three serve a single, already-dispatched technician. **Our difference:** we decide *whether, whom and where* to dispatch, using the people already on site.

### 1.10 Remote visual support — TechSee, CareAR, Blitzz, Help Lightning

A video session in which an expert or AI sees through the user's camera, with the aim of avoiding truck rolls ([CareAR](https://carear.com/blog/what-is-a-truck-roll-how-to-reduce-them)) [C]. It is one-to-one, expert-driven and visual. Vision would complement Pramana as a future observation modality ("show me the switch"). It is not what we compete on.

### 1.11 Voice operations at scale — HappyRobot; voice intake — SkipCalls, Octonomy, CallSphere

- **HappyRobot**: $15.6M Series A led by a16z in Dec 2024 ([HappyRobot](https://happyrobot.ai/post/series-a-announcement)) [V]. AI voice agents make inbound and outbound logistics calls (check calls, load updates, negotiations) [C]. This proves that many-call voice operations sell. It has no diagnostic inference.
- **SkipCalls**: after-hours MSP call routing with configurable diagnostic questions, summarized for the technician ([SkipCalls](https://skipcalls.com/it-company/does-skipcalls-work-for-msps-can-it-route-urgent-after-hours-outage-calls-server)) [C].
- **Octonomy**: a voice agent for technical hotlines that pre-qualifies tickets ([computer-automation.de](https://www.computer-automation.de/operate---monitor/octonomy---ai-voice-agent--for-technical-hotlines.htm)) [S].

None of these chooses observations across several people.

### 1.12 Microsoft Research systems — RCACopilot, Triangle, AIOpsLab, OpenRCA

These are digital incident-management research systems:

- RCA via engineered handlers (RCACopilot)
- multi-agent triage (Triangle; [GitHub](https://github.com/microsoft/Triangle))
- a fault-injection benchmark framework ([AIOpsLab](https://www.microsoft.com/en-us/research/publication/aiopslab-a-holistic-framework-for-evaluating-ai-agents-for-enabling-autonomous-cloud))
- a hard RCA benchmark ([OpenRCA](https://microsoft.github.io/OpenRCA): best 11.34%)

**What we borrow:** AIOpsLab's fault-injection plus agent-interface design for our simulator. **What differs:** our sensors are people.

### 1.13 Gnani's own Inya / Agent Builder

Gnani's platform for building enterprise voice agents for conversation automation. It is **out of scope for the programme** [V]. It is a voice-agent builder; it does not include an investigation engine. Pramana runs on Gnani's speech models, which shows them working in a way the Gnani team may not have tried before. That fits the Jugaad Genius award.

---

## 2. Feature comparison matrix

| Capability | Astyr | Quintess | PagerDuty / AI SRE | Utility OMS TCA | RentAHuman / Humwork | Aruba UXI | Tech copilots | **Pramana** |
|---|---|---|---|---|---|---|---|---|
| Works without telemetry | ✗ | ✓ (docs + readings) | ✗ | Partly | n/a | ✗ (is telemetry) | ✓ | **✓** |
| Selects the next observation | Partly (one safe test) | ✓ (cheapest first) | Over systems | ✗ | ✗ | ✗ | Partly | **✓ VOI per cost** |
| Selects *who* observes | One technician | ✗ | ✗ | ✗ | Marketplace match | ✗ | ✗ | **✓ routing by access, location, language, fatigue** |
| Parallel humans | ✗ | ✗ | ✗ | Passive many | ✗ | ✗ | ✗ | **✓ with live preemption (P1)** |
| Observer reliability model | Not stated | Not stated | n/a | Heuristics | Not stated | n/a | Not stated | **✓ joint Bayesian** |
| Contradiction handling | Not stated | Not stated | — | Volume | — | — | — | **✓ reconciliation + tie-break** |
| Decision-focused stopping | Confidence gate | Not stated | — | — | — | — | — | **✓ EVOI + decision classes** |
| Honest abstention | "Refuses to guess" | Escalates | — | — | — | — | — | **✓ with "what it would take"** |
| Voice, Indian code-mixed | ✗ | Voice (language n/s) | ✗ | IVR | ✗ | ✗ | Voice | **✓ Prisma v3.0 / Timbre** |
| Verification | Field verdict | Customer process | System signals | Restoration calls | — | Continuous tests | — | **✓ held-out risky prediction** |
| Authorization of actions | "Decides nothing physical" | Customer process | Runbooks | Utility process | — | — | — | **✓ role matrix + signed capability** |

---

## 3. Honest novelty assessment

- **Not novel by itself:**
  - asking a human to run a check (Astyr, Quintess, decades of SOPs)
  - EIG question selection (GDE in 1987; UoT/BED-LLM in 2024–26)
  - observer reliability (Dawid–Skene in 1979; Wang et al. in 2012–13)
  - humans plus topology inference (utility OMS)
  - voice agents
  - authorization gates
- **Plausibly novel as a combination** [I]: we found no product or paper that combines all of these:
  - active, decision-focused selection across *multiple co-present humans*
  - parallel isolated voice calls synchronized by one belief, with preemption
  - per-incident joint fault × reliability inference from causal consistency
  - speech-uncertainty-aware confirmation
  - held-out risky-prediction verification
- **Claims we will NOT make:**
  - "first"
  - "world-first"
  - "replaces technicians"
  - "works on real buildings"
  - any accuracy figure that is not from our own benchmark report
  - any Gnani-model benchmark figure (EULA)

---

## 4. Investor landscape: what is verified vs. not

| Investor | Relevant verified activity | Thesis relevance | Status |
|---|---|---|---|
| a16z | Led HappyRobot's Series A (voice agents for logistics calls) [V]. "Big Ideas 2026" episodes cover physical AI, "physical observability" and voice agents moving into production ([podcast](https://a16z.simplecast.com/episodes/big-ideas-2026-physical-ai-and-the-industrial-stack-_jUvmWaM), [Part 2](https://www.a16z.news/p/big-ideas-2026-part-2)) [S summaries] | "Physical observability without sensors: people as the sensor network" | Partly verified |
| Y Combinator | Humwork (Spring 2026), NOSO Labs (S25) [S]. Current RFS (Winter 2027) includes "The $15-an-Hour Expert", "AI for City Hall" (311, inspections), "AI for the Air-Gapped Economy", "Own Your Intelligence" ([RFS](https://www.ycombinator.com/rfs)) [V] | AI lets non-experts produce expert-grade observations; self-hostable models (Evon) | Verified |
| Kleiner Perkins, Sequoia | Traversal Series A (lead / participant) [S]. Sequoia reportedly led ElevenLabs' Series D (Feb 2026) [S] | AI investigation; voice infrastructure | Secondary only |
| Peak XV | India AI Impact Summit pitchfest: 5 startups, about $13.2M ([Entrepreneur](https://www.entrepreneur.com/en-in/news-and-trends/five-ai-startups-secure-peak-xv-support-to-build/502888)) [S]. Rajan Anandan: AI that "works at population scale". Reportedly led Vapi's round [S] | Population-scale Indian AI; voice | Secondary |
| 645 Ventures | Causely seed [V] | Causal AI for operations | Verified |
| Blume, Lightspeed, General Catalyst, Accel, Khosla, Bessemer, GV, Menlo, Radical, NFX | No primary thesis page read today. A Blume portfolio post on evaluating voice-AI platforms exists [S]. Menlo's 2026 "show me the money" framing [S] | — | **Not verified; no claims made** |

**Implication for the pitch.** Investors already back three adjacent categories:
- AI investigation over telemetry
- voice agents that do operational calling
- physical AI and observability

Pramana's pitch is the intersection of the three: *investigation for the physical world, using voice, where telemetry is absent*. We should not claim any investor endorses this.
