# Dissecting the Claude protein binder design prompts

View at: [https://pansapiens.github.io/claude-protein-design-prompt/](https://pansapiens.github.io/claude-protein-design-prompt/)

This is a dissection of the protein binder design campaign prompts Anthropic released as
[**Anthropic/claude-protein-binder-design**](https://huggingface.co/datasets/Anthropic/claude-protein-binder-design):
16 single-target prompts, one multi-target prompt, two kickoff messages, and a 1.1 GB
reference corpus.

The two-pane viewer displays the prompt text on the left, per-block annotations on the right, and
a navigation overview between them.

The 50 clauses enforced *mechanically* are also reconstructed as Python, readable side by side
with the prose.
---

## Getting the source bundle

The original release bundle from Anthropic is not included in this repository. You can download it directly from Hugging Face:

```bash
curl -L -o protein_binder_design_prompts_release.zip \
  https://huggingface.co/datasets/Anthropic/claude-protein-binder-design/resolve/main/prompts/protein_binder_design_prompts_release.zip

unzip -q protein_binder_design_prompts_release.zip
rm protein_binder_design_prompts_release.zip
```

The zip is ~1.16 GB and already contains a top-level `protein_binder_design_prompts_release/` directory
that unpacks directly into the layout `build.py` expects. Afterwards you should have:
```
protein_binder_design_prompts_release/
├── MANIFEST.sha256
├── README.md
├── REDISTRIBUTION_NOTES.csv
├── prompts/
│   ├── single_target/          16 per-target campaign prompts
│   ├── multi_target_binder_design_prompt.md
│   └── kickoff/
└── corpus/                     339 files of reference material
```

---

## Build and view

```bash
python3 build.py      # regenerates index.html and runs every assertion
xdg-open index.html   # or just double-click it
```

Standard library only - no `pip install` required. Vue 3 loads from a CDN when opening the
page. A successful build prints:

```
blocks: single=170 multi=184  sections=32
annotations: single=170/170 multi=184/184 (142 inherited, 42 authored)
pycode: 51 region(s) across 9 module(s) covering 50/50 MECHANICAL blocks
        24 checks passed; every region round-trips through the highlighter
template slots: 36 varying line(s) across 16 prompts -> 6 slot(s)
fidelity: 354 blocks round-trip from index.html
```

---

## Using the viewer

Four views, selectable from the header:

**Single target** and **Multi target** place the prompt beside its annotations. Selecting either
side highlights the pair; scrolling the prompt keeps the annotation pane anchored to the active block.

The **centre rail** displays one tick per block weighted by normative force: solid for
`MECHANICAL`, hairline for `SHOULD`, hollow for `MAY`. It indicates overall progress and shows how
machine-checked clauses cluster across sections.

**As Python** switches each annotation card to its corresponding code, with clickable chips
for cross-block references. **Δ Scaling** displays every difference between the two prompts with
word-level diffs. **Flow** diagrams agent authority across dispatches, reads, writes, and terminations
(20 nodes, 39 rules); click any node to view its rules, each linking to its prompt block and verbatim quote.

Filters dim non-matching blocks to maintain document continuity. `j`/`k` step through blocks,
`/` searches, `p` toggles Python, and `Esc` clears.
---

## Dissection findings

**The 16 single-target prompts are one template with six slots.** Diffing all 16 yields 36
varying lines; 29 of those simply renumber the shared reference list. The functional
slots are `TASK_TARGET`, `TARGET_DOSSIER`, `COMPETITION_REFS`, `CONSTRUCT_CLAUSE` (Cas9
only), `OLIGOMER_CLAUSE`, and `SELECTIVITY_CLAUSES` (the two GDF-8 prompts only). Annotating
one prompt covers the entire set. The build re-derives this table on every run.

**The multi-target prompt is the same document under a scaling vector.** 16 changed regions
cover 28 of 170 blocks. One change is structural: a 14-row target table replaces the
single-target dossier paragraph. Every other change is a substituted constant: $10k to $50k,
24h to 48h, governor 150 to 325, and 20k–200k to 100k–1M designs. Every method, threshold,
gate, formula, deliverable, and safety clause is byte-identical between the $10,000 campaign and
the $50,000 one. Three of the 16 flagged regions are straight versus curly quotation marks.

**Roughly a third of the prompt is machine-checked rather than instructed.** Classifying
every block by normative force yields 50 `MECHANICAL`, 81 `MUST`, 33 `SHOULD`, and 6 `MAY`.
The mechanical clauses specify code the agent is required to write (`submit_gate()`, the
sheet writer's gate recompute, and `/state/gates/{target}.json`), enforcing constraints directly
in execution rather than relying on prompt adherence.

**The 50 mechanical clauses form an executable package.** All 50 clauses are reconstructed in
`pycode/` as an importable package with a shared vocabulary. The build identifies 41 cross-references
between blocks. This exposes the structural relationship between clauses: in prose, the selection
caps (st-92) and pre-order re-check (st-246) appear redundant, but in code st-246 is an explicit
call to st-92 passing the final selected set.

Evaluating that arithmetic also exposed an internal inconsistency in the prompt itself. Its stated
"1.58x even-pace" for the bootstrap ceiling is 150/95 (the ratio against a rounded figure
in the prose), while the `floor()` rule in the same block produces 94, giving 1.60x.
This discrepancy is small in budget terms and is flagged rather than altered.
Full detail, tables and method in [ANALYSIS.md](ANALYSIS.md).

---

## Layout

```
build.py                  generates index.html; the only writer of it
viewer.tmpl.html          the viewer's HTML/CSS/JS; build.py injects JSON into it
index.html                generated, self-contained, opens on file://
annotations/
  single_target.json      170 block annotations for 15-PGDH.md
  multi_target.json       42 authored; the other 142 blocks inherit by exact text match
  flow_authority.json     the Flow tab's graph; every edge quotes its block verbatim
pycode/                   the 50 MECHANICAL blocks as one Python package + its selftest
ANALYSIS.md               the written dissection
CLAUDE.md                 repo conventions
plans/                    approved implementation plans, plus plan-overview.md (status)
                          and plan-original-brief.md (the original brief, verbatim)
```

Annotations are authored in `annotations/*.json` and embedded near the top of the generated
`index.html` as pretty-printed JSON, so they can also be read and hand-edited there.

### Build assertions

The build fails on any contract violation:

- **Fidelity.** Block text is parsed back out of the generated HTML and must match the
  source markdown exactly. No prompt text is paraphrased, reformatted, or elided anywhere in
  the viewer: the left pane renders the source bytes.
- **Coverage.** Every block must have an annotation, and every tag, force, and owner must be
  in the declared vocabulary.
- **Slots.** The template-slot table is re-derived from all 16 prompts each run; a varying
  line that no rule classifies fails the build instead of being ignored.
- **Code.** Every `MECHANICAL` block must have a `pycode/` region, every module must
  compile, every region must round-trip through the syntax highlighter byte-for-byte, and
  `pycode/selftest.py` must pass.
---

## Python reconstruction

`pycode/` is an analytical reconstruction for reading rather than a live campaign execution
environment; `pycode/external.py` stubs provider and harness surfaces so the package imports
and its pure logic can be exercised. Its purpose is to make the prompt's arithmetic and control
flow legible, and `pycode/selftest.py` verifies that the implementation computes what the
prompt states.

## Licensing

This repository contains original analysis, annotations, and tooling. The prompts and
reference corpus are not redistributed here: download them from
[the dataset](https://huggingface.co/datasets/Anthropic/claude-protein-binder-design).
See its `README.md` and `REDISTRIBUTION_NOTES.csv` for license terms governing the reference
corpus, which contains third-party material under diverse licenses.
