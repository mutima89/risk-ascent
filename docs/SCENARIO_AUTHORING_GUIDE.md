# Scenario authoring guide

All game content is plain JSON in `riskascent/content/`. You can add missions, organisations, risks, KRIs, controls, events and achievements without touching Python. Content is validated on every start: if anything is wrong, the game refuses to start and lists each problem with its file and id.

> The packaged `RiskAscent.exe` contains a read-only copy of the content. To author content, run the game from source (`pip install -r requirements.txt`, then `python RiskAscent.py`) and rebuild the exe when you're done (see the README).

## Workflow

1. Copy an existing pack in `content/missions/`, for example `saudi_pack.json`, to a new file such as `my_pack.json`. Every `*.json` in that folder is loaded, and each file is a JSON **array** of missions.
2. Give every mission a unique `id`. Use a prefix for your pack, such as `X01`.
3. Validate:
   ```bash
   python -m pytest tests/test_content.py -q
   ```
4. Play it: start a career, open **Missions**, and use the filters. Use `--data-dir C:\temp\ra-test` to keep test careers apart from your real saves.

## Mission skeleton

```json
{
  "id": "X01",
  "title": "The Overbooked Weekend",
  "type": "side",
  "level": 2,
  "xp": 140,
  "duration": "10 min",
  "objective": "Decide whether to accept a large group booking that exceeds safe staffing levels.",
  "concepts": ["risk_appetite"],
  "from": "coo",
  "subject": "Can we take the conference group?",
  "briefing": "{sh:coo} wants to accept a 300-guest booking worth {m:420000} ...",
  "industries": ["hospitality"],
  "geographies": ["saudi"],
  "requires": {"missions": ["M02"]},
  "documents": [
    {"id": "d1", "title": "Staffing roster", "text": "..."},
    {"id": "d2", "title": "Last year's incident log", "text": "..."}
  ],
  "info_questions": {
    "prompt": "What else do you need before advising?",
    "options": [
      {"text": "Agency staff availability that weekend", "relevant": true},
      {"text": "The guests' dietary preferences", "relevant": false}
    ]
  },
  "steps": [ ... ],
  "debrief": {
    "summary": "What the player did and why it mattered.",
    "key_points": ["...", "..."],
    "stronger_approach": "What an expert would also have done.",
    "transfer": "How the same idea applies in another industry."
  },
  "endings": [
    {"id": "strong", "title": "Strong outcome", "min_score": 0.8, "text": "..."},
    {"id": "mixed", "title": "Mixed outcome", "min_score": 0.5, "text": "..."},
    {"id": "poor", "title": "Hard lesson", "min_score": 0, "text": "..."}
  ],
  "on_complete": {
    "effects": {"org": {"control_effectiveness": 1}},
    "effects_by_score": [{"min": 0.7, "effects": {"trust": {"coo": 3}}}]
  }
}
```

| Field | Required | Notes |
|---|---|---|
| `id`, `title`, `type`, `level`, `objective`, `briefing`, `steps`, `debrief`, `xp` | yes | `type` is one of `career`, `side`, `crisis`, `capstone`, `executive`, `weekly`. |
| `debrief.summary`, `.stronger_approach`, `.transfer` | yes | Every mission must teach. |
| `from`, `to` (on steps) | no | A stakeholder role id from `stakeholder_roles.json` (`ceo`, `cfo`, `coo`, `cio`, `chro`, `mentor`, ...). |
| `concepts` | no | Ids from `concepts.json`. They become spaced-review cards once the mission is completed. |
| `industries`, `geographies` | no | Limit the mission to organisations with that `industry` or `geography`. |
| `requires` | no | `missions` (must be completed), `flags_all`, `flags_none`, `min_capstone`. |
| `stretch_documents` | no | Extra ambiguous evidence, shown only in adaptive *stretch* mode. |

To make a mission count for promotion, add its id to a level's `required_missions` (or set it as the `capstone`) in `careers.json`.

## Placeholders

Text fields are rendered for the current organisation:

| Placeholder | Becomes |
|---|---|
| `{m:250000}` | Money in reference units × the organisation's `money_scale`, in its currency (`SAR 937,500`). Always write money this way so the content works in every organisation. |
| `{p:0.25}` | `25%` |
| `{sh:cfo}` / `{shr:cfo}` | The CFO's name / the name with their title |
| `{org}` `{player}` `{title}` `{industry}` `{city}` `{regulator}` `{cur}` | Organisation and player details |

## Step types

Every step needs a unique `id`, a `prompt`, and `competencies` (one or more of `technical`, `evidence`, `analysis`, `prioritization`, `financial`, `decision`, `communication`, `stakeholder`, `ethics`, `leadership`, `strategy`). Optional fields on any step: `weight` (default 1), `hint`, `worked_example`, `to`, and `confidence: true`, which asks the player to rate their confidence for calibration.

### choice: a judgement call

```json
{"id": "s2", "type": "choice", "competencies": ["decision", "financial"],
 "prompt": "Two other sites have overdue duct cleaning. Cleaning both costs {m:18000}.",
 "options": [
   {"id": "a", "text": "Clean both now.", "quality": 3, "feedback": "Proportionate and urgent.",
    "effects": {"org": {"cash": -18000}, "cancel": ["ev_kitchen_fire"]},
    "outcome": {"p_bad": 0.15, "good": "Heavy grease found; a fire was likely averted.",
                "bad": "The contractor damaged a fan.", "bad_effects": {"org": {"cash": -8000}}}},
   {"id": "b", "text": "Schedule them next month.", "quality": 0, "feedback": "Repeats the original mistake.",
    "effects": {"schedule": [{"event": "ev_kitchen_fire", "after": 1, "p": 0.35}],
                "flags": ["duct_warning_ignored"]},
    "outcome": {"p_bad": 0.35, "good": "No fire this month.", "bad": "A second fire occurred."}}]}
```

- `quality` is 0 to 3, and at least one option must be 2 or higher. Write `feedback` for **every** option. Explain *why*, not just "wrong".
- `outcome` adds luck. The roll is seeded, and the debrief explains judgement versus luck. Keep `p_bad` realistic: good decisions can still go badly.

### The other types

```json
{"type": "multi", "options": [{"text": "...", "correct": true}, {"text": "...", "correct": false, "why": "..."}]}
{"type": "numeric", "formula": "p * impact", "vars": {"p": 0.3, "impact": 500000},
 "money_vars": ["impact"], "unit": "money", "tolerance_pct": 2, "solution": "{p:0.3} x {m:500000} = {m:150000}"}
{"type": "classify", "categories": ["Risk", "Issue", "Control"],
 "items": [{"text": "Server room door found unlocked", "answer": "Issue", "why": "It is happening now."}]}
{"type": "rank", "items": [{"id": "safety", "text": "Life safety"}, {"id": "it", "text": "IT"}],
 "answer": ["safety", "it"], "why": "Life safety first, then by RTO."}
{"type": "allocate", "budget": 7, "unit": "harm units",
 "items": [{"id": "capex", "text": "Delay capex", "cost": 3, "value": 8, "note": "optional comment"}]}
{"type": "matrix", "expected": {"l": 1, "i": 5}, "why": "Supervision lowers likelihood; severity stays."}
{"type": "write", "min_words": 20, "max_words": 120,
 "rubric": [{"element": "Event", "keywords": ["fire", "duct"], "tip": "State the event."}],
 "model_answer": "An overnight duct fire closed the main kitchen..."}
```

- `numeric.formula` is evaluated by a safe arithmetic evaluator: numbers, variables, `+ - * / ** %`, brackets and `min max abs round sqrt log exp` only. Variables listed in `money_vars` are scaled by `money_scale`. `unit` is `money`, `percent` or `number`.
- `matrix.expected` may also include `rl` and `ri` (residual) on a 1–5 scale.
- `allocate` items: keep to 16 or fewer (the optimum is found by exact enumeration).
- `write` scoring is keyword-based and the game says so. Give several synonyms per element and always provide a strong `model_answer`.

## Effects

Effects can sit on options, on `outcome.good_effects` / `bad_effects`, on `on_complete`, and on allocate's `effects_per_item`.

```json
{"org":   {"cash": -18000, "reputation": 2, "compliance": 1, "control_effectiveness": 1,
           "resilience": 1, "morale": -1, "risk_exposure": -2},
 "trust": {"cfo": 3, "coo": -2},
 "flags": ["duct_warning_ignored"],
 "schedule": [{"event": "ev_kitchen_fire", "after": 2, "p": 0.3}],
 "cancel": ["ev_kitchen_fire"],
 "budget": -10000}
```

Money in `org.cash` and `budget` is in reference units (it is scaled). Scheduled `event` ids must exist in `events.json` → `scheduled`. Flags can unlock or lock later missions (`requires.flags_all` / `flags_none`) and pick endings.

## Endings

`endings` are checked in the order listed, and the first one that matches wins, so list them from the highest `min_score` down. An ending can also require flags with `flags_all`, `flags_any` or `flags_none`, so it only applies when the player made a particular decision (for example a cover-up ending). If nothing matches, a neutral "Assignment closed" ending is used.

## Other content files

| File | Contains |
|---|---|
| `orgs.json` | Organisations: `industry`, `geography`, `currency`, `money_scale`, starting `metrics`, `people` (role → name/title), and the ids of their risks, KRIs, controls and processes |
| `risk_library.json` | Register entries: title, cause/event/consequence, category, inherent and residual ratings, owner role |
| `kri_library.json` | KRIs: unit, baseline, warning, critical, direction, drift, volatility, escalation |
| `control_library.json` / `bia_library.json` | Controls (type, frequency, evidence) and BIA processes (impact curve, MTPD/RTO/RPO, dependencies) |
| `events.json` | `scheduled` (delayed consequences) and `random` (monthly industry events with `p_month`) |
| `concepts.json` | Review cards: question, options, answer, explanation |
| `achievements.json` | `{id, title, description, category, hidden?, condition: {type, ...}}` (see the design doc for the condition types) |
| `interview.json` | Interview question pools by career stage |
| `careers.json` | Levels, salary bands (illustrative, in USD), required missions, capstones, competency minimums by path, tracks, geographies, executive paths |

## Quality checklist

- [ ] Each mission teaches one or two concepts, and its debrief states them.
- [ ] Options are plausible. The weak options are mistakes real professionals make, not strawmen.
- [ ] Every option has feedback that explains the reasoning.
- [ ] All money uses `{m:...}`, and figures are sensible after scaling.
- [ ] Ethical shortcuts are never the strongest option.
- [ ] No real company, person or regulator is portrayed as acting wrongly. Use the fictional organisations.
- [ ] `pytest tests/test_content.py` passes.
