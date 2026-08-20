# claude-protein-design-prompt

Dissection and annotation of the prompts from
[Anthropic/claude-protein-binder-design](https://huggingface.co/datasets/Anthropic/claude-protein-binder-design).
The deliverable is `index.html`: a two-pane viewer with the prompt on the left and per-block
annotation on the right.

## Hard rules

**`protein_binder_design_prompts_release/` is read-only.** It is the upstream release bundle,
1.1 GB, with a `MANIFEST.sha256`. Never write, move, rename, or reformat anything inside it. All
analysis reads from it; nothing writes to it.

**`build.py` is the only writer of `index.html`.** Do not hand-edit `index.html` and expect it to
survive — the next build overwrites it. Annotations are authored in `annotations/*.json`.

**Prompt text is never paraphrased into the viewer.** The left pane renders the source bytes.
`build.py` asserts a round-trip: text extracted back out of the generated HTML must match the
source `.md` exactly (modulo HTML escaping).

## Layout

```
build.py                    generates index.html from annotations/ + the release bundle
viewer.tmpl.html            the viewer's HTML/CSS/JS; build.py injects JSON into its two
                            placeholders (/*__ANNOTATIONS__*/ and /*__PAYLOAD__*/).
                            Edit UI here, never in index.html.
index.html                  generated; self-contained, opens on file:// with no server
annotations/
  single_target.json        block records for prompts/single_target/15-PGDH.md
  multi_target.json         block records for prompts/multi_target_binder_design_prompt.md
pycode/                     the MECHANICAL clauses re-coded as one importable package;
                            the viewer's "As Python" tab renders regions out of it
ANALYSIS.md                 the written dissection
plans/                      approved implementation plans, plus the project plans:
  plan-overview.md            project overview and status (rewritten from the original brief)
  plan-original-brief.md      the user's original brief, verbatim. Not a generated backup --
                              it is the only copy, so never overwrite it (note that /compress
                              would target this exact filename if run on plan-overview.md).
protein_binder_design_prompts_release/   READ ONLY upstream bundle
```

## The two source documents

- `prompts/single_target/15-PGDH.md` — 264 lines, **170 non-blank blocks**, 32 labelled sections.
  Canonical: the other 15 single-target prompts are the same file with 6 slots substituted
  (`TASK_TARGET`, `TARGET_DOSSIER`, `COMPETITION_REFS`, `CONSTRUCT_CLAUSE`, `OLIGOMER_CLAUSE`,
  `SELECTIVITY_CLAUSES`). The slot table is re-derived from all 16 files on every build — do not
  hand-maintain this list; read it off `build.py`'s output.
- `prompts/multi_target_binder_design_prompt.md` — 288 lines, **184 non-blank blocks**, 32 sections.
  Differs from the single-target prompt in only 16 regions, almost all scalar
  ($10k→$50k, 24h→48h, governor 150→325, …).

## Segmentation contract

- **block = one non-blank line.** Every paragraph and every list item in these files is exactly one
  physical line, so this is lossless.
- **block id = `st-<line>` / `mt-<line>`**, 1-based line number in the source file. Stable, because
  the sources are frozen release artifacts.
- **depth** = leading-whitespace run mapped to 0–3 (0 / 3 / 4 / 7 spaces observed).
- **section** = the most recent preceding line matching `^[A-Z][A-Za-z ,*/-]{2,45}:`, slugified.

If a build assertion about these counts fails, the upstream bundle changed — investigate before
adjusting the numbers.

## Annotation record

```json
{
  "title": "short imperative or noun phrase, sentence case",
  "note":  "1-3 sentences: what this block does and why it is there",
  "tags":  ["scoring", "gate"],
  "force": "MECHANICAL | MUST | SHOULD | MAY",
  "owner": "orchestrator | SETUP | BUDGET | WATCHDOG | CLOCK | SCRIBE | DISPATCH | DELIVERABLES | monitor | sheet-writer | any-agent"
}
```

`force` is the axis the viewer's centre rail visualises:

- `MECHANICAL` — enforced by code the agent is required to write (`submit_gate()`, the sheet
  writer's gate recompute, `/state/gates/{target}.json`). Not merely disallowed — impossible.
- `MUST` — hard obligation, enforced by review or report.
- `SHOULD` — strong default with a disclosed-deviation path.
- `MAY` — explicit latitude.

Coverage is enforced: `build.py` fails if any block lacks an annotation, and if any annotation
references a block id, tag, force, or owner outside the vocabularies above.

## The `pycode/` layer

Every `MECHANICAL` block is re-coded as Python in `pycode/`, and the viewer shows it under
an **As Python** tab on the annotation card. This is a *reconstruction for reading*, not
the campaign's implementation: `pycode/external.py` stubs `host`/`modal`/Slack/Drive so
the package imports and its pure logic can be exercised.

The point of a single package rather than 50 snippets is that the blocks share a
vocabulary. `submit_gate()` is defined once (st-137) and called from the dispatcher
(st-65) and the validation gate (st-111); `enforce_selection_caps()` (st-92) is re-run by
the pre-order re-check (st-246) and re-parameterised by the relaxation ladder (st-185).
The build derives those links and the card renders them as clickable chips, so **do not
inline a shared rule** — import it, and the cross-reference appears for free.

Regions are marked with a comment naming the block they encode:

```python
# @block st-92 kind=logic
def enforce_selection_caps(...): ...
```

A region runs to the next `# @block` or end of file. Multiple regions may name the same
block (st-137 has two — the governor file, then the gate function). `kind` is one of:

- `logic` — an algorithm: thresholds, ordering, arithmetic, control flow
- `schema` — a frozen data shape: columns, dtypes, required keys
- `config` — a pinned recipe: flags, versions, paths
- `protocol` — a contract between agents: who may write what, in what order
- `lint` — a rule about the campaign's own source, checkable statically

`build.py` enforces, and fails on any of these:

- every `MECHANICAL` block has at least one region (`load_pycode` asserts coverage)
- every `@block` id exists in one of the prompts, and every marker carries one valid `kind`
- every module compiles
- `python3 -m pycode.selftest` exits 0 — it checks that the arithmetic the prompt states
  is the arithmetic the code computes (the 4:1 weighting, the burn-rate adders, the six
  caps, the rank key, the WATCHDOG ladder)
- each region round-trips through the syntax highlighter byte-for-byte

Multi-target blocks do not get their own code: they alias the single-target region, either
outright (byte-identical text) or flagged `rescaled` (same code, different constants).

## Tag vocabulary

`framing` `objective` `target-biology` `reference` `corpus` `tooling` `installation` `licensing`
`design-method` `sequence-design` `filtering` `scoring` `metric` `calibration` `gate`
`diversity-cap` `provenance` `data-retention` `compute` `budget` `concurrency` `orchestration`
`delegation` `cadence` `reporting` `deliverable` `verification` `epistemics` `failure-handling`
`isolation` `safety`

Add a tag only if at least three blocks need it; otherwise reuse an existing one.

## Build and preview

```bash
python3 build.py          # regenerates index.html, runs all assertions
xdg-open index.html       # no server needed
```

Stdlib only — no pip install. Vue 3 comes from a CDN at view time.

## Frontend conventions

Plain JavaScript (per the `vue-preferences` skill: CDN project ⇒ JS, not TS). Vue 3 global build,
components as template strings, no SFC loader, no UI framework. Light theme is the default.
Annotation JSON lives near the top of `index.html` in a `<script type="application/json">` block,
pretty-printed, so it can be read and edited by hand.
