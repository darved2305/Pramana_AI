# RESEARCH.md — Questions, verified facts, papers, search log

All web material below was accessed on **2026-11-04**.

**Labels**
- **[V]** — verified on a primary page today.
- **[C]** — the company's or authors' own claim.
- **[S]** — secondary or aggregator source.
- **[B]** — a classic reference we cite from bibliographic knowledge; it was not re-fetched today.

**Depth of verification.** For papers, we read the abstract page. Full texts were not read unless a note says otherwise.

---

## 1. Research questions and short answers

| # | Question | Short answer | Where it is used |
|---|---|---|---|
| RQ1 | What exactly does the programme allow and require? | Open brief. Must make genuine use of a Gnani model or API. Shortlist goes by verified engagement on the nominated posts. Agent Builder is out of scope. Evon is not on the API platform. Synthetic data only. Deadline Nov 10, 23:59 IST, no extensions. [V] | PRODUCT §0, §22; PLAN §32 |
| RQ2 | Which Gnani capabilities enable a *specific* product capability? | Prisma v3.0: language candidates, `codemix`, `keyterms`/`previous_text` (question-conditioned ASR). Prisma REST: second-opinion decode. Timbre v3.0: one persona across 10 languages. Evon: a sovereign language layer, if we host it. [V] | PRODUCT §22 |
| RQ3 | What is missing from Gnani that the design must work around? | No confidence scores. No interim transcripts. No word timestamps. Per-org concurrency cap with no published number. No credit-to-usage conversion. Timbre does not support incremental text streaming. [V] | PLAN §12, §23 |
| RQ4 | Does anyone already do multi-human, active, voice-based physical investigation? | Not found (search log §5). The nearest products guide one technician (Astyr, Quintess, Aquant, NOSO), passively aggregate callers (utility OMS), or hire humans for tasks (RentAHuman, Humwork). | COMPETITORS |
| RQ5 | What is the right scientific frame? | Sequential Bayesian experimental design / decision-theoretic troubleshooting, with heterogeneous noisy human sensors. Plus truth discovery. Plus speech uncertainty. | PRODUCT §10, §19 |
| RQ6 | Should an LLM do the planning? | No. Evidence: MediQ (naive question-asking hurts); UoT and BED-LLM (explicit information gain beats prompting); Hitachi's fault-diagnosis work (LLMs struggle to calibrate); the HVAC review (LLMs are best as semantic/workflow layers). We test this claim directly with Baseline B. | PRODUCT §9, EVALUATION |
| RQ7 | Can multi-party voice be done in one shared conversation? | Not reliably today. MultiPartyTurnBench reports near-chance selective-interruption handling. We use isolated 1:1 calls coordinated by a shared belief. | PRODUCT §13 C3 |
| RQ8 | How should humans be questioned so their answers are reliable? | Ask for observations rather than conclusions. Use item-specific options rather than agree/disagree. Avoid leading wording. Model hedges and hearsay. | PRODUCT §16 A5, A7 |
| RQ9 | Can we publish ASR metrics? | Risky. The linked EULA §16 restricts disclosing benchmark results; §4.2(g) restricts disclosing performance information. Ask Gnani first. | PRODUCT §22 |

---

## 2. Gnani verification log [V unless marked]

| Fact | Value | Source |
|---|---|---|
| Programme name, theme | "The Great Indian AI Internship Challenge. Build Sovereign AI for India." Open brief | [gnani.ai/internship](https://www.gnani.ai/internship) |
| Eligibility | Enrolled in a degree or course at an Indian college or university; 18+; solo or a team of two; one entry per team | internship page |
| Dates | Build window opened Oct 1 (press says Sept 30); **final submission Nov 10, 2026, 11:59 PM IST**; internships scheduled to start Jan 1, 2027; interview dates not stated | internship page; [registration terms](https://www.gnani.ai/great-indian-ai-internship-registration-form) ("final, no extensions") |
| Credits | 5,000 programme credits per registration; for teams, credits go to the primary registrant; usage is managed at app.gnani.ai/voice; "Your credits work on the models hosted on the API platform"; expiry not stated | internship page, terms |
| Scope exclusions | "The agent builder sits outside the scope of this internship, and we don't offer APIs for it yet." Evon is not on the API platform; weights are available on Hugging Face on request | internship FAQ |
| Internships | Up to 100 paid, six-month internships; stipend up to ₹1 lakh/month per intern (a ceiling, not shared between teammates); individual interviews; only a written offer confirms | internship page, terms |
| Shortlist | "The eligible projects with the strongest verified engagement are shortlisted for interview" (reactions, comments and reshares on the nominated posts, counted up to the closing cutoff) | internship page |
| Awards | 10 × ₹50,000: Main Character (regional/low-resource language), Mixed Vibes (code-mixed voice), Real Deal (most useful real-world problem, e.g., farmers, kirana stores, rural health workers), Noise Canceller (messy telephonic audio), Two-Person Army, Solo Ninja, Jugaad Genius (most creative or unexpected use of Gnani models), Small Town Big Build (Tier 2/3), Demo Day Drop (best 60-second demo), Crowd Favourite (public votes). Maximum one award per team | internship page |
| Post requirements | Public video of the app working on LinkedIn and/or X; explain what you built and the Gnani tech used; tag Gnani AI; include #GnaniAI and #GreatIndianAIInternshipChallenge; nominate one post per platform; the post must be live before you submit | internship page, terms |
| Prohibited | "Purchased engagement, bots, paid promotion, engagement exchanges, plagiarism and misleading demonstrations"; synthetic data only (no real phone numbers, account numbers, Aadhaar, PAN, or recorded calls) | terms; internship page |
| Third-party LLMs | Not addressed in the terms. Gnani's own docs show Claude/OpenAI used for analysis and Groq in the Pipecat example | terms; docs use-case pages |
| EULA (linked as T&C) | §16: benchmark test results "may not be disclosed outside Your organization"; §4.2(g): no disclosure of "information relating to the performance or quality"; no audio-retention terms | [EULA](https://www.gnani.ai/legal/eula) |
| STT hosts and auth | REST `POST https://api.vachana.ai/stt/v3`; WS `wss://api.vachana.ai/stt/v3/stream`; header `X-API-Key-ID`; browsers cannot set WS headers, so proxy through a backend | [STT realtime](https://docs.gnani.ai/api/STT/stt-websocket.md), [quick start](https://docs.gnani.ai/api/introduction/quick-start.md) |
| Prisma v3.0 | Released 22 Oct 2026, opt-in (v2.5 is the default). `indic-auto` or 1–4 language codes; `detected_language_code`; formats `verbatim` / `transcribe` / `codemix` / `transliterate`; hints `keyterms` (≤ 200), `topic` (≤ 1,600 chars), `previous_text` (last 600 chars kept), `speaker_names` (1–4) | [changelog](https://docs.gnani.ai/api/introduction/changelog.md), [Prisma v3](https://docs.gnani.ai/api/STT/models/prisma-v3.md) |
| Languages (STT) | bn-IN, en-IN, gu-IN, hi-IN, kn-IN, ml-IN, mr-IN, pa-IN, ta-IN, te-IN (both models); no separate Hinglish code; Assamese rejected | [languages](https://docs.gnani.ai/api/STT/languages.md) |
| Realtime protocol | 1,024-byte frames (512 samples; 32 ms at 16 kHz) sent at real-time cadence. Server VAD: `x-vad-threshold`, `x-min-silence-ms` (default 500), `x-min-speech-ms`, `x-min-segment-ms` (a high value silently drops "yes"), `x-max-speech-s`. Control messages `commit` and `update_settings`. Events `connected`, `speech_start`, `processing`, `transcript` (final only), `error`. 15-minute session cap (close 1001). Idle timeout 60 s by default (5–900). Per-org concurrency cap, number not stated | STT realtime page, [limits](https://docs.gnani.ai/api/STT/limits.md) |
| Not provided | Confidence scores (REST/realtime), n-best, word timestamps, interim transcripts, keepalive spec | Prisma v3 page; realtime page |
| REST limits | ≤ 30 s of audio; 504 `UPSTREAM_TIMEOUT` after 5,000 ms; 429 example "Only 1 active request is allowed at a time", no `Retry-After`; 402 = insufficient credit | [errors](https://docs.gnani.ai/api/introduction/errors.md) |
| Rate limits | "Current request-rate and concurrent-session limits for your account are available at app.gnani.ai" | limits page |
| TTS | REST `/api/v1/tts/inference`, SSE `/api/v1/tts/sse`, WS `wss://api.vachana.ai/api/v1/tts`. v2.5: 42 voices with one preferred language each (Marathi: Zahira, Ishaan; Hinglish `hi-en`: Poorvi). v3.0: 13 voices, each speaks all 10 languages, audio tags (`<pauses>` etc.; tags are billable characters). Speed 0.85–1.15. No incremental text over WS. No latency figures in the docs (marketing claims < 200 ms p95 [C]) | [voices](https://docs.gnani.ai/api/TTS/available-voices.md), [TTS WS](https://docs.gnani.ai/api/TTS/tts-websocket.md), [audio tags](https://docs.gnani.ai/api/TTS/tts-audio-tags.md), [TTS product page](https://www.gnani.ai/text-to-speech-api) |
| Text normalization | Numbers, currency, dates and IDs are expanded; IP addresses are not covered; Marathi must be set explicitly (Devanagari script defaults to Hindi) | [TN guide](https://docs.gnani.ai/api/TTS/tts-input-formating.md) |
| Integrations | `livekit-plugins-gnani` (Prisma/Timbre incl. v3.0 per Gnani docs; LiveKit's own page shows older versions); `pipecat-gnani` (Pipecat ≥ 1.5); Python SDK `gnani-vachana` (SDK STT page shows no `model` param) | [LiveKit](https://docs.gnani.ai/livekit/introduction.md), [LiveKit's page](https://docs.livekit.io/agents/integrations/stt/gnani/), [Pipecat](https://docs.gnani.ai/pipecat/introduction.md), [SDK](https://docs.gnani.ai/python-sdk/introduction.md) |
| Evon v3.3 | Nemotron-H hybrid Mamba2-Transformer MoE; 30B total / ~3.5B active; 128K context; 11 languages incl. Marathi; reasoning toggle; tool calling via vLLM qwen3_coder parser ("active area of development"); Apache-2.0; vLLM ≥ 0.12 / SGLang / Transformers ≥ 5.3; H100/A100 class; not deployed by any inference provider | [HF card](https://huggingface.co/gnani/gnani-evon-v3.3-30B-A3B) |
| Evon benchmarks [C] | MILU macro 78.74 vs Sarvam-30B 67.15, Sarvam-105B 75.71; trails Gemma-4-26B-A4B (82.65) and Gemma-4-31B (85.29) on MILU in Gnani's own table | HF card |
| Prisma claims [C] | "#1 in 8 of 9 Indian languages on Kathbath Noisy 8kHz"; "15.3% lower WER than ElevenLabs Scribe v2", etc.; language ID "95% accuracy on 3+ seconds" | [models](https://www.gnani.ai/models), [Prisma v3 page](https://www.gnani.ai/resources/prisma-v3) |
| LiveKit Cloud (plan B) | Free "Build" plan: 1,000 agent session minutes, 5 concurrent agent sessions, 5,000 WebRTC minutes; self-hosting is open source | [pricing](https://livekit.com/pricing) |

---

## 3. Paper and prior-art notes

Each entry covers: what it contributes; its method; what it demonstrated; what remains unsolved; how it improves our system; and whether we can realistically implement it without training a model.

### 3.1 Choosing what to observe

**de Kleer & Williams, "Diagnosing Multiple Faults", *Artificial Intelligence* 32 (1987) [B]**
- *Contribution:* the General Diagnostic Engine (GDE). It derives conflicts and candidate diagnoses for multiple simultaneous faults, and picks the next measurement by minimum expected entropy.
- *Demonstrated:* digital circuits.
- *Unsolved:* noisy human observers; cost of measurements across different people; spoken channels.
- *Use for us:* it is the direct ancestor of our measurement selection. We add costs, reliabilities and decision focus.
- *Implementation:* yes. Our hypothesis space is small enough to enumerate.

**Reiter, "A Theory of Diagnosis from First Principles", *AI* 32 (1987) [B]**
- *Contribution:* formal diagnoses as minimal hitting sets of conflicts.
- *Use for us:* it justifies enumerating pairs of faults guided by conflicts, rather than all pairs.
- *Implementation:* yes.

**Heckerman, Breese & Rommelse, "Decision-Theoretic Troubleshooting" (MSR) [V-abstract]** ([MSR page](https://www.microsoft.com/en-us/research/publication/decision-theoretic-troubleshooting/))
- *Contribution:* a Bayesian network recommends repairs and observations from expected repair cost. An observation is worthwhile only if the expected cost after seeing it is lower.
- *Demonstrated:* troubleshooting systems. The tech report notes that the exact optimal decision tree blows up (about 340,000 endpoints for 5 components and 3 observations).
- *Unsolved:* human observers in different places; spoken channels.
- *Use for us:* EVOI-based stopping and a myopic greedy policy.
- *Implementation:* yes.

**Golovin, Krause & Ray, "Near-Optimal Bayesian Active Learning with Noisy Observations", NeurIPS 2010 [V-abstract]** ([arXiv 1010.3091](https://arxiv.org/abs/1010.3091))
- *Contribution:* shows that greedy generalized binary search can perform very poorly once observations are noisy. EC² is adaptive-submodular and competitive with the optimal policy. Supports non-uniform costs and correlated noise.
- *Demonstrated:* a human-subject Bayesian experimental design about theories of decision-making.
- *Use for us:* do not use raw entropy over hypotheses alone; model noise explicitly. EC² or HEC are drop-in alternatives to our EIG_D scorer (P2 ablation).
- *Implementation:* yes for our sizes.

**Javdani, Chen, Karbasi, Krause, Bagnell & Srinivasa, "Near Optimal Bayesian Active Learning for Decision Making", AISTATS 2014 [V-abstract]** ([PMLR](https://proceedings.mlr.press/v33/javdani14.html))
- *Contribution:* the decision-region-determination problem. The goal is to push uncertainty into a single decision region, not to identify the exact hypothesis. The HEC algorithm is competitive with the optimal policy.
- *Demonstrated:* comparison-based learning; robot localization.
- *Use for us:* this is the formal basis for "stop when the action is certain" (decision classes).
- *Implementation:* EIG over decision classes is simple. HEC is a P2 option.

**Krause & Guestrin, "Near-optimal Nonmyopic Value of Information in Graphical Models", UAI 2005 [B]; Golovin & Krause, "Adaptive Submodularity", JAIR 2011 [B]**
- *Use for us:* justifies greedy batch selection of parallel observations (submodularity under conditional independence).
- *Caveat:* reliability coupling makes this approximate [I].

### 3.2 LLM-era information seeking

**UoT — "Uncertainty of Thoughts", NeurIPS 2024 [V-abstract]** ([arXiv 2402.03271](https://arxiv.org/abs/2402.03271))
- *Method:* the LLM simulates possible futures; rewards are based on information gain; rewards are propagated back.
- *Result:* +38.1% average task success versus direct prompting across medical diagnosis, troubleshooting and 20 Questions, with fewer questions (NeurIPS version; an earlier version reported 57.8%).
- *Unsolved:* hypotheses and likelihoods come from the LLM; there is one respondent and no model of reliability.
- *Use for us:* evidence that EIG-guided questioning beats prompting. Our likelihoods come from a causal model.
- *Implementation:* not needed; our engine is analytic.

**BED-LLM, ICLR 2026 [V-abstract]** ([arXiv 2508.21184](https://arxiv.org/abs/2508.21184))
- *Method:* sequential Bayesian experimental design, with EIG computed from the LLM's predictive distribution.
- *Result:* "substantial gains" on 20 Questions and preference elicitation versus prompting. A secondary summary cites the v1 example of 14% → 91% (celebrity guessing with Mistral-Large) [S].
- *Use for us:* supports the principle. We differ because our likelihoods come from physics, not from the LLM.

**MediQ, NeurIPS 2024 [V-abstract]** ([arXiv 2406.00922](https://arxiv.org/abs/2406.00922))
- *Result:* simply prompting models to ask questions *reduces* accuracy (an 11.3% relative drop). An abstention or confidence module helps.
- *Use for us:* a design lesson. Asking more questions is not automatically better; we need explicit stopping and abstention. This is also why Baseline B is an important comparison.

**MedClarify, arXiv 2602.17308 (Feb 2026) [S]**
- *Method:* LLM diagnosis agent with EIG-chosen follow-up questions and a Bayesian update.
- *Result:* reportedly about 27 percentage points fewer errors than a single-shot LLM.
- *Use for us:* the closest recent diagnostic analogue. It has one respondent and no reliability or cost routing.

**KnowNo — "Robots That Ask For Help", CoRL 2023 [V-abstract]** ([arXiv 2307.01928](https://arxiv.org/abs/2307.01928))
- *Method:* conformal prediction over LLM-proposed options. The robot asks for help when the prediction set contains more than one option. Comes with statistical guarantees.
- *Use for us:* future work on conformal calibration of the decision to stop or abstain.

### 3.3 Fault localization from end-user observations

**Sherlock — Bahl et al., SIGCOMM 2007 (MSR) [V-abstract]** ([PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/sherlock_sigcomm_07.pdf))
- *Method:* a multi-level, three-state inference graph built from host observations; the Ferret localization algorithm.
- *Result:* modelling multiple levels improved localization by 30% compared with two-level approaches.
- *Use for us:* people play the role of "end hosts". Our graph spans power, network and services.
- *Follow-up:* SpotLight (bipartite compression plus greedy set cover, about 100× faster) shows how to scale if our hypothesis space grows.

**Boolean network tomography (Duffield 2006), SCORE (Kompella et al., NSDI 2005), Shrink (Kandula et al. 2005) [B]**
- *Contribution:* inferring internal failures from end-to-end observations.
- *Use for us:* framing and pruning heuristics.

**Utility OMS trouble-call analysis [V]** ([US5568399](https://patents.google.com/patent/US5568399), [ETAP](https://etap.com/de/product/outage-analysis))
- *Method:* calls are combined with GIS topology and protective-device schema to find the probable fault location. Confidence rises as more calls arrive. Rules include "two customers sharing a transformer".
- *Use for us:* proof that humans as sensors plus topology has commercial value. We add *active* selection, reliability modelling and voice dialogue.

### 3.4 Unreliable human sources

**Dawid & Skene 1979 [B]**
- *Method:* EM over observer error rates, without ground truth.
- *Use for us:* the conceptual basis for observer reliability modelling.

**Wang, Abdelzaher, Kaplan et al., truth discovery in social sensing (IPSN 2012; TOSN 2014) [V-abstract]** ([TOSN PDF](https://www3.nd.edu/~sslab/pdf/tosn14.pdf))
- *Method:* joint MLE of source reliability and claim truth via EM.
- *Result:* beats fact-finding heuristics and majority voting.

**Wang et al., "Exploitation of Physical Constraints for Reliable Social Sensing", RTSS 2013 [V]** ([PDF](https://www3.nd.edu/~sslab/pdf/rtss13.pdf))
- *Result:* physical constraints improve the estimates of both source reliability and observation correctness.
- *This is the closest prior art to our "physics-consistent testimony weighting".*
- *Our difference:* a causal dependency model inside an active diagnostic loop; reliability integrated out per incident; per probe class; an explicit open-world hypothesis.

### 3.5 Asking well (survey and interview science)

- **Cognitive interview meta-analyses** [V-abstract]:
  - [Köhnken et al. 1999](https://informahealthcare.com/doi/abs/10.1080/10683169908414991): large gain in correct recall (d = 0.87); smaller increase in incorrect details (d ≈ 0.28 [S]).
  - [Memon, Meissner & Fraser 2010](https://works.bepress.com/christian_meissner/57/): replicated, with "a large and significant increase in correct details and a small increase in errors".
  - *Use for us:* open, observation-first elicitation, with a "describe what you see" variant.
- **Loftus & Palmer 1974 [B]:** question wording changes reported memories. *Use for us:* the realizer linter bans leading wording and any mention of causes.
- **Saris, Revilla, Krosnick & Shaeffer 2010** [V-abstract] ([SRM](https://ojs.ub.uni-konstanz.de/srm/article/view/2682)): agree/disagree questions give much lower data quality than item-specific questions. Krosnick 1991 [B, via secondary citation] connects acquiescence to satisficing. *Use for us:* confirmations use item-specific options ("green, orange, or no light?"); acquiescence skew is modelled for closed yes/no questions.
- **Kent 1964, "Words of Estimative Probability" [B]:** verbal probability expressions vary between people. *Use for us:* hedge weights are a heuristic to calibrate (Hindi "shayad", "lagta hai"; Marathi "kadachit", "vatta"). The weights are not facts.

### 3.6 Multi-party speech and turn-taking

- **MultiPartyTurnBench** (arXiv 2610.20172, Oct 2026) [V-abstract]:
  - 240 synthetic conversations with 2–5 speakers.
  - End-of-turn recall 82.5–92.6% at 4.3–11.8% false-positive rate.
  - Full-duplex agents reach 86.1–95.8% balanced accuracy on turn entry but near chance (46.9–54.7%) on selective interruption.
  - *Use for us:* shared-floor multi-party voice is unsolved, so we use isolated 1:1 calls.
- **Speak or Stay Silent** (arXiv 2603.11409) [V-abstract]: 120K labelled decision points; 8 LLMs fail zero-shot; supervised fine-tuning with reasoning traces adds up to 23 percentage points.
- **JarvisBench** (arXiv 2608.14870, Aug 2026) [V-abstract]:
  - An always-on layer that coordinates one human's attention across several agents, with a full-duplex speech reference implementation and 45 tasks. The abstract gives no numbers.
  - *Relation to us:* the inverse arrangement. Jarvis routes agents to one human; Pramana routes many humans to one belief.
- **When2Speak** (arXiv 2605.05626) [S]: a dataset for timing participation in multi-party conversation.

### 3.7 Agentic fault diagnosis and AIOps

- **Hitachi America, "Exploring LLM-based Frameworks for Fault Diagnosis"** (arXiv 2509.23113; the PHM 2025 version adds "Agentic" to the title) [V-abstract]:
  - LLMs do better with summarized statistics than raw data; multi-LLM setups improve sensitivity; LLMs struggle to calibrate across repeated fault cycles.
  - *Use for us:* keep the probabilistic calibration in code.
- **"LLMs for HVAC Operations" review** (arXiv 2609.05314, Sep 2026) [V-abstract]:
  - 66 studies; only 4 reach pilot level; none is "ready-now"; LLMs are best as "semantic and workflow layers rather than autonomous controllers".
  - *Use for us:* direct support for "LLMs translate, math decides".
- **AgentRCA** (arXiv 2607.22385, Jul 2026) [V-abstract]:
  - A digital twin plus a tool-augmented LLM that gathers evidence and evaluates competing hypotheses; reported competitive with supervised baselines without fault-specific training.
  - *Relation to us:* uses sensor data; our evidence comes from people.
- **AIOpsLab** (MSR, arXiv 2501.06706) [V-abstract]:
  - Deploys microservices, injects faults, generates workloads, exports telemetry, and gives agents an interface.
  - *Use for us:* the design pattern for our simulator and benchmark (fault injection plus an agent–site interface).
- **OpenRCA** (ICLR 2025) [V]: 335 failures; the best model with an RCA agent got 11.34% fully correct. ([site](https://microsoft.github.io/OpenRCA))
- **ITBench** (ICML 2025) [S]: SRE 11.4%, CISO 25.2%, FinOps 25.8%. **ITBench-AA** (May 2026) [V]: all frontier models below 50%; the best was 47%. ([AA](https://artificialanalysis.ai/articles/itbench-aa-launch))
- **RCACopilot / Triangle** (Microsoft) [S]: RCA from handlers and incident triage using LLM agents. These are digital-only.

### 3.8 Security of agents that read untrusted input

**CaMeL** (Google DeepMind, arXiv 2503.18813) [V-abstract]
- *Method:* a privileged LLM plans while a quarantined LLM handles untrusted data, and a custom interpreter enforces data-flow policies.
- *Result:* 77% of AgentDojo tasks solved with provable security, versus 84% with no defence.
- *Use for us:* a stronger version of the same principle. Our planner is not an LLM at all; the extractor outputs enum-typed data only.

### 3.9 Closed-loop discovery (inspiration)

Coscientist (Boiko et al., *Nature* 2023) and A-Lab (Szymanski et al., *Nature* 2023) [B]: autonomous hypothesis → experiment → update loops in laboratories. Our analogue uses people as the instruments.

---

## 4. Implementation implications (summary)

1. Enumerate hypotheses and compute exact EIG in numpy. Do not let the LLM estimate probabilities.
2. Use decision classes with an EVOI stopping rule, plus an `OPEN_WORLD` hypothesis for honest abstention.
3. Integrate out reliability per participant; mix toward uniform for hedges and hearsay.
4. Use isolated 1:1 calls, not a shared multi-party floor.
5. The extractor is a quarantined, enum-only structured-output call.
6. Because there are no ASR confidence scores, uncertainty comes from (hedge × second decode × extractor alternatives). Confirm only when the decision would change.
7. The benchmark must include a frontier-LLM policy choosing from the *same* action menu, as a fair test of RQ6.

---

## 5. Search log (what we searched; dead ends)

**Queries run (web search, 2026-11-04):**
- "Great Indian AI Internship Challenge" Gnani 2026
- PagerDuty SRE agent 2026
- Microsoft autonomous incident management (AIOpsLab / RCACopilot / Triangle)
- RentAHuman
- Humwork
- "Jarvis" proactive speech agent multi-party
- agentic FDD HVAC LLM
- "Exploring LLM-based Agentic Frameworks for Fault Diagnosis"
- BED-LLM
- Uncertainty of Thoughts
- MediQ
- multi-party turn-taking benchmark 2026
- AI SRE funding (Resolve / Traversal / Cleric)
- OMS trouble call analysis
- Sherlock inference graph
- truth discovery social sensing
- CaMeL
- r/sysadmin remote site troubleshooting
- truck-roll cost / no-fault-found
- Premise Data
- Aruba UXI
- voice-guided field troubleshooting startups 2026
- a16z physical AI 2026
- EC²
- Heckerman troubleshooting
- Javdani HEC
- OpenRCA
- ITBench
- Causely
- HappyRobot
- YC RFS 2026
- Aquant 2025 benchmark
- network documentation out-of-date survey
- cognitive interview meta-analysis
- acquiescence bias item-specific
- Indian hostel Wi-Fi complaints
- Downdetector methodology
- "AI agent calls multiple on-site staff gather observations" (no match found)
- Indian VC voice-AI thesis
- Menlo / Sequoia voice AI 2026
- physical constraints social sensing (RTSS 2013)
- LLM + Bayesian diagnosis + information gain 2026
- KnowNo

**Pages read directly:**
- the Gnani internship page, terms and EULA; Gnani docs (llms.txt, STT overview/models/v3/v2.5/languages/limits/realtime/REST, quick start, TTS voices/REST/SSE/WS/tags/TN, LiveKit/Pipecat/SDK pages, errors, changelog); gnani.ai models, Prisma v3, and STT/TTS product pages; the Evon HF card;
- Astyr (/product, /, /company); Quintess (/, fleet page, EAM page, trust page);
- LiveKit's Gnani plugin pages, turn handling, audio, RPC, pricing;
- YC RFS (now showing Winter 2027);
- arXiv abstracts: 2608.14870, 2610.20172, 2509.23113, 2607.22385, 2609.05314, 2501.06706, 2603.11409, 2508.21184.

**Could not access or read:**
- `docs.gnani.ai/stt-websocket.yml` and `tts-websocket.yml` (404);
- the Evon release-notes page body (it did not render);
- Gnani Discord and the app.gnani.ai dashboard (login required);
- the full Aquant report;
- the YC Spring 2026 RFS (the official page now lists Winter 2027);
- full texts of most papers (verified at abstract level only);
- primary investor thesis pages for Sequoia, Lightspeed, General Catalyst, Accel, Khosla, Bessemer, GV, Menlo, Radical and NFX (see COMPETITORS §4 for what was and wasn't verified).

**Negative findings:**
- No product found that actively coordinates several on-site humans by voice to pool observations for a diagnosis. The nearest were SkipCalls (MSP after-hours intake), Octonomy (technical-hotline voice agent) and CallSphere (outage intake plus scheduling).
- No published 2026 "vernacular voice AI" thesis found from Peak XV, Blume or Lightspeed.

---

## 6. Unresolved findings

1. The real concurrency and credit consumption on the programme account (Day-1 spike).
2. Whether the EULA's benchmark clause applies to programme participants' public posts (ask Gnani).
3. Whether Timbre v3.0 handles Hinglish written in Latin script well (listening test).
4. The real-world rate of model misspecification on uninstrumented sites. Our benchmark only simulates it.
5. Whether staff accept short AI calls (needs a pilot).
