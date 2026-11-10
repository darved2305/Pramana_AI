# COMPETITORS.md - Direct and adjacent competitors, scope, and honest novelty

The original landscape review was accessed on 2026-11-04. Selected vendor pages for PagerDuty,
ServiceNow, and Augury + MaintainX were reviewed on 2026-11-10 and are dated below. This update did
not re-open every source from the original review; existing [V], [C], and [S] labels retain their
original scope and date.

- **[V]** verified on the company's own page or a primary source
- **[C]** the company's own claim
- **[S]** secondary or aggregator source

We describe what a cited source says about each product, not its marketing tagline. "Not described
in public material reviewed" means the sources reviewed here do not establish whether a capability
is available. It does not mean the product lacks it. [C] denotes a vendor claim, not an independent
test.

The Nov 10 pass did not recheck every older startup, utility, marketplace, crowdsourcing, sensor,
voice-agent, remote-support, research, or investor source. Those summaries retain their original
dates and labels; unchanged text is not a current independent verification.

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

### 1.1 Astyr - [astyr.app/product](https://astyr.app/product), [/company](https://astyr.app/company)

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
6. **Chooses new observations?** Partly: "hands the operator a hypothesis and a safe test" [C]. The cited source does not describe an information-gain or cost-based selection method.
7. **Multiple humans?** The cited workflow describes a selected technician returning a verdict.
   Whether several people can participate in one investigation is not described in material
   reviewed for this pass.
8. **Dynamic hypotheses?** Yes, with a confidence gate and re-diagnosis on refusal [C]. The method is not stated (no Bayesian or information-gain language).
9. **Voice?** Not stated. A native iOS operator app [C].
10. **Verification.** A human field verdict gates any prescription [C].
11. **Apparent limitations.** The cited material describes telemetry and documentation inputs and
   a technician verdict. It does not describe multi-person investigation or an observer-reliability
   model. Those capabilities may or may not exist outside the material reviewed. The product is
   presented as an augmentation tool [C].
12. **Our difference.**
    - Our documented design includes a simulated no-telemetry investigation.
    - Our documented design routes observations across several people with different access and
      permissions.
    - Our engine includes observer-reliability inference.
    - Our speech integration includes Hindi, Marathi, and Hinglish routes; human language review
      remains open.
    - Our simulator supports held-out verification after a repair. These are Pramana design
      properties, not claims that Astyr lacks corresponding features.

> Context: Astyr reports wins at Anthropic's "Built with Opus 2026" and a podium at RAISE Summit (Vultr track) [C]. Judges may know it. **Do not describe Pramana as "the first AI that asks humans to run diagnostic tests."**

### 1.2 Quintess - [quintess.ai](https://www.quintess.ai/), [fleet page](https://www.quintess.ai/fleet-maintenance-troubleshooting)

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
7. **Multiple humans?** The cited material describes shift handover, expert escalation, and
   role-based permissions [C]. Whether several people can be interviewed concurrently, or whether
   an observer-reliability model is available, is not described in the material reviewed.
8. **Dynamic hypotheses?** "Probable causes are ranked against the evidence" [C].
9. **Voice?** Yes, voice-first, hands-free [C]. Languages not stated.
10. **Verification.** "Your maintenance process governs review, repair verification, and return to service." [C]
11. **Apparent limitations.** The cited workflow is technician-led, suggests checks, ranks causes,
    and can escalate to an expert [C]. It says the customer's process governs repair verification
    [C]. Concurrent multi-person interviews and observer-reliability modelling are not described
    in the material reviewed; that is an evidence boundary, not a product exclusion.
12. **Our difference.**
    - Our documented target includes participants with different roles and access.
    - Our implementation supports parallel questions.
    - Our engine models fault and observer reliability jointly.
    - Our planner uses a decision-focused stopping rule.
    - Our simulated workflow has a held-out verification step.
    - Our language routes include Hindi, Marathi, and Hinglish, with native review pending.
      These differences describe Pramana; the reviewed Quintess sources do not establish whether
      equivalent capabilities are available there.

### 1.3 PagerDuty Paige and SRE Agent

Sources reviewed 2026-11-10: [Paige virtual responder documentation](https://docs.pagerduty.com/ai-automation/advance/add-paige-as-virtual-responder)
and [PagerDuty's September 16, 2026 product blog](https://www.pagerduty.com/blog/chatops/automate-incident-management-with-pagerduty-slack/).

1–3. PagerDuty's documentation labels Paige virtual responder as Early Access and describes
   investigation using incident history and integrations, with recommended next steps [C]. Its
   product blog describes SRE agent diagnosis and remediation capabilities [C].
4. **Autonomy.** The documented availability is Early Access for Paige virtual responder; the blog
   makes vendor claims about the SRE agent [C].
5. **Information sources.** Incident history and configured integrations are described in Paige's
   documentation [C].
6. **Chooses new observations?** The reviewed pages describe investigation across incident data;
   selection of on-site human observations is not described.
7. **Multiple humans?** Paige can be added as a virtual responder in incident workflows [C]. A
   multi-person physical-site interview is not described in the reviewed pages.
8. **Dynamic hypotheses?** The sources describe investigation and next-step recommendations [C];
   the inference method is not specified in the reviewed pages.
9. **Voice?** The reviewed pages describe Slack and PagerDuty web workflows. Physical-site voice
   interviews are not described in those pages.
10. **Verification.** The reviewed materials describe incident workflow and remediation; the
    criteria for verifying a physical repair are not described.
11. **Evidence boundary.** Do not infer that Paige lacks voice, multi-person, or other capabilities
    from these pages. This review establishes only what the cited materials describe.
12. **Our difference.** Pramana's documented target gathers evidence from people already at a
    physical site. A connection to PagerDuty is a possible complement, not an existing integration.

### 1.4 AI SRE startups - Resolve AI, Traversal, Cleric, Causely

- **Resolve AI** reached a $1B valuation in its Series A (Dec 2025), with a reported $125M raise ([TechCrunch](https://techcrunch.com/2026/02/04/ai-sre-resolve-ai-confirms-125m-raise-unicorn-valuation/)) [V/S]. It runs autonomous investigation over production telemetry. In May 2026 it announced a new architecture that it says "roughly doubles root-cause accuracy" [C].
- **Traversal** raised a $48M Series A led by Kleiner Perkins, with Sequoia participating [S]. A Fortune 100 case study claims 82% RCA accuracy [C].
- **Cleric** is "read-only by design" per a comparison site [S].
- **Causely** raised an $8.8M seed in 2023 led by 645 Ventures ([BusinessWire](https://www.businesswire.com/news/home/20230629773124/en/)). It builds structured causal models of Kubernetes environments for root cause [C]. Its internals are not public. It is the closest in *method* (causal models) among these examples; the cited description centers on Kubernetes environments and does not establish support for non-telemetry observation inputs.

The cited descriptions center on software telemetry and incident investigation. Whether each
product coordinates people as physical sensors is not established by the sources summarized here.
They show investor appetite for "AI investigation" and set the bar for "causal" language. Our
evaluation should remain clear about which results are measured and which are vendor claims.

### 1.5 Utility Outage Management Systems: trouble-call analysis (TCA)

- **Product.** OMS prediction engines (e.g., [ETAP](https://etap.com/de/product/outage-analysis); patents such as [US5568399](https://patents.google.com/patent/US5568399)). They combine customer calls with network topology and protective-device schema to infer which device operated. Confidence rises with call volume, and heuristics such as "two customers on the same transformer" are used [V]. Modern versions add SCADA and AMI meter data [C].
- **Questions 6–9.** The cited descriptions cover call aggregation, topology, and IVR. Active selection of whom to call, an observer-reliability model, and how hypotheses update are not established by the sources summarized here.
- **Our difference.** Pramana's documented design actively selects observations and includes reliability inference. Utility outage workflows are useful adjacent examples of human reports combined with network topology; they are not proof of Pramana's commercial validation.

### 1.6 Agent→human marketplaces - RentAHuman, Humwork

- **RentAHuman** launched Feb 2026 ([India TV](https://www.indiatvnews.com/technology/news/rentahuman-ai-lets-ai-agents-hire-humans-for-real-world-tasks-2026-02-05-1028987)) [S]. AI agents book and pay humans for physical tasks (deliveries, errands) via REST or MCP, paid in stablecoins. User and task counts are self-reported and inconsistent [S].
- **Humwork** is in YC's Spring 2026 batch ([YC](https://ycombinator.com/companies/humwork)). It is an "agent-to-person" marketplace where agents escalate to verified human experts via MCP [S].
- **Questions 6–12.** The cited marketplace descriptions focus on booking physical tasks or escalating to human experts. Whether either product includes diagnostic inference, adaptive observation selection, participant-reliability modelling, or voice is not described in the reviewed sources. **Our design** treats human observations as evidence inside an inference loop.

### 1.7 Crowdsourced ground truth - Premise

Premise ([brochure](https://premise.com/wp-content/uploads/2019/11/WhyPremiseBrochure_2019.pdf), [StateScoop](https://statescoop.com/under-new-ceo-premise-brings-crowdsourced-research-to-government/)) runs a task marketplace of surveys, place visits and route walks. Contributors are paid per verified task, with ML quality control [C]. Customers include governments and NGOs. It has been criticized over the background data it collects [S].

The cited sources describe a task marketplace for surveys and place-based work. Adaptive,
investigation-driven diagnostic task design is not described in those sources. **Our design** uses
value of information to select an observation for a simulated incident and includes reliability
inference.

### 1.8 Sensor alternative - HPE Aruba UXI ([HPE](https://www.hpe.com/int/en/products/networking/user-experience-insight.html))

Physical sensors and software agents run synthetic "end-user" tests in round-robin. Cellular sensors keep working when the Wi-Fi itself is down [C].

This is a sensor-based alternative. The cited HPE page describes monitoring network experience;
its coverage of other physical equipment is not established by that source. **Our design** can
model a sensor as a highly reliable participant (PLAN §9) and includes a simulated site without
telemetry.

### 1.9 Technician voice copilots - Aquant ("Roger"), NOSO Labs, ECI GlobalEdge

- **Aquant**: a voice agent technicians call for guidance, piloted with Comfort Systems USA ([Aquant](https://www.aquant.ai/resources/post/comfort-systems-usa-is-redefining-service-with-voice-ai)) [C]. Aquant also publishes field-service benchmarks, e.g., "14% of truck rolls are unnecessary" ([Aquant](https://www.aquant.ai/resources/post/2025-service-benchmark-report-insights)) [C].
- **NOSO Labs** (YC S25): AI agents for home-services technicians ([YC](https://ycombinator.com/companies/noso-labs)) [S].
- **ECI GlobalEdge**: one-tap AI troubleshooting recommendations [S].

The cited pages describe voice guidance or troubleshooting recommendations for field-service
technicians. Whether these products coordinate multiple people already at a site or select whom
to dispatch is not described in the sources summarized here. **Our design** targets observation
routing among people already present in a simulated site.

### 1.10 Remote visual support - TechSee, CareAR, Blitzz, Help Lightning

The cited example describes a video session where an expert or AI sees through a user's camera,
with the aim of avoiding truck rolls ([CareAR](https://carear.com/blog/what-is-a-truck-roll-how-to-reduce-them)) [C].
The referenced material is visual-support oriented. Other interaction patterns are not established
by this example. Vision could complement Pramana as a future observation modality ("show me the
switch").

### 1.11 Voice operations at scale - HappyRobot; voice intake - SkipCalls, Octonomy, CallSphere

- **HappyRobot**: $15.6M Series A led by a16z in Dec 2024 ([HappyRobot](https://happyrobot.ai/post/series-a-announcement)) [V]. AI voice agents make inbound and outbound logistics calls (check calls, load updates, negotiations) [C]. This is evidence of vendor-described voice operations; it does not independently establish product performance. Diagnostic inference is not described in the cited pages.
- **SkipCalls**: after-hours MSP call routing with configurable diagnostic questions, summarized for the technician ([SkipCalls](https://skipcalls.com/it-company/does-skipcalls-work-for-msps-can-it-route-urgent-after-hours-outage-calls-server)) [C].
- **Octonomy**: a voice agent for technical hotlines that pre-qualifies tickets ([computer-automation.de](https://www.computer-automation.de/operate---monitor/octonomy---ai-voice-agent--for-technical-hotlines.htm)) [S].

The cited pages focus on calls or intake. Choosing diagnostic observations across several people
is not described in the material summarized here.

### 1.12 Microsoft Research systems - RCACopilot, Triangle, AIOpsLab, OpenRCA

The cited descriptions cover digital incident-management research systems:

- RCA via engineered handlers (RCACopilot)
- multi-agent triage (Triangle; [GitHub](https://github.com/microsoft/Triangle))
- a fault-injection benchmark framework ([AIOpsLab](https://www.microsoft.com/en-us/research/publication/aiopslab-a-holistic-framework-for-evaluating-ai-agents-for-enabling-autonomous-cloud))
- a hard RCA benchmark ([OpenRCA](https://microsoft.github.io/OpenRCA): best 11.34%)

**What we borrow:** AIOpsLab's fault-injection plus agent-interface design for our simulator.
**What differs in our design:** people supply observations at the simulated physical site.

### 1.13 Gnani's own Inya / Agent Builder

Gnani describes Inya and Agent Builder as tools for enterprise voice-agent development. The
[programme FAQ](https://www.gnani.ai/internship) lists Agent Builder as out of scope for this
programme [V]. This is an eligibility note; whether Inya includes an investigation engine is not
established by the sources reviewed here. Pramana's use of Gnani speech APIs is described in
[GNANI_INTEGRATION.md](engineering/GNANI_INTEGRATION.md). Award fit is mapped separately in
[SUBMISSION.md](SUBMISSION.md).

### 1.14 ServiceNow AI Agents for help desk [C]

Sources reviewed 2026-11-10: [ServiceNow's help-desk agent tutorial](https://www.servicenow.com/community/ceg-ai-coe-articles/build-a-help-desk-agent-in-10-minutes-with-servicenow-ai-agents/ta-p/3473300).
The tutorial describes clarifying questions, knowledge-backed device troubleshooting, and
deployment through service portal, chat, or voice [C]. The [voice agent documentation](https://www.servicenow.com/docs/r/intelligent-experiences/itsm-manage-ticket-ai-voice-agent.html)
describes ticket lookup, confirmation, comments, and escalation [C]. This is adjacent IT help-desk
support. Whether the product provides multi-person physical-site diagnosis or Bayesian observation
reliability is not described in these sources.

### 1.15 Augury + MaintainX [C]

Source reviewed 2026-11-10: [joint announcement dated March 24, 2026](https://www.augury.com/media-center/press/augury-maintainx-partner/).
The announcement describes machine-health insights feeding traceable MaintainX work orders and a
feedback loop. This is an adjacent machine-health and maintenance-workflow alternative. The
announcement does not address adaptive interviews; availability is unknown from this source.

---

## 2. Feature comparison matrix

This table separates what the cited public material describes from what it does not establish.
"Not established" is not a product exclusion. Astyr and Quintess source summaries below retain the
original 2026-11-04 review date; PagerDuty, ServiceNow, and Augury + MaintainX were reviewed on
2026-11-10.

| Product | Public material reviewed describes | Not established by those sources |
|---|---|---|
| Astyr [C] | Telemetry and documentation, a proposed safe test, matching one technician, and a returned field verdict. | Whether multiple people can take part in one investigation; an observer-reliability model. |
| Quintess [C] | Technician-led voice troubleshooting, suggested checks, ranked causes, and escalation to an expert. | Whether several people can be interviewed concurrently; an observer-reliability model. |
| PagerDuty Paige [C] | Early Access virtual responder, incident history and integrations, recommended next steps, and Slack/web workflows. | Physical-site interviews, on-site voice, and physical repair verification. |
| ServiceNow AI Agents [C] | Clarifying questions, knowledge-backed device troubleshooting, and service-portal, chat, or voice deployment. | Multi-person physical-site diagnosis and observation-reliability inference. |
| Augury + MaintainX [C] | Machine-health insights feeding traceable work orders and a feedback loop. | Adaptive interviews, multi-person evidence gathering, and voice workflows. |
| Utility outage management [V/C] | Customer reports combined with network topology and protective-device information. | Active selection of whom to ask, reliability inference, and the exact update method across current products. |
| Pramana (repo evidence) | A deterministic engine that selects simulated observations, supports parallel participants, and separates diagnosis, approval, and simulator truth. | Generalization to real buildings, external populations, or measured speech quality. See [EVALUATION.md](EVALUATION.md) and [DEMO.md](DEMO.md). |

---

## 3. Honest novelty assessment

- **Not novel by itself:**
  - asking a human to run a check (Astyr, Quintess, decades of SOPs)
  - EIG question selection (GDE in 1987; UoT/BED-LLM in 2024–26)
  - observer reliability (Dawid–Skene in 1979; Wang et al. in 2012–13)
  - humans plus topology inference (utility OMS)
  - voice agents
  - authorization gates
- **Potentially distinctive combination to investigate** [I]: the original non-exhaustive review,
  accessed 2026-11-04, did not identify a product or paper combining all of these. This is an
  inference from that review, not a uniqueness or absence claim. The selected Nov 10 competitor
  update did not perform a complete new landscape search:
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
| Blume, Lightspeed, General Catalyst, Accel, Khosla, Bessemer, GV, Menlo, Radical, NFX | No primary thesis page read today. A Blume portfolio post on evaluating voice-AI platforms exists [S]. Menlo's 2026 "show me the money" framing [S] | - | **Not verified; no claims made** |

**Implication for the pitch.** Investors already back three adjacent categories:
- AI investigation over telemetry
- voice agents that do operational calling
- physical AI and observability

Pramana's pitch is the intersection of the three: *investigation for the physical world, using voice, where telemetry is absent*. We should not claim any investor endorses this.
