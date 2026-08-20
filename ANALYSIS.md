# Dissecting the Claude protein binder design prompts

An analysis of the prompts released as
[Anthropic/claude-protein-binder-design](https://huggingface.co/datasets/Anthropic/claude-protein-binder-design):
16 single-target campaign prompts, one multi-target prompt, two kickoff messages and a 1.1 GB
reference corpus.

The interactive companion to this document is `index.html` — the prompt on the left, a
per-block annotation on the right, and an enforcement rail between them. Everything below is
derived by `build.py` from the release bundle; no figure here is hand-counted.

---

## 1. What kind of document is this?

The single-target prompt is 264 lines and 112,155 characters — about 28,000 words of continuous
instruction, delivered as a system prompt to an agent that will then run unsupervised for 24 hours
and spend $10,000.

It is not written like a brief. It is written like an **operations order with machine-checked
invariants**. The distinguishing feature is that a large fraction of its rules are not addressed
to the agent's judgement at all; they are specifications for code the agent is required to write,
which then enforces the rule whether the agent remembers it or not.

The clearest example is the concurrency governor. The prompt does not say "stay within budget."
It specifies a function:

> The module exposes one function, `submit_gate(app_id, project_tag, timeout_s, gpu_type=None,
> target=None, stage=None)`, whose ENTIRE body is wrapped in try/except and which on ANY exception
> returns False with `reason="GATE_ERROR"`; the gate is FAIL-CLOSED, never fail-open, because a
> delayed dispatch costs seconds while an ungated H100 dispatch can be multiple unrecoverable
> dollars.

…then defines steps (a) through (g), names the four processes permitted to write the governor
file, forbids any agent from maintaining a private concurrency cap, and states that "there is NO
orchestrator-authorized 'degraded mode'." That single block is 3,700 characters.

The same pattern recurs. Scoring is not "rank the designs well" but a frozen six-term formula with
a 4:1 weighting, pre-registered before any production design is scored. Data integrity is not
"keep good records" but a sheet writer that recomputes every gate from the row's own sequence and
predicted structure and admits the row only on agreement to within 1e-4.

### Enforcement profile

Annotating all 170 blocks on a four-level scale of normative force gives:

| Force | Blocks | Share | Meaning |
|---|---:|---:|---|
| `MECHANICAL` | 50 | 29% | Enforced by code the agent must write. Violation is impossible, not disallowed. |
| `MUST` | 81 | 48% | Hard obligation, enforced by review or report. |
| `SHOULD` | 33 | 19% | Strong default with a disclosed-deviation path. |
| `MAY` | 6 | 4% | Explicit latitude. |

Nearly a third of the document is machine-checked. That is the single most unusual thing about it,
and it is what the viewer's centre rail exists to show: the density of mechanical clauses is very
uneven, clustering in Deliverables (14 of 30 blocks), Compute (5 of 7), and Verification (5 of 10),
and thinning out almost to nothing in the Behavior and Safety sections at the end.

### The distribution of authority

Assigning each block an owner shows a deliberately flat structure. Of 170 blocks, 99 bind *any*
agent at any depth — the verification, measurement and reporting standards that the opening
"Addressing:" block says travel with the document. The rest are owned by named singletons:
`sheet-writer` (19), `orchestrator` (18), `DELIVERABLES` (14), `BUDGET` (7), `SCRIBE` (6),
`DISPATCH` (4), and one each for `CLOCK`, `WATCHDOG` and the per-10-jobs `monitor`.

The orchestrator owns strikingly little. The prompt is explicit about why: it must never call a
provider SDK, never sleep, never hold load-bearing state in memory, and its token cost exceeding
one third of the campaign total after hour one is called "an architecture failure."

---

## 2. The 16 single-target prompts are one template

Diffing all 16 single-target files against `15-PGDH.md` yields 36 varying lines. Classified, they
resolve to **six slots** — and 29 of the 36 lines are the shared 29-item reference list renumbering
itself, not new content.

| Slot | Lines | Targets affected | What varies |
|---|---:|---|---|
| `TASK_TARGET` | 1 | all 15 | Target name and synonyms. The GDF-8 prompts add a counter-target and a third goal (selectivity). |
| `TARGET_DOSSIER` | 1 | all 15 | UniProt accession, oligomeric state, cofactors, assay construct, competition link. |
| `COMPETITION_REFS` | 29 | 6 targets | 0–4 target-specific competition references are prepended, shifting the numbering of the shared list. |
| `CONSTRUCT_CLAUSE` | 1 | Cas9 only | "scoring construct" widened to "design and scoring constructs", because the functional unit is a 1:1 RNP. |
| `OLIGOMER_CLAUSE` | 1 | all 15 | A parenthetical naming the oligomeric state, or dropped entirely for monomers. |
| `SELECTIVITY_CLAUSES` | 3 | both GDF-8 prompts | Counter-target arm at the validation gate, selectivity-directed optimization, and selectivity terms in the ranking formula. |

Everything else — every method, threshold, gate, formula, deliverable and safety clause — is
byte-identical across all 16 files. Analysing one single-target prompt genuinely covers the set.

`build.py` re-derives this table from the files on every run and fails the build if a varying line
appears that none of the six rules classifies, so a future addition to the release surfaces as an
error rather than being silently absorbed.

---

## 3. The multi-target prompt is the same document under a scaling vector

This is the more interesting finding. Aligning the two prompts block by block with `difflib` gives
**16 changed regions covering 28 of 170 blocks**. One of those regions is structural — a 14-row
target table replaces the single-target dossier paragraph. Every other change is a substituted
constant.

| Parameter | Single | Multi | Ratio |
|---|---|---|---|
| Modal budget | $10,000 | $50,000 | 5× |
| Wall clock | 24 h | 48 h | 2× |
| Targets | 1 | 14 | 14× |
| Governor ceiling | 150 | 325 | 2.2× |
| Bootstrap step per cycle | 25 | 50 | 2× |
| Daemon concurrency cap | 200 | 450 | 2.25× |
| Sub-agent headroom N | 50 | 100 | 2× |
| Peak concurrent agents | >50 | >100 | 2× |
| Designs generated and screened | 20k–200k | 100k–1M | 5× |
| Even-pace H100 equivalents | ~95 | ~237 | 2.5× |
| Bootstrap vs even pace | 1.58× | 1.37× | — |
| Close-out reserve | final hour | final 3 hours | 3× |
| Surplus-plan trigger | >2 h remaining | >5 h remaining | 2.5× |
| Design sheet | 30 designs | 30 per target | 14× |
| Optimization rounds | ≥5 | ≥2, ≥5 if hard | — |
| Stale-metered $ threshold | $40 | $200 | 5× |

Two of these are not proportional, and both are informative.

**Optimization depth is redistributed, not scaled.** The single-target minimum of five rounds
becomes "at least two per target and at least five on the more challenging targets." With 14× the
targets and only 5× the budget, uniform depth is unaffordable, so the prompt converts a flat
minimum into an evidence-weighted allocation — consistent with the `target_weights.json` mechanism
that blends a literature difficulty prior with live screening data.

**The multi-target campaign starts more conservatively.** Its bootstrap ceiling of 325 instances
runs 1.37× even pace, against 1.58× for the single-target campaign. More money and more time buys
a smaller initial overshoot relative to the sustainable rate.

Everything else is untouched. The entire methodology — roster, method floors, novelty and liability
gates, the three-arm instrument, `ipSAE_min` union-mask construction, calibration bands, selection
caps, the sheet writer's invariants, the WATCHDOG escalation ladder, the epistemic rules, the
safety section — is byte-identical between a $10,000 campaign and a $50,000 one.

Three of the 16 "changed" regions turn out to be typographic only: straight versus curly quotation
marks and apostrophes in three blocks. A byte diff reports them as changes; they are not.

---

## 4. Code-like constructs in the prompt text

The prompt reads as prose but is dense with identifiers that behave like code. Tokenising the
single-target and multi-target prompts together gives 2,435 such matches (plus 59 markdown
emphasis spans, not counted here):

| Class | Matches | Examples |
|---|---:|---|
| snake_case identifiers | 720 | `submit_gate`, `root_backbone_id`, `pct_spent_metered`, `n_seeds`, `reply_broadcast` |
| tool and service names | 423 | `RFdiffusion3`, `BoltzGen`, `ESMFold2-Full`, `Protenix v2`, `SolubleMPNN`, `MMseqs2`, `DockQ` |
| numeric constants | 331 | `$10,000`, `150`, `0.23`, `60%`, `1e-4`, `5400s`, `2048` |
| metric names | 202 | `ipSAE_min`, `sc_DockQ`, `pose_dockq`, `rank_zscore`, `final_score`, `lcp_score`, `TM-score` |
| file and state artifacts | 152 | `/state/governor.json`, `/state/gates/{target}.json`, `per_seed_metrics.parquet`, `method_vocab.json` |
| enum literals and env vars | 129 | `PASS`, `NaN`, `CONSTRUCT_FAIL`, `REDUCED_MASK`, `GATE_ERROR`, `TORCH_EXTENSIONS_DIR` |
| agent role names | 126 | `SETUP`, `BUDGET`, `WATCHDOG`, `CLOCK`, `SCRIBE`, `DISPATCH`, `DELIVERABLES` |
| dotted API calls | 104 | `modal.Sandbox.create()`, `host.compute.set_concurrency_limit`, `sb.terminate()` |
| markdown citations | 75 | 29 numbered references plus inline method-paper links |
| operator placeholders | 55 | `<target>`, `<SLACK_CHANNEL_ID>`, `<Campaign Deliverables Folder>`, `<frameid8>` |
| CLI flags | 24 | `--need_atom_confidence`, `--norun_data_pipeline`, `--of3_weights` |

The viewer colours these by group. Two distinctions matter when reading:

- **Operator placeholders** (`<target>`, `<SLACK_CHANNEL_ID>`) are filled by the human before
  launch — the release README lists exactly six that must be substituted.
- **Template slots** (the six above) are filled by whoever generated the 16 per-target files.

They look alike in the raw markdown and are highlighted differently in the viewer.

There is a third convention the tokeniser deliberately does not highlight: heavy ALL-CAPS emphasis
on ordinary words — MUST, NEVER, ONLY, SAME, BEFORE, REQUIRED. It appears hundreds of times and
colouring it would drown everything else, but it is worth noting as a stylistic choice: the prompt
uses typographic stress the way a specification uses RFC 2119 keywords.

---

## 5. Re-coding the mechanical clauses

If a third of the document really is machine-checked, that claim should survive being
taken literally. So all 50 `MECHANICAL` blocks were rewritten as Python — not fifty
snippets, but one importable package (`pycode/`, ~2,500 lines across 9 modules) with a
shared vocabulary. The viewer renders each block's region under an **As Python** tab.

It works. Every one of the 50 encodes, and the distribution of *how* is itself the
result:

| Encoding | Regions | What the block turned out to be |
|---|---:|---|
| `logic` | 29 | An algorithm: thresholds, ordering, arithmetic, control flow |
| `protocol` | 12 | A contract between agents: who may write what, in what order |
| `schema` | 6 | A frozen data shape: columns, dtypes, required keys |
| `lint` | 2 | A rule about the campaign's own source, checkable statically |
| `config` | 2 | A pinned recipe: flags, versions, paths |

Only the two `config` regions are a stretch. The ESMFold2 and Protenix v2 bring-up blocks
(st-53, st-54) are install recipes; rendering them as frozen `ToolRecipe` records is
honest but adds nothing an ordered list would not. Everything else is genuinely
executable in shape. The two `lint` regions are the pleasant surprise: "the orchestrator
must never call `time.sleep`" and "NEVER call `ask_user`" are not prose exhortations at
all — they are static properties of the campaign's own source, and encoding them as an
`ast` walk is closer to what they mean than a paragraph is.

**The blocks share a vocabulary, and the sharing is measurable.** The build derives which
region uses a name another region defines, and finds **41 cross-references** among the
50 blocks. Two blocks supply most of them:

- `submit_gate()` is specified in the governor block (st-137) and called by the dispatcher
  (st-65), the validation gate (st-111) and the backlog cap (st-147) — 8 borrowings.
- `enforce_selection_caps()` is specified once (st-92), then re-run by the pre-order
  re-check (st-246), re-parameterised by the relaxation ladder (st-185), and reused by the
  scoreboard's diversity columns (st-192) — 8 borrowings.

That is the structural finding. Read as prose, st-92 and st-246 look like the document
repeating itself; written as code, st-246 is a *call* to st-92 with the final selected set
— a different operation on the same rule, and necessarily so, because diversity is a
property of the selected set and the set is only final at st-246. Several apparent
redundancies in the prompt resolve this way once the shared name is factored out.

**Making the prose compute also surfaced a small inconsistency.** The prompt says the
governor's `max_instances` MUST be derived as `floor(target_hourly_rate /
weighted_per_sandbox_rate)`. With its own numbers — $10,000/24 h = $416.67/h against a
$4.394/h all-in H100 box — that floor is **94**. The prompt then states the 150-instance
bootstrap cap "runs about 1.58x even-pace", which is 150/95: the ratio against the
*rounded* 95 quoted in the prose, not against the floor its own rule specifies (150/94 =
1.60x). Immaterial in dollars, and it is flagged rather than corrected — but it is exactly
the class of drift that only appears when the prose is made to compute.

The build enforces the reconstruction rather than trusting it: every module must compile,
every `MECHANICAL` block must have a region, each region must round-trip through the
syntax highlighter byte-for-byte, and `pycode/selftest.py` must pass — 24 checks that the
arithmetic the prompt states is the arithmetic the code computes (the 4:1 weighting, the
burn-rate adders, the six caps applied in order, the rank key's tier-before-score rule,
the WATCHDOG escalation ladder and its independent runaway brake).

---

## 6. Recurring rhetorical moves

Reading all 170 blocks, a handful of patterns account for most of the document's unusual passages.

**Name the failure mode, then close it mechanically.** Almost every hazard is stated concretely
before its remedy. Structure generators reproduce a target protomer when asked for a binder of
similar length — caught by the TM-score branch of the novelty gate. Modal volume appends across
concurrent sandboxes are not atomic and silently clobber — hence one ledger file per writing frame.
ESMFold2 emits pLDDT on 0–1 where the threshold is written on 0–100. `MBP` means two different
proteins. The PyPI package named `esm` is a different project.

**Prefer disclosure to deletion.** Repeatedly, when the ideal cannot be met, the instruction is to
ship the imperfect thing and label it rather than drop it. Rows with fewer than five seeds are
ranked below the full-seed rows with the count disclosed, not discarded. A missing per-arm score is
written as `NaN`, never as `0.0` or `-999`, because a sentinel would silently become a real number
in a downstream mean. If the 10% non-all-alpha fold-diversity target cannot be met without
displacing better designs, ship fewer and state the count and the reason.

**Pre-registration.** An alternative ranking formula is permitted only if it demonstrably separates
controls better *and* is frozen and disclosed before any production design is scored. Analyses
tuned after seeing results must be declared along with how many configurations were tried.

**Reasoning about evaluation bias.** Published de novo miniprotein binders are excluded as
positive controls because "they were themselves likely selected by co-folding metrics, so their
separation is circular." Antibody controls are demoted because co-folding models systematically
underperform on antibody-antigen interfaces. Whole-complex ipTM is rejected for ranking on
multimeric targets because native protomer-protomer interfaces inflate it.

**Spend the budget.** "The Modal budget is a target to spend, not a ceiling… Under-pace is a
planning failure, not a savings." Finishing 5% over beats finishing 50% under. Under-spend at
close-out must be explained in the final report. Immediately guarded: "hitting a spend number with
busywork is a defect."

**Standards bind tighter under autonomy.** Stated explicitly at line 228: because no human reviews
the work before resources are spent, the agent's verification discipline is the only gate. This is
the justification the rest of the Behavior section rests on, and it is why the epistemic rules are
as specific as they are — no external identifier, DOI, PMID, PDB ID, accession or URL may be
written from memory; each must be the literal output of a lookup executed in the same session.

---

## 7. Method and reproducibility

- **Segmentation.** Block = one non-blank line. Every paragraph and list item in these files is
  exactly one physical line, so this is lossless. Block ids are source line numbers, stable because
  the release is a frozen artifact with a `MANIFEST.sha256` (339 files, all verified unmodified).
- **Counts.** 170 blocks / 32 labelled sections (single); 184 blocks / 32 sections (multi).
- **Annotations.** 170 authored for the single-target prompt; 42 authored for the multi-target
  prompt, with the remaining 142 blocks inheriting by exact text match. `build.py` fails the build
  if any block lacks an annotation or uses a tag, force or owner outside the declared vocabulary.
- **Fidelity.** After generating `index.html`, the build parses the block text back out of the
  file and asserts it matches the source markdown exactly. No prompt text is paraphrased,
  reformatted or elided anywhere in the viewer.
- **Re-coding.** 51 `pycode/` regions cover all 50 `MECHANICAL` blocks. The build compiles
  every module, asserts coverage, round-trips each region through the highlighter, and runs
  the 24-check selftest. The Python is a reconstruction for reading, not a runnable
  campaign: `pycode/external.py` stubs the provider and harness surfaces.

```bash
python3 build.py      # regenerate index.html and run every assertion
xdg-open index.html   # no server needed
```

---

## 8. What this analysis does not cover

- The 1.1 GB reference corpus. It is referenced throughout the annotations but not rendered.
- The two kickoff messages (`prompts/kickoff/`), which supply T0, the operator placeholders and the
  first-actions sequence.
- Any assessment of whether the campaign worked. The release contains prompts and source material,
  not results.
