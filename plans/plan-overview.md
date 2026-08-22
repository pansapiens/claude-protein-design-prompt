# Protein Design Prompt Dissection and Modularization

Source material: the prompts and reference corpus from
<https://huggingface.co/datasets/Anthropic/claude-protein-binder-design>, vendored unmodified at
`protein_binder_design_prompts_release/` (339 files, 1.1 GB, checksums verified against
`MANIFEST.sha256`).

## Goal

Dissect the campaign prompt into logical sections, annotate the purpose of each, identify the
template slots and code-like constructs inside it, and ship a two-pane viewer: prompt on the left,
annotation on the right, bidirectional click-to-highlight, clean minimal light theme.

## Status: built

| Artifact | What it is |
|---|---|
| `index.html` | The viewer. Self-contained, opens on `file://` with no server. Generated. |
| `build.py` | Generates `index.html` from the release bundle + `annotations/`. Stdlib only. |
| `annotations/single_target.json` | 170 block annotations for `15-PGDH.md`. |
| `annotations/multi_target.json` | 42 authored annotations for the multi-target prompt; the other 142 blocks inherit by exact text match. |
| `annotations/dspy_roles.json` | A second facet over the same 170 blocks: what each would be as a DSPy program, with the evidence for the claim. |
| `pycode/` | All 50 `MECHANICAL` blocks re-coded as one importable Python package, rendered by the viewer's **As Python** tab. |
| `dspy_slice/` | The DSPy feasibility experiment: one slice rebuilt as a program, plus a counterexample chosen to fail. Not part of the build. |
| `ANALYSIS.md` | The written dissection: findings, tables, method. |
| `CLAUDE.md` | Repo conventions and the frozen-artifact rule. |

```bash
python3 build.py      # regenerate, runs every assertion
xdg-open index.html
```

## What the dissection established

**The 16 single-target prompts are one template with six slots.** 36 varying lines across all 16
files, of which 29 are the shared 29-item reference list renumbering itself. The real slots are
`TASK_TARGET`, `TARGET_DOSSIER`, `COMPETITION_REFS`, `CONSTRUCT_CLAUSE` (Cas9 only),
`OLIGOMER_CLAUSE`, and `SELECTIVITY_CLAUSES` (the two GDF-8 prompts only). So annotating
`15-PGDH.md` covers the set — as the original brief guessed.

**The multi-target prompt is the same document under a scaling vector.** 16 changed regions
covering 28 of 170 blocks. One is structural (a 14-row target table replacing the dossier
paragraph); every other change is a substituted constant — $10k→$50k, 24h→48h, governor 150→325,
20k–200k→100k–1M designs. Methods, scoring, gating, verification and safety are byte-identical
between a $10,000 campaign and a $50,000 one. Three of the 16 "changes" are curly-vs-straight
quotation marks only.

**A third of the prompt is machine-checked, not merely instructed.** Classifying every block by
normative force gives 50 `MECHANICAL` / 81 `MUST` / 33 `SHOULD` / 6 `MAY`. The mechanical clauses
specify code the agent must write — `submit_gate()`, the sheet writer's gate recompute,
`/state/gates/{target}.json` — which then enforces the rule regardless of what the agent remembers.
This is the axis the viewer's centre rail visualises.

**The mechanical clauses survive being taken literally.** All 50 were re-coded as one
Python package (`pycode/`), and the build enforces it: every module compiles, every
`MECHANICAL` block has a region, and a 24-check selftest asserts the arithmetic the prompt
states is the arithmetic the code computes. 29 regions are algorithms, 12 are inter-agent
protocols, 6 are schemas, 2 are static lint rules over the campaign's own source, and only
2 — the install recipes — are a stretch. The build derives 41 cross-references between
blocks, which is the structural finding: several apparent repetitions in the prompt are
one rule invoked at a second point, not a second rule.

**Normative force is almost independent of decidability.** A second classification asks what
each block would be in a [DSPy](https://github.com/stanfordnlp/dspy) program — `code`, `metric`,
`signature`, `scaffolding`, `corpus`, `inert` or `unclear` — and the build refuses a claim without
its evidence: `metric` needs a predicate naming a concrete artifact, `signature` needs its output
fields, `scaffolding` needs the DSPy capability it lacks. The two axes agree at the extremes
(`MECHANICAL` is two-thirds `code`, `SHOULD` nine-tenths `corpus`) and disagree in the middle:
`MUST` scatters across five roles with no majority. Only **11 blocks are genuine judgment sites**,
ten of them epistemic rather than scientific, and `scaffolding` — the campaign machinery DSPy
cannot express at all — is 25% of the document by text. Method and verdict in
[dspy_slice/README.md](dspy_slice/README.md).

Full detail, tables and method in [ANALYSIS.md](ANALYSIS.md).

## Viewer design

Three views: **Single target**, **Multi target**, **Δ Scaling**.

- Left pane renders the prompt segmented into blocks, grouped under its 32 labelled sections, with
  inline entities highlighted. Right pane carries one annotation card per block with force, owner
  and tags. Clicking either side selects the pair and centres both; scrolling the prompt keeps the
  annotation pane anchored to the same block.
- **The centre rail** is the signature element: one tick per block, weighted by normative force
  (solid = `MECHANICAL`, hairline = `SHOULD`, hollow = `MAY`). It doubles as a minimap and a
  scroll-position indicator, and it makes the uneven density of machine-checked clauses visible at
  a glance.
- Filters by force, tag and DSPy role dim non-matching blocks rather than hiding them, so the
  document's continuity survives filtering. Search covers prompt text and annotations. `j`/`k`
  step, `/` focuses search, `Esc` clears. A **Highlight** toggle strips entity colouring for
  plain reading.
- **The DSPy role** rides as a badge on each card with its evidence — the predicate, the output
  fields, or the missing capability — printed under the note. The rail can be recoloured to the
  role axis instead of force, which is how the disagreement between the two becomes visible.
- **As Python** turns the annotation card into the block's own code. Every `MECHANICAL`
  block is re-coded in `pycode/`, one package with a shared vocabulary rather than 50
  snippets, so a card can say "calls `submit_gate()`, defined at st-137" and the chip is
  clickable. The header button flips the default; each card can be flipped back
  individually. `p` toggles it.
- **Δ Scaling** shows all 16 changed regions with word-level diffs, alongside the scaling-vector
  table, the derived template-slot table, the encoding breakdown, the enforcement profile, the
  role table and the force×role cross-tab.

Entity classes highlighted inline: operator placeholders (`<SLACK_CHANNEL_ID>`), template slots,
numeric constants, snake_case identifiers and dotted API calls, state artifacts and file paths,
tool and model names, metric names, agent role names, enum literals, and citations. 2,435 matches
across the two prompts.

## Technology

Vue 3 from CDN, plain JavaScript, no build step at view time, no UI framework (per the
`vue-preferences` skill: CDN project ⇒ JS). Visual direction follows the `frontend-design` skill.
Annotations are embedded as pretty-printed JSON near the top of `index.html` so they can be read
and edited by hand.

## Invariants

- `protein_binder_design_prompts_release/` is read-only and is never written to.
- `build.py` is the only writer of `index.html`.
- Prompt text is never paraphrased: the build parses block text back out of the generated HTML and
  asserts it matches the source markdown exactly.
- Annotation coverage is enforced — the build fails on any unannotated block, or any tag, force or
  owner outside the declared vocabulary.
- The template-slot table is re-derived from all 16 files on every run; an unclassifiable varying
  line fails the build rather than being silently absorbed.
- Every `MECHANICAL` block has a `pycode/` region; the build fails on a gap, on a marker
  naming an unknown block, on a module that does not compile, on a failing selftest, or on
  a region that does not round-trip through the syntax highlighter.
- Every block carries a DSPy role, and no role claim is accepted without its evidence — a
  `metric` without a predicate, a `signature` without output fields or a `scaffolding` without
  a named blocker fails the build. Coverage is not to be bought by softening a predicate;
  `unclear` is a legitimate answer and the build prints which blocks use it.

## Not covered

The 1.1 GB reference corpus and the two kickoff messages are referenced in annotations but not
rendered. The other 15 single-target prompts are covered by the slot table rather than loaded as
documents. There is no round-trip editor writing annotations back from the browser.
