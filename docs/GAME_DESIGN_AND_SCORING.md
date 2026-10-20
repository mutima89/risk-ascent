# Risk Ascent: game design and scoring

This document explains every system the player interacts with and every formula that produces a score, so that results can be audited. The code references point at `riskascent/`.

## 1. Design principles

1. **Score judgement, explain luck.** Decisions are graded on authored quality, never on the random outcome. Outcomes are rolled from a recorded seed and the debrief says which one you got: good call and good result, good call and bad luck, or poor call and a lucky escape.
2. **Real tools, real data.** The register, workbench, KRIs, control tests, BIA, financial models and reports all run on the same live organisation state. They are not mock-ups.
3. **Consequences are delayed and visible.** Many choices schedule events that may fire months later. Every incident explains the probability and the roll behind it.
4. **Promotion reflects competence.** XP alone never promotes you. You also need passed core work, a passed capstone and the competency minimums for the next role.
5. **Low-friction learning.** One next action, checklists, saved progress at every step, no streaks, no penalties for taking a break.

## 2. Career structure

| Level | Role | XP to reach |
|---|---|---|
| 1 | Risk Management Graduate Trainee | 0 |
| 2 | Junior Risk Analyst | 250 |
| 3 | Risk Analyst | 600 |
| 4 | Senior Risk Analyst | 1,050 |
| 5 | Risk Team Lead | 1,550 |
| 6 | Risk Manager | 2,100 |
| 7 | Senior Risk Manager | 2,700 |
| 8 | Head of Enterprise Risk | 3,350 |
| 9 | Director of Risk Management | 4,050 |
| 10 | Chief Risk Officer | 4,800 |

The title is suffixed with the player's track (for example "Risk Analyst, Cyber and Technology Risk"). From level 5 the player picks a management or expert path at each promotion. The two paths have different competency minimums.

After the CRO board simulation (pass mark 70%) the **executive paths** unlock: Group CRO, CEO, COO, Board Risk Committee Adviser, Independent Consultant, Chief Resilience Officer, and Specialist Risk Executive. Each has its own competency minimums and an assessment mission. **New Game Plus** starts a new career at another organisation on a chosen difficulty and carries over earned achievements.

### Tracks and organisations

There are ten tracks (ERM, financial, operational, strategic, cyber/technology, project/infrastructure, continuity/resilience, compliance/regulatory, insurance/risk financing, HSE). The track changes the salary multiplier and which missions are recommended.

There are nine organisations in eight industries: hospitality (Meridian Coast Hotels & Resorts, USD; Al Waha Hospitality Group, Saudi Arabia, SAR), banking, retail/logistics, technology, energy, real estate/infrastructure, government and healthcare. Each one sets its currency, `money_scale` (which multiplies every monetary figure in content), its starting metrics, its stakeholders, and its risk, KRI, control and BIA libraries. Missions can be limited to particular geographies (the Saudi pack) or industries.

## 3. Missions

A mission moves through **briefing → investigation → decisions → debrief**.

- **Investigation.** The player reads the evidence documents, then optionally answers a gap analysis ("which information do you still need?"). That analysis is scored like a multi-select and counts for half a step's weight, all of it towards the *evidence* and *analysis* competencies.
- **Decision steps.** There are eight step types:

| Type | Scoring |
|---|---|
| `choice` | quality ÷ 3, with quality 0 (poor), 1 (weak), 2 (reasonable) or 3 (strong). It counts as correct when quality ≥ 2. |
| `multi` | max(0, (true picks − 0.5 × wrong picks) ÷ number of correct options) |
| `numeric` | Within tolerance: full credit × retry credit^(attempt − 1). The tolerance is the step's `tolerance_pct` × the difficulty multiplier × the adaptive multiplier. Within three times the tolerance on the final attempt: 0.4 × retry credit. Otherwise 0, and the solution is shown. |
| `classify` | share of items placed correctly |
| `rank` | 1 − Spearman footrule distance ÷ ⌊n²/2⌋ |
| `allocate` | value of the chosen items ÷ optimal value (exact 0/1 knapsack); over-budget selections are rejected before scoring |
| `matrix` | Mean over the rated axes of 1.0 (exact), 0.6 (one step off), 0.2 (two steps off) or 0. A zero is added if residual exceeds inherent. |
| `write` | Share of rubric elements present, where each element accepts several keywords. ×0.7 if below the minimum length, ×0.85 if above the maximum. The game says plainly that this is local keyword matching, and shows the model answer. |

- **Retries.** Calculation steps allow retries depending on difficulty (Guided 3, Professional 1, Executive 0). Each retry multiplies the credit by 0.8, 0.6 or 0.5 respectively.
- **Mission score** = the weighted mean of step scores (default weight 1) plus the investigation at weight 0.5.
- **XP** = mission XP × score when the score is at least 0.4, otherwise 10% of the mission's XP. A replay that beats your previous best earns 25% of that; a replay that does not improve earns none.
- **Endings** are chosen by score band and flags (for example `duct_warning_ignored`), so the story reflects what you actually did.
- **Effects** of options and endings change organisation metrics, stakeholder trust and flags, and can schedule future events with a delay and a probability.

### Judgement versus luck

A `choice` option may carry `outcome: {p_bad, good, bad, bad_effects, good_effects}`. The roll is `Random(stable_seed(run_seed, step_id, option_id))`, compared against `p_bad × difficulty.event_severity` (capped at 0.95). The roll, the probability and the seed are shown in the step details. The debrief then states one of:

- strong choice + good outcome → "sound judgement, and it paid off";
- strong choice + bad outcome → "bad luck, not poor judgement: you would make the same call again";
- weak choice + good outcome → "you avoided the adverse chance by luck; do not mistake this for evidence the approach works";
- weak choice + bad outcome → "the risk you accepted materialised".

The CRO career summary keeps a count of "sound calls, bad luck" so players learn to separate the two.

## 4. Competencies, skills and adaptive support

There are **11 competencies**: technical accuracy, evidence quality, analytical reasoning, risk prioritisation, financial judgement, decision quality, communication, stakeholder management, ethical judgement, leadership and strategic thinking. Each starts at 30/100.

After every step, each competency the step assesses moves toward the observed performance:

```
alpha  = clamp(max(0.12, 1 / (evidence + 2)) × clamp(weight, 0.25, 1.5), max 0.6)
score' = score + alpha × (performance × 100 − score)
```

Early evidence moves the score quickly and later evidence moves it more slowly, which acts as a simple confidence-weighted average. Using a worked example multiplies the evidence weight by 0.7.

The **skill tree** has five branches (analytical, controls, quantitative, influence, leadership). Each branch's score is the mean of its competencies. Tiers unlock at Beginner (40, 2 pieces of evidence), Intermediate (55, 6), Advanced (70, 12) and Executive (82, 20).

**Adaptive scaffolding** looks at the last six step scores. A mean below 0.5 switches to *support*: hints open automatically, the worked example is offered first, and tolerances widen by 25%. A mean of at least 0.85 over five or more steps switches to *stretch*: extra ambiguous documents appear and tolerances tighten by 25%. Anything else is *normal*.

| Difficulty | Hints | Worked examples | Calculation retries | Tolerance | Event severity | Budget |
|---|---|---|---|---|---|---|
| Guided | always | yes | 3 | ×1.5 | ×0.7 | ×1.2 |
| Professional | on request | yes | 1 | ×1.0 | ×1.0 | ×1.0 |
| Executive | after an error | no | 0 | ×0.6 | ×1.3 | ×0.85 |

## 5. Promotion, interviews and salary

To be **eligible** for the next level the player needs all of the following (`core/career.py: promotion_checks`):

1. XP ≥ the next level's requirement;
2. every core assignment of the current level at a best score ≥ 60%;
3. the stage capstone (if any) at ≥ 70%;
4. each competency minimum for the next role on the chosen path.

The **interview** asks three questions drawn (seeded) from the pool for the target stage, with options shuffled. The interview score is the mean of quality ÷ 3, and the player needs at least 0.5 to be promoted. A failed interview costs nothing but time, and the feedback explains every answer.

**Salary** (illustrative): the USD reference band for the level × geography multiplier × industry × organisation size × track × FX. In negotiation the player picks an ask position *a* in the range 0–1. The supported position is

```
supported = 0.2 + 0.6 × evidence_strength + 0.2 × trust/100
```

where `evidence_strength` is the mean best score on the level's core work. If *a* ≤ supported + 0.05, the ask is accepted and trust rises by 2. If *a* is less than 0.25 above supported, it is countered at the midpoint. Otherwise it is countered at the supported position and trust falls by 3. **All salary figures are labelled "illustrative simulation data, not a market survey".**

**Performance reviews** compare each competency to the expectation for the player's stage (meets, exceeds or below), cite specific missions as evidence, list three strengths and up to three development areas with recommended missions, and include the player's confidence calibration.

## 6. The living organisation

The organisation advances one month when a mission completes or when the player chooses to advance (`core/org_sim.py: tick`). Each month:

1. Operating cash flow is added: (revenue − operating costs) ÷ 12. Index metrics drift 2% back toward 55.
2. Each KRI moves by `drift × (1 − 0.5 × control_effectiveness) + N(0, volatility)`. Warning and critical breaches, and recoveries, are logged with the required escalation.
3. Scheduled consequences that are now due fire with their stored probability.
4. Register risks can materialise. The monthly probability comes from the residual likelihood's midpoint (× 0.6) converted to a monthly rate, with at most two incidents a month. Severity is the impact midpoint × money_scale × 0.15 × lognormal(0, 0.5) × event severity. Each incident shows its probability and roll, and says whether the controls were rated effective.
5. At most one random industry event fires from the organisation's pool.

Every random draw uses `stable_seed(career_seed, period, kind, id)` (FNV-1a), so the same seed and the same decisions always give the same world. The seed is shown in settings and in reports.

Stakeholders keep a trust level from 0 to 100. Replies to messages, mission choices and escalation behaviour change it: escalating a normal KRI reading costs credibility, while ignoring a critical one costs more. Trust with the CFO feeds the investment approval decision. Below the player's delegated authority, the player can approve an investment themselves if the benefit/cost ratio is at least 0.5. Above it, the CFO approves when the three-year benefit/cost ratio and trust are high enough.

## 7. The workspace tools

| Tool | What it calculates |
|---|---|
| Risk register | Inherent and residual L × I on the configured matrix (3×3, 4×4 or 5×5; bands are configurable). Residual is validated against control effectiveness: controls cannot increase risk, a reduction must be supported by control strength, and "effective controls with no reduction" is flagged. Risks are prioritised by appetite status, then residual score, then residual impact, then inherent score. |
| Assessment workbench | Probability and £/$ impact are mapped to ratings. The strongest preventive control reduces likelihood and the strongest detective or corrective control reduces impact (weak controls do not stack). It also checks appetite and tolerance per category, sensitivity (does a ±25% estimate change the band?) and expected annual loss. |
| Controls testing | Design rating from six criteria. Missing either the cause or the owner caps the rating at Weak. The operating test uses a sample size by frequency (annual 1, quarterly 2, monthly 3, weekly 10, daily 25, multiple daily 40, automated 1). 0 exceptions means effective; 1 exception in 25 or more means partial; anything else is ineffective. An undersized sample means "insufficient evidence". Overall = min(design, operating). |
| BIA | Criticality tier from the impact curve at 4h, 24h, 72h and 1 week. Checks RTO ≤ MTPD, that dependencies recover no slower than dependants, and that demonstrated capability meets the RTO. Also gives a dependency-ordered recovery sequence. |
| KRIs | Thresholds, direction, owner and escalation; trend from the least-squares slope of the last 4 readings. |
| Financial lab | EL = p × impact; scenario-weighted loss; Monte Carlo with Poisson frequency × lognormal severity (fitted from median and P90), 2k–100k trials with a seed, giving mean, median, P90/95/99, ES95, P(any loss) and the reserve at a confidence level; cost-benefit with NPV, undiscounted ROI, payback and BCR; tornado one-at-a-time sensitivity; and a 12-month liquidity stress with runway and covenant breach month. |
| Reports | Executive dashboard, top risks, heat maps, KRI trends, post-incident review, investment proposal, risk committee report and board summary, unlocked by level. Each is a static HTML document, exportable to PDF, with the register and KRI history available as CSV. |
| Crisis exercise | Several seeded threats grow every turn and response capacity is limited. Actions are investigate (reveals true severity and makes containment more effective), contain, communicate (halves reputational spread) and escalate (+2 capacity next turn; escalating minor threats costs credibility). |

## 8. Learning systems

- **Spaced retrieval.** Each concept a mission teaches becomes a card. A correct answer moves the card up one box. A miss sends it back to box 0, due tomorrow. The default intervals are 1, 3, 7, 14, 30 and 60 days, and the player can change them. Reminders appear only as counts, never as pop-ups.
- **Confidence calibration.** The player rates their confidence (50–100%) on reviews and key decisions. The game reports the Brier score, calibration bins, and the bias (mean confidence − accuracy), and says when the player is over- or under-confident.
- **Worked examples and hints.** Their availability depends on difficulty and scaffolding. Using a worked example reduces the competency evidence weight to 0.7, but never the XP.
- **Deliberate practice.** The training centre suggests missions that target the three largest gaps against the expectations for the player's stage.

## 9. Achievements

There are 81 achievements in eight categories: career 17, tools 17, skills 13, organisation 9, capstone 7, executive 7, learning 6, crisis 5. Each one has a machine-checkable condition: `mission` (with a minimum score), `missions_count`, `level`, `counter` (for example reports generated or controls tested), `branch_tier`, `all_branches`, `competency`, `stakeholder` trust, `flag`, or `calibration`. Hidden achievements are masked until earned. Nothing is awarded for time played or for logging in.

## 10. Ethics and dark patterns

There are no streaks, no loss aversion, no timers that punish, no in-game currency to buy, and no notifications outside the app. Mission content scores honest disclosure and ethical options highly even when they are commercially uncomfortable, and the ethical-judgement competency tracks it. Salaries and credentials are labelled as illustrative and as game achievements.
