# Dissecting the Claude protein binder design prompts

An analysis of the prompts released as
[Anthropic/claude-protein-binder-design](https://huggingface.co/datasets/Anthropic/claude-protein-binder-design):
16 single-target campaign prompts, one multi-target prompt, two kickoff messages and a 1.1 GB
reference corpus.

The interactive companion to this document is `index.html`: the prompt on the left, a
per-block annotation on the right, and an enforcement rail between them. Everything below is
derived by `build.py` from the release bundle; no figure here is hand-counted.

---

## 1. Document structure and enforcement

The single-target prompt contains 264 lines and 112,155 characters (about 28,000 words of
continuous instruction), delivered as a system prompt to an agent that runs unsupervised for 24 hours
with a $10,000 budget.

The prompt operates as an **operations order with machine-checked invariants**. A large portion of
its rules are not left to agent judgment; they specify code the agent must author, which enforces
constraints programmatically regardless of agent memory.

The concurrency governor exemplifies this design. Instead of instructing the agent to stay within
budget in prose, the prompt defines a concrete gate function:

> The module exposes one function, `submit_gate(app_id, project_tag, timeout_s, gpu_type=None,
> target=None, stage=None)`, whose ENTIRE body is wrapped in try/except and which on ANY exception
> returns False with `reason="GATE_ERROR"`; the gate is FAIL-CLOSED, never fail-open, because a
> delayed dispatch costs seconds while an ungated H100 dispatch can be multiple unrecoverable
> dollars.

The specification details steps (a) through (g), restricts governor file writes to four authorized
processes, forbids private concurrency caps, and establishes that no orchestrator-authorized
degraded mode exists. That single block spans 3,700 characters.

Scoring follows the same paradigm: rather than general instructions to rank designs well, the prompt
requires a frozen six-term formula with a 4:1 weighting, pre-registered before scoring production
designs. Data integrity relies on a sheet-writer module that recomputes every gate from the candidate
sequence and predicted structure, admitting a row only when values match within 1e-4.
### Enforcement profile

Annotating all 170 blocks on a four-level scale of normative force gives:

| Force | Blocks | Share | Meaning |
|---|---:|---:|---|
| `MECHANICAL` | 50 | 29% | Enforced by code the agent must write. Violation is impossible, not disallowed. |
| `MUST` | 81 | 48% | Hard obligation, enforced by review or report. |
| `SHOULD` | 33 | 19% | Strong default with a disclosed-deviation path. |
| `MAY` | 6 | 4% | Explicit latitude. |

Mechanical clauses constitute 29% of the prompt. Their distribution is concentrated in
Deliverables (14 of 30 blocks), Compute (5 of 7), and Verification (5 of 10), but sparse in the
final Behavior and Safety sections.

### The distribution of authority

Owner assignments across all 170 blocks reveal a distributed architecture. 99 blocks bind any
agent at any delegation depth, establishing verification, measurement, and reporting standards
that accompany subagent briefs. The remaining blocks belong to designated roles: `sheet-writer` (19),
`orchestrator` (18), `DELIVERABLES` (14), `BUDGET` (7), `SCRIBE` (6), `DISPATCH` (4), and one each
for `CLOCK`, `WATCHDOG`, and per-job `monitor` instances.

The orchestrator role has minimal operational duties. The prompt explicitly restricts it: the
orchestrator must never call provider SDKs, never sleep, and never maintain critical state in
memory. Orchestrator token usage exceeding one third of the campaign total after hour one is
designated an architecture failure.

---

## 2. The 16 single-target prompts are one template

Diffing all 16 single-target files against `15-PGDH.md` yields 36 varying lines. Classified, they
resolve to **six slots**: 29 of the 36 lines reflect renumbering of the shared 29-item reference list.

| Slot | Lines | Targets affected | Variation |
|---|---:|---|---|
| `TASK_TARGET` | 1 | all 15 | Target name and synonyms. The GDF-8 prompts add a counter-target and a third goal (selectivity). |
| `TARGET_DOSSIER` | 1 | all 15 | UniProt accession, oligomeric state, cofactors, assay construct, competition link. |
| `COMPETITION_REFS` | 29 | 6 targets | 0–4 target-specific competition references are prepended, shifting the numbering of the shared list. |
| `CONSTRUCT_CLAUSE` | 1 | Cas9 only | "scoring construct" widened to "design and scoring constructs", because the functional unit is a 1:1 RNP. |
| `OLIGOMER_CLAUSE` | 1 | all 15 | A parenthetical naming the oligomeric state, or dropped entirely for monomers. |
| `SELECTIVITY_CLAUSES` | 3 | both GDF-8 prompts | Counter-target arm at the validation gate, selectivity-directed optimization, and selectivity terms in the ranking formula. |

Everything else (methods, thresholds, gates, formulas, deliverables, and safety clauses) is
byte-identical across all 16 files. Analysing one single-target prompt covers the entire set.

`build.py` re-derives this table from the release files on every run and fails if an unclassified line
appears, ensuring prompt changes cause explicit build failures rather than being ignored.

---

## 3. The multi-target prompt is the same document under a scaling vector

Aligning the single- and multi-target prompts block by block with `difflib` identifies
**16 changed regions covering 28 of 170 blocks**. One region is structural: a 14-row target table
replaces the single-target dossier paragraph. Every other change is a substituted constant.
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
| Bootstrap vs even pace | 1.58× | 1.37× | - |
| Close-out reserve | final hour | final 3 hours | 3× |
| Surplus-plan trigger | >2 h remaining | >5 h remaining | 2.5× |
| Design sheet | 30 designs | 30 per target | 14× |
| Optimization rounds | ≥5 | ≥2, ≥5 if hard | - |
| Stale-metered $ threshold | $40 | $200 | 5× |

Two of these are not proportional, and both are informative.

**Optimization depth is redistributed by target difficulty.** The single-target minimum of five
rounds becomes "at least two per target and at least five on the more challenging targets."
Because target count increases 14x while budget increases 5x, uniform depth is impossible; the
prompt shifts from a uniform floor to an evidence-weighted allocation. This matches the
`target_weights.json` mechanism, which blends a literature difficulty prior with live screening metrics.

**Initial concurrency starts closer to sustainable pace.** The bootstrap ceiling of 325 instances
runs at 1.37x even pace, compared to 1.58x in the single-target campaign. The expanded budget and
duration produce a smaller initial overshoot relative to the sustainable rate.

The rest of the prompt remains identical. The entire methodology (tool roster, method floors,
novelty and liability gates, the three-arm scoring ensemble, `ipSAE_min` union-mask construction,
calibration bands, selection caps, sheet-writer invariants, the WATCHDOG ladder, epistemic
constraints, and safety guidelines) is byte-identical between the $10,000 and $50,000 campaigns.

Three of the 16 modified regions reflect only punctuation: straight versus curly quotation marks
and apostrophes across three blocks.

---

## 4. Code-like constructs in the prompt text

While written as English text, the prompt contains extensive program-like identifiers. Tokenising the
single-target and multi-target prompts together yields 2,435 matches (alongside 59 markdown
emphasis spans):

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

- **Operator placeholders** (`<target>`, `<SLACK_CHANNEL_ID>`) are populated before launch; the
  release README lists six required substitutions.
- **Template slots** (the six categories above) vary across the 16 generated per-target files.

They look alike in raw markdown and receive distinct highlighting in the viewer.

The tokenizer leaves ordinary words in all-caps unstyled (MUST, NEVER, ONLY, SAME, BEFORE, REQUIRED).
Capitalized keywords appear hundreds of times, serving as typographic reinforcement analogous to
RFC 2119 keywords in technical specifications.

---

## 5. Re-coding mechanical clauses

To verify mechanical enforcement, all 50 `MECHANICAL` blocks were reconstructed in Python as an
importable package (`pycode/`, ~2,500 lines across 9 modules) sharing a common vocabulary. The viewer
displays each block's code under the **As Python** tab.

All 50 blocks map to executable Python constructs across five structural categories:

| Encoding | Regions | Category description |
|---|---:|---|
| `logic` | 29 | Concrete algorithms: thresholds, ordering, arithmetic, and control flow |
| `protocol` | 12 | Agent interaction contracts: write permissions and staging sequence |
| `schema` | 6 | Structured data formats: columns, data types, and required keys |
| `lint` | 2 | Static code requirements checkable via AST inspection |
| `config` | 2 | Pinned environments: flags, versions, and paths |

The two `config` regions (ESMFold2 and Protenix v2 installation in st-53 and st-54) represent shell
recipes stored in structured records. The two `lint` regions directly express operational constraints:
prohibitions against calling `time.sleep` or `ask_user` are static code properties validated by AST parsing.

**Cross-references reflect shared implementation state.** Deriving symbol definitions and uses
across regions yields **41 cross-references** among the 50 blocks. Two blocks account for 16 of them:

- `submit_gate()` is defined in governor block st-137 and invoked by the dispatcher (st-65),
  validation gate (st-111), and backlog cap (st-147) (8 references).
- `enforce_selection_caps()` is defined in st-92, re-invoked by the pre-order check (st-246),
  re-parameterized by the relaxation ladder (st-185), and reused by scoreboard diversity reporting
  (st-192) (8 references).

This resolves apparent redundancies in the text. In prose, st-92 and st-246 read like repetitive
instructions; in code, st-246 is an explicit call to `enforce_selection_caps()` passing the final
selected set. Because diversity caps apply to the complete selected batch, evaluating the rule at
selection close-out is a distinct execution of the same function.

**Direct computation exposed an arithmetic discrepancy.** The prompt requires deriving governor
`max_instances` as `floor(target_hourly_rate / weighted_per_sandbox_rate)`. Using the prompt's
parameters ($10,000/24 h = $416.67/h against a $4.394/h H100 rate), the floor evaluates to **94**.
The prompt subsequently asserts that the 150-instance bootstrap cap "runs about 1.58x even-pace",
corresponding to 150/95 (dividing by a rounded 95 mentioned in text) rather than the formula-derived
94 (150/94 = 1.60x). This small variation is flagged in the commentary rather than modified in code.

The build verifies the implementation automatically: all modules must compile, every `MECHANICAL`
block must map to a region, each region must round-trip through the syntax highlighter, and
`pycode/selftest.py` must pass. Selftest runs 24 verification checks covering the 4:1 weighting,
burn-rate calculations, sequential cap enforcement, tier-before-score ordering, the WATCHDOG ladder,
and independent runaway bounds.
---

## 6. Operational and design patterns

Several architectural patterns recur across the 170 blocks:

**Specify failure modes before mechanical remedies.** Hazards are identified explicitly alongside
their mitigations. Structure generators generating target-protomer copies for similar-length targets
are filtered by the TM-score check in the novelty gate. Concurrent volume appends that risk write
corruption are avoided by dedicating one ledger file per writing frame. Metric scale differences
(such as ESMFold2 reporting pLDDT on 0–1 rather than 0–100), name collisions (MBP referring to distinct
proteins), and package ambiguities (the PyPI `esm` package) receive explicit operational handling.

**Prioritize disclosure over omission.** When constraints cannot be met, instructions require retaining
imperfect entries with explicit labels rather than discarding them. Rows with fewer than five seeds
rank below complete rows with seed counts disclosed. Missing scores are recorded as `NaN` rather than
sentinels such as `0.0` or `-999`, preventing artificial values in downstream averages. If the 10%
non-all-alpha diversity target cannot be met without displacing superior designs, the prompt directs
outputting the actual count accompanied by a documented explanation.

**Pre-register evaluation protocols.** Custom ranking formulas are permitted only when demonstrably
superior at separating controls, provided they are frozen and documented before scoring production
designs. Retrospective parameter adjustments must disclose the total number of evaluated configurations.

**Account for evaluation bias.** Published de novo miniprotein binders are rejected as positive controls
because prior selection by co-folding metrics makes separation testing circular. Antibody controls are
deprioritized due to model inaccuracies on antibody-antigen interfaces. Whole-complex ipTM is excluded
on multimeric targets because native protomer interfaces bias the score.

**Budget target enforcement.** The Modal budget operates as a planned expenditure target rather than
an upper cap: spending 5% over target is preferred to ending 50% under budget. Underspending at close-out
requires formal justification in the final report, while generating synthetic compute solely to reach
the spending target is prohibited.

**Verification requirements under autonomous execution.** Because human operators do not review
intermediate artifacts before compute resources are committed, autonomous agents require strict
verification boundaries. Epistemic constraints forbid citing external identifiers (DOIs, PMIDs, PDB
IDs, accessions, or URLs) from model memory; every identifier must originate from a tool lookup executed
within the current session.
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

## 8. Scope limits

- The 1.1 GB reference corpus. It is referenced throughout the annotations but not rendered.
- The two kickoff messages (`prompts/kickoff/`), which supply T0, the operator placeholders and the
  first-actions sequence.
- Any assessment of whether the campaign worked. The release contains prompts and source material,
  not results.
