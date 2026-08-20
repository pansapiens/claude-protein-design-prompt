# Prompt Dissection Viewer — implementation plan

## Context

`protein_binder_design_prompts_release/` is the HuggingFace release bundle for Anthropic's
`claude-protein-binder-design` campaign: 16 single-target prompts, one multi-target prompt, two
kickoff messages, and a 1.1 GB reference corpus. Each prompt is a ~112 KB, 264-line document that
functions less like a prose brief and more like an **operations order with machine-checked
invariants** — it specifies gate functions by pseudocode, freezes scoring formulas, names exact CLI
flags, sets budget-governor arithmetic, and defines a sub-agent org chart.

`PLAN.md` asks to dissect that document into logical sections, annotate each with purpose and tags,
identify its template slots and code-like constructs, and ship a two-pane Vue viewer (prompt left,
annotation right, bidirectional click-to-highlight) with a clean minimal light theme.

Nothing has been built yet. This plan covers the analysis, the data model, and the viewer.

---

## What the exploration established

These are measured facts, not assumptions — they shape the whole design.

### The 16 single-target prompts are one template with ~5 slots

`diff` across all 16 files against `15-PGDH.md` yields 28–71 differing lines, and almost all of that
is **renumbering of the shared 29-item reference list**, not new content. The genuine slots are:

| Slot | Location (15-PGDH line) | Varies how |
|---|---|---|
| `TASK_TARGET` | 3 | Target name/synonyms; GDF-8 variants add a counter-target and a 3rd goal (selectivity) |
| `TARGET_DOSSIER` | 5 | UniProt ID, oligomeric state, cofactor, assay-construct note |
| `COMPETITION_REFS` | 5 → 9 | 0–4 target-specific refs prepended, shifting the master list's numbering |
| `OLIGOMER_CLAUSE` | 117 | `(15-PGDH is a homodimer)` / `(GDF-8 and GDF-11 are homodimers)` / omitted |
| `SELECTIVITY_CLAUSES` | 111, 127, 246 | Only present on the two GDF-8 prompts (counter-screen arm, selectivity-weighted score) |

So annotating `15-PGDH.md` genuinely covers all 16. Confirms PLAN.md's hypothesis.

### The multi-target prompt is the same document under a scaling vector

`difflib` over non-blank lines: **only 16 changed regions out of ~170 blocks**. One is the 14-target
table replacing the single-target dossier. The rest is scalar substitution:

| Parameter | Single | Multi |
|---|---|---|
| Budget | $10,000 | $50,000 |
| Wall clock | 24 h | 48 h |
| Concurrency governor ceiling | 150 | 325 |
| `host.compute.set_concurrency_limit` cap | 200 | 450 |
| Designs generated/screened | 20k–200k | 100k–1M |
| Peak concurrent agents | >50 | >100 |
| Close-out reserve | final hour | final three hours |
| Design sheet | 30 designs | 30 designs **per target** |
| Optimization rounds | ≥5 | ≥2/target, ≥5 on hard targets |
| Slack header / volume slug | includes `<target>` | `<target>` dropped |

Every methodological, scoring, gating, verification, and safety clause is **byte-identical**. That is
the headline finding and the viewer should make it visible rather than bury it in a diff.

### Structure to parse against

- 264 lines / **170 non-blank blocks** (single); 288 lines / **184 blocks** (multi).
- **32 labelled sections** in each, marked by a leading `Label:` (`Addressing:`, `Task:`,
  `Models and Tools:`, `Compute:`, `Deliverables:`, `Delegation:`, `Verification:`, `Safety:` …).
- Every paragraph and every list item is exactly one physical line, so **block = non-blank line**
  is an unambiguous segmentation, and the line number is a stable ID (the source files are frozen
  release artifacts with a `MANIFEST.sha256`).
- Nesting is encoded by leading whitespace (0 / 3 / 4 / 7 spaces → depth 0–3).

### Skill availability

`frontend-design` is **not** in the Skill tool's listing, but it is installed at
`~/.claude/skills/frontend-design/SKILL.md` and I read it directly; its guidance is applied below.
`vue-preferences` is available and says: CDN project ⇒ plain JavaScript.

---

## Deliverables

1. `index.html` — self-contained single-page viewer. Vue 3 from CDN, plain JS, no build step at
   view time, opens by double-click (`file://`, no server needed).
   Annotation data sits **near the top as pretty-printed JSON** inside
   `<script type="application/json" id="annotations">`, per your instruction — indented, one object
   per block, trivially hand-editable.
2. `build.py` — assembles `index.html` from the annotation sources + the two prompt `.md` files.
   Keeps `index.html` reproducible and keeps me from hand-emitting 225 KB of prompt text.
3. `annotations/single_target.json`, `annotations/multi_target.json` — the authored annotation
   corpus (source of truth for the build).
4. `ANALYSIS.md` — the written dissection: template-slot table, scaling-vector table, tag taxonomy,
   and the structural argument about what kind of document this is.
5. `CLAUDE.md` — repo conventions: the frozen-artifact rule
   (`protein_binder_design_prompts_release/` is read-only), block-id scheme, tag/force/owner
   vocabularies, `build.py` is the only writer of `index.html`, and how to preview.
6. `PLAN.md` — rewritten in place to carry the expanded brief (findings + taxonomy + deliverables),
   so the original brief file stays the entry point rather than going stale next to `ANALYSIS.md`.

---

## Analysis model

### Per-block record

```json
{
  "id": "st-117",
  "line": 117,
  "section": "additional-cofolding-considerations",
  "depth": 1,
  "tags": ["scoring", "mechanical", "target-shape"],
  "force": "MUST",
  "owner": "sheet-writer",
  "slot": "OLIGOMER_CLAUSE",
  "diff": "scaled",
  "title": "Oligomeric targets: score at 1:N and N:N",
  "note": "Design may crop protomers; scoring may not. …"
}
```

### Tag vocabulary (facet 1 — subject)

Grounded in what the document actually contains, not a generic list:

`framing` · `objective` · `target-biology` · `reference` · `corpus` · `tooling` · `installation` ·
`licensing` · `design-method` · `sequence-design` · `filtering` · `scoring` · `metric` ·
`calibration` · `gate` · `diversity-cap` · `provenance` · `data-retention` · `compute` · `budget` ·
`concurrency` · `orchestration` · `delegation` · `cadence` · `reporting` · `deliverable` ·
`verification` · `epistemics` · `failure-handling` · `isolation` · `safety`

### Normative force (facet 2 — the signature axis)

The most interesting property of this prompt is that its rules are not uniformly soft. Four levels,
assigned per block:

- **MECHANICAL** — enforced by code the agent must write (`submit_gate()`, the sheet writer's
  gate-recompute, `/state/gates/{target}.json`). Violation is impossible, not merely disallowed.
- **MUST** — hard obligation, enforced by review/report.
- **SHOULD** — strong default with a disclosed-deviation path.
- **MAY** — explicit latitude.

### Owner (facet 3)

`orchestrator` · `SETUP` · `BUDGET` · `WATCHDOG` · `CLOCK` · `SCRIBE` · `DISPATCH` ·
`DELIVERABLES` · `monitor` · `sheet-writer` · `any-agent`

### Inline entity classes (the "code-like constructs" highlight layer)

Tokenised by an ordered regex pass in `build.py`, emitted as `<span class="ent ent-*">`:

| Class | Examples |
|---|---|
| `placeholder` | `<target>`, `<SLACK_CHANNEL_ID>`, `<Campaign Deliverables Folder>`, `<frameid8>` — 20 distinct, inventoried |
| `slot` | the 5 target-varying regions above (highlighted differently from operator placeholders) |
| `constant` | `$10,000`, `150`, `0.23`, `60%`, `1e-4`, `24 hours`, `20,000 to 200,000`, `5400s` |
| `identifier` | `submit_gate()`, `modal.Sandbox.create()`, `host.delegate`, `wait_for_notification`, `sb.terminate()` |
| `artifact` | `/state/governor.json`, `/state/gates/{target}.json`, `lib/submit_gate.py`, `per_seed_metrics.parquet`, `instrument_realization.csv`, `method_vocab.json` |
| `tool` | roster models — `RFdiffusion3`, `BoltzGen`, `ESMFold2-Full`, `Protenix v2`, `SolubleMPNN`, `ipSAE`, `DockQ`, `MMseqs2` … |
| `metric` | `ipSAE_min`, `sc_DockQ`, `pose_dockq`, `rank_zscore`, `final_score`, `lcp_score`, `pLDDT`, `TM-score` |
| `role` | `SETUP`, `BUDGET`, `WATCHDOG`, `CLOCK`, `SCRIBE`, `DISPATCH`, `DELIVERABLES` |
| `citation` | markdown links → rendered `<a>`, plus corpus folder names (`"07 Prompt-Cited Papers"`) |

Tokeniser detail that matters: build a **single alternation regex** and walk it once over the raw
block text, escaping each segment as it is emitted. Do not regex over already-generated HTML, and
handle markdown links before any other class so link text isn't shredded.

---

## Viewer

### Layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  15-PGDH · single-target      [ Single ][ Multi ][ Δ Scaling ]      ⌕ search  │  header
├───────────────────────────────────────┬──┬───────────────────────────────────┤
│                                       │▍ │                                   │
│  Task: Autonomously de novo design    │▍ │  ┌─ OBJECTIVE ─ MECHANICAL ─────┐ │
│  miniprotein binders against          │  │  │ Defines the campaign in one  │ │
│  ⟦human 15-PGDH (15-PGDH / HPGD)⟧ …   │▍ │  │ sentence. Slot: TASK_TARGET. │ │
│                                       │▍ │  │ #objective #framing          │ │
│  Human 15-PGDH (UniProt ⟨P15428⟩) …   │  │  └──────────────────────────────┘ │
│                                       │▍ │                                   │
│  left pane: prompt, block-segmented   │▲ │  right pane: annotation cards     │
│                                       │  │                                   │
└───────────────────────────────────────┴──┴───────────────────────────────────┘
                                    enforcement rail
```

**The signature element is the centre rail.** A ~14 px column between the panes carrying one tick per
block, weighted by normative force (solid bar = MECHANICAL, medium = MUST, hairline = SHOULD, hollow
= MAY). It is simultaneously a minimap, a scroll position indicator, and a visualisation of a real
property of the document: the density of machine-enforced clauses is wildly uneven, and the rail
shows that at a glance. Structure encoding content, not decoration.

Everything else stays quiet: no cards-with-shadows, no gradient, no hero stat tiles.

### Interaction

- Click a block → its annotation card activates, both panes scroll it into view.
- Click a card → same, reversed. Rail tick is a third entry point.
- Keyboard: `↑`/`↓` prev/next block, `/` focus search, `Esc` clear. Visible focus ring.
- Filter chips for tags + force; non-matching blocks dim (never hide — the document's continuity is
  part of what's being read).
- Search filters annotations and prompt text, with hit count.
- Legend for the entity colours, collapsed by default.
- `prefers-reduced-motion` respected; scroll-into-view falls back to instant.

### Δ Scaling view

Third mode. Left pane shows only the 16 changed regions, aligned single ↔ multi with precomputed
word-level `difflib` highlights; right pane shows the scaling-vector table. This is where the
"one document, two budgets" finding lands.

### Design tokens

Deliberately **not** the cream-paper/serif/terracotta default. Register is *technical protocol
document*, cool and precise:

- Paper `#FBFBFC`, ink `#12151A`, secondary ink `#5A6270`, rule `#E4E6EB`.
- Accents drawn from the document's own vocabulary: gate green `#1B6B52`, deviation amber `#9A6100`,
  selection indigo `#2F4FD8`.
- Entity hues: low-saturation, ≥4.5:1 on paper, distinguishable without relying on hue alone
  (each also carries a weight or underline treatment).
- Type: **IBM Plex Sans** body / **IBM Plex Mono** for section labels, entities, tags and the rail
  legend — the mono is the personality, since every code-like construct in this document *is* mono
  by nature. Section labels set in mono, uppercase, tracked. Google Fonts with system fallbacks.
- Measure capped ~72ch in the left pane; the right pane narrower. Zero border-radius on the rail,
  small radius elsewhere.
- Light theme default (as specified); a dark toggle only if it costs nothing.

### Tech

Vue 3 global build from CDN (`vue.global.prod.js`), plain JavaScript, no SFCs, no UI framework — the
component count is ~6 and PrimeVue/shadcn would bring more weight than value here. Components
defined with template strings in an inline `<script>`.

---

## Files

```
claude-protein-design-prompt/
├── CLAUDE.md                        (new)
├── PLAN.md                          (unchanged — original brief)
├── ANALYSIS.md                      (new)
├── index.html                       (new — generated, self-contained viewer)
├── build.py                         (new)
├── annotations/
│   ├── single_target.json           (new — 170 block records)
│   └── multi_target.json            (new — 184 block records, reusing shared text)
└── protein_binder_design_prompts_release/    ← READ ONLY, never modified
```

`build.py` responsibilities:
1. Read `prompts/single_target/15-PGDH.md` and `prompts/multi_target_binder_design_prompt.md`.
2. Segment into blocks (non-blank line + depth from leading whitespace), assign sections from
   `^Label:` markers.
3. Tokenise each block into entity spans.
4. Compute the single↔multi alignment with `difflib.SequenceMatcher` over non-blank lines, plus
   word-level opcodes inside each changed pair.
5. Recompute the 5 template slots by diffing all 16 single-target files (so the slot table is
   derived from the files, not hardcoded).
6. Merge annotations by block id; **fail loudly on any block with no annotation** so coverage is
   provable rather than assumed.
7. Emit `index.html` with the annotation JSON pretty-printed near the top.

---

## Execution order

1. `CLAUDE.md` + `build.py` skeleton with the parser; verify segmentation counts (170 / 184 / 32
   sections each).
2. Entity tokeniser + a coverage report (which entities matched how often) to tune the regexes.
3. Read `15-PGDH.md` end to end and author `annotations/single_target.json` — all 170 blocks. This
   is the bulk of the work; done in section-sized passes.
4. Author `annotations/multi_target.json`, inheriting shared-block annotations and writing fresh
   ones only for the 16 changed regions + the 14-target table.
5. Viewer HTML/CSS/JS; build; screenshot-and-critique pass.
6. `ANALYSIS.md`.
7. Log the project to the `agent-project-log` MCP (per your global instruction — deferred to now
   because plan mode blocks writes).

---

## Verification

- `python3 build.py` exits 0 and asserts: 170 single blocks, 184 multi blocks, 32 sections each,
  100% annotation coverage, every `section` value resolving to a known section.
- Re-derive the slot table from all 16 files and assert it matches the 5 slots above — if a 17th
  prompt were ever added, the build fails rather than silently under-reporting.
- Open `index.html` directly from the filesystem (no server) and confirm it renders; drive it with
  the `browser-tools` skill to check: click block → card activates and scrolls; click card →
  reverse; tag filter dims correctly; search returns hits; Δ mode renders all 16 regions; keyboard
  nav and focus rings work; layout holds at 1280 px and at 768 px.
- Verify no prompt text was altered: extract the rendered block text back out of `index.html` and
  diff it against the source `.md` — must be byte-identical modulo escaping.
- Confirm `protein_binder_design_prompts_release/` is untouched via `MANIFEST.sha256`.

---

## Out of scope

- The other 14 single-target prompts as loadable documents (covered by the slot table, per your
  answer).
- The kickoff messages and the 1.1 GB corpus — referenced in annotations, not rendered.
- Any write to `protein_binder_design_prompts_release/`.
- A round-trip editor that writes annotations back from the browser.
