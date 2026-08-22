# Dissecting the Claude protein binder design prompts

A close reading of the campaign prompts Anthropic released as
[**Anthropic/claude-protein-binder-design**](https://huggingface.co/datasets/Anthropic/claude-protein-binder-design)
— 16 single-target prompts, one multi-target prompt, two kickoff messages and a 1.1 GB
reference corpus.

The deliverable is **`index.html`**: a two-pane viewer with the prompt on the left, a
per-block annotation on the right, and an enforcement rail between them. It is
self-contained — open it by double-clicking, no server, no build step at view time.

Each of the 264 lines is annotated with what it does, who owns it, and how hard it binds.
The 50 clauses that are *mechanically* enforced are additionally re-coded as Python, which
you can read side-by-side with the prose. A second axis classifies every block by what it
would be if the campaign were rebuilt as a [DSPy](https://github.com/stanfordnlp/dspy)
program — and refuses the label unless the evidence for it is written down.

---

## Getting the source bundle

The release bundle is **not** in this repository — it is 1.1 GB and belongs to its
publisher. Download it from the original source into the repo root:

```bash
curl -L -o protein_binder_design_prompts_release.zip \
  https://huggingface.co/datasets/Anthropic/claude-protein-binder-design/resolve/main/prompts/protein_binder_design_prompts_release.zip

unzip -q protein_binder_design_prompts_release.zip
rm protein_binder_design_prompts_release.zip
```

The zip is ~1.16 GB and already contains a top-level
`protein_binder_design_prompts_release/` directory, so it unpacks straight into the layout
`build.py` expects. Afterwards you should have:

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

Or, via the HuggingFace CLI:

```bash
pip install huggingface_hub
hf download Anthropic/claude-protein-binder-design \
  prompts/protein_binder_design_prompts_release.zip \
  --repo-type dataset --local-dir .
```

(On `huggingface_hub` older than 0.34 the command is `huggingface-cli download`, same
arguments.)

### Verifying the download

`MANIFEST.sha256` uses a three-column format — `sha256  size  path` — so plain
`sha256sum -c` will report every file as failed. Check it like this instead:

```bash
python3 - <<'EOF'
import hashlib, os
root = "protein_binder_design_prompts_release"
bad = n = 0
for line in open(os.path.join(root, "MANIFEST.sha256")):
    parts = line.split()
    if len(parts) < 3:
        continue
    digest, path = parts[0], " ".join(parts[2:])
    h = hashlib.sha256()
    with open(os.path.join(root, path), "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    n += 1
    if h.hexdigest() != digest:
        print("MODIFIED", path)
        bad += 1
print(f"{n} files verified, {bad} modified")
EOF
```

Expect `339 files verified, 0 modified`.

**The bundle is read-only.** Nothing in this repository writes to it; all analysis reads
from it and the build re-verifies its own assumptions about it on every run.

---

## Build and view

```bash
python3 build.py      # regenerates index.html and runs every assertion
xdg-open index.html   # or just double-click it
```

Standard library only — no `pip install`. Vue 3 is loaded from a CDN when you open the
page. A successful build prints:

```
blocks: single=170 multi=184  sections=32
annotations: single=170/170 multi=184/184 (142 inherited, 42 authored)
pycode: 51 region(s) across 9 module(s) covering 50/50 MECHANICAL blocks
        24 checks passed; every region round-trips through the highlighter
dspy roles: code=48, metric=39, signature=11, scaffolding=26, corpus=32, inert=13, unclear=1
            multi-target: 167/184 inherited (142 identical, 25 rescaled)
template slots: 36 varying line(s) across 16 prompts -> 6 slot(s)
fidelity: 354 blocks round-trip from index.html
```

---

## Using the viewer

Three views, switched from the header.

**Single target** and **Multi target** put the prompt beside its annotation. Click either
side to select the pair; scrolling the prompt keeps the annotation pane anchored to the
same block.

The **centre rail** carries one tick per block, weighted by normative force — solid for
`MECHANICAL`, hairline for `SHOULD`, hollow for `MAY`. It is a minimap, a scroll indicator,
and a picture of how unevenly the machine-checked clauses are distributed. It can be
recoloured to the **DSPy role** axis instead, which is how the disagreement between the two
classifications becomes visible.

**As Python** turns each annotation card into that block's code, with clickable chips
showing which other block defines a name it borrows. Each card also carries its DSPy role
and the evidence for it — the predicate, the output fields, or the capability DSPy lacks.
**Δ Scaling** shows every difference between the two prompts with word-level diffs.

Filters dim rather than hide, so the document stays continuous. `j`/`k` step, `/` searches,
`p` toggles Python, `Esc` clears.

---

## What the dissection found

**The 16 single-target prompts are one template with six slots.** Diffing all 16 yields 36
varying lines, and 29 of those are the shared reference list renumbering itself. The real
slots are `TASK_TARGET`, `TARGET_DOSSIER`, `COMPETITION_REFS`, `CONSTRUCT_CLAUSE` (Cas9
only), `OLIGOMER_CLAUSE` and `SELECTIVITY_CLAUSES` (the two GDF-8 prompts only). Annotating
one prompt covers the set. The build re-derives this table from the files on every run.

**The multi-target prompt is the same document under a scaling vector.** 16 changed regions
covering 28 of 170 blocks. One is structural — a 14-row target table replacing the dossier
paragraph — and every other change is a substituted constant: $10k→$50k, 24h→48h, governor
150→325, 20k–200k→100k–1M designs. Every method, threshold, gate, formula, deliverable and
safety clause is byte-identical between a $10,000 campaign and a $50,000 one. Three of the
16 "changes" are curly-versus-straight quotation marks.

**Roughly a third of the prompt is machine-checked, not merely instructed.** Classifying
every block by normative force gives 50 `MECHANICAL` / 81 `MUST` / 33 `SHOULD` / 6 `MAY`.
The mechanical clauses specify code the agent is required to write — `submit_gate()`, the
sheet writer's gate recompute, `/state/gates/{target}.json` — which then enforces the rule
regardless of what the agent remembers.

**Those 50 clauses survive being taken literally.** All of them are re-coded in `pycode/`
as one importable package with a shared vocabulary. The build derives 41 cross-references
between blocks, which is the structural finding: read as prose, the selection caps (st-92)
and the pre-order re-check (st-246) look like repetition; written as code, st-246 is a
*call* to st-92 against the final selected set.

Doing that arithmetic also surfaced a small inconsistency in the prompt itself. Its stated
"1.58x even-pace" for the bootstrap ceiling is 150/95 — the ratio against a rounded figure
in the prose — while the `floor()` rule the same block specifies gives 94, and so 1.60x.
Immaterial in dollars; flagged rather than corrected.

**How hard a clause binds says little about whether it can be checked.** Classifying the
same 170 blocks a second time — by what each would be in a DSPy program — gives 48 `code`,
39 `metric`, 26 `scaffolding`, 32 `corpus`, 13 `inert`, one `unclear`, and only **11
`signature` blocks: places where a model must actually exercise judgment.** Ten of those
eleven are epistemic rather than scientific; they govern how the campaign reasons and
reports, not what it designs.

Set against the force axis, the two agree at the extremes and part company in the middle:

|  | code | metric | signature | scaffolding | corpus | inert | unclear |
|---|---:|---:|---:|---:|---:|---:|---:|
| `MECHANICAL` | **33** | 9 | · | 8 | · | · | · |
| `MUST` | 14 | **28** | 9 | 17 | 2 | 10 | 1 |
| `SHOULD` | · | 2 | 1 | · | **30** | · | · |
| `MAY` | 1 | · | 1 | 1 | · | 3 | · |

`MUST` scatters across five roles with no majority — "you must" states a consequence, not a
check. The blocks that resist becoming metrics are the ones whose subject the campaign never
records: pacing between generation and scoring, "use as much time as possible", adversarial
review of every deliverable. Making those checkable is a change to what the campaign
*writes down*, not to how the prompt is worded. Method, counterexample and verdict in
[dspy_slice/README.md](dspy_slice/README.md).

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
  dspy_roles.json         the DSPy-role axis over the same 170 blocks, with its evidence
pycode/                   the 50 MECHANICAL blocks as one Python package + its selftest
dspy_slice/               the DSPy feasibility experiment; runs offline, outside the build
ANALYSIS.md               the written dissection
CLAUDE.md                 repo conventions
plans/                    approved implementation plans, plus plan-overview.md (status)
                          and plan-original-brief.md (the original brief, verbatim)
```

Annotations are authored in `annotations/*.json` and embedded near the top of the generated
`index.html` as pretty-printed JSON, so they can also be read and hand-edited there.

### What the build enforces

The build fails rather than producing a plausible-looking page:

- **Fidelity.** Block text is parsed back out of the generated HTML and must match the
  source markdown exactly. No prompt text is paraphrased, reformatted or elided anywhere in
  the viewer — the left pane renders the source bytes.
- **Coverage.** Every block must have an annotation, and every tag, force and owner must be
  in the declared vocabulary.
- **Slots.** The template-slot table is re-derived from all 16 prompts each run; a varying
  line that no rule classifies fails the build instead of being silently absorbed.
- **Code.** Every `MECHANICAL` block must have a `pycode/` region, every module must
  compile, every region must round-trip through the syntax highlighter byte-for-byte, and
  `pycode/selftest.py` must pass.
- **Evidence.** Every block must carry a DSPy role, and the role must be earned: a `metric`
  without a predicate naming a concrete artifact, a `signature` without its output fields,
  or a `scaffolding` without a named missing capability fails the build. This is the rule
  that keeps the axis from degenerating into relabelling — it is easy to call something a
  metric and hard to write the predicate.

---

## A note on the Python

`pycode/` is a **reconstruction for reading**, not the campaign's implementation and not
runnable against real services — `pycode/external.py` stubs the provider and harness
surfaces so the package imports and its pure logic can be exercised. Its purpose is to make
the prompt's own arithmetic and control flow legible, and its selftest checks that the
arithmetic the prompt states is the arithmetic the code computes.

`dspy_slice/` is likewise an experiment rather than a port. It rebuilds one slice — roster
bring-up triage — as a DSPy program and runs it offline on `dspy.utils.DummyLM`, so **no
real model is called anywhere in it** and nothing in it measures a model's skill. What it
measures is control flow: a guarded program and an unguarded one, driven by the *same*
unreliable scripted model, score 1.00 and 0.60–0.80 against the same metric. It needs
`pip install dspy` and is deliberately outside `build.py`, which stays stdlib-only.

## Licensing

This repository contains original analysis, annotation and tooling. The prompts and
reference corpus are **not redistributed here** — download them from
[the dataset](https://huggingface.co/datasets/Anthropic/claude-protein-binder-design) and
see its `README.md` and `REDISTRIBUTION_NOTES.csv` for the terms attaching to the corpus,
which contains third-party material under a mix of licences.
