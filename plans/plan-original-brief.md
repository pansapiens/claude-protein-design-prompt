# Protein Design Prompt Dissection and Modularization

We have the prompts and associated reference material from https://huggingface.co/datasets/Anthropic/claude-protein-binder-design

We want to dissect the prompts used, starting with a single target prompt (eg `protein_binder_design_prompts_release/prompts/single_target/15-PGDH.md`), then the multiple target prompt (`protein_binder_design_prompts_release/prompts/multi_target_binder_design_prompt.md`).

Diff the single target prompts to establish what is different between them and against the multiple target prompt - most likely we only need to analyse one single target prompt, and the differences with the multiple target prompt.

I want to generate a simple two pane web viewer that shows the prompt in the left pane and a additional LLM + human annotation in the right pane. When we click an annotation block, the associated prompt section should be highlighted in the left pane, and vice versa. Use the frontend-design skill for guidance - want a clean minimal design, light theme by default.

Break the prompt down into logical sections, analyse the purpose of each section and add this as a concise annotation to the right pane. Consider the prompt as pseudo-code, and as set of template fragments that can be filled in with different values and composed. Give each section a set of tags - you'll need to iterate to decide on a good set of categories/tags for each section (the might be 'reference', 'installation', 'infrastruture', 'pseudocode', 'outputs', 'safety' etc) 

Identify:

- 'Constants'/'Variables' that could substituted (eg, this could be a protein name)
- List of inputs/variables (eg lists of protein design tools, lists of reference URLs)
- Other 'code like' constructs that would be useful highlighting

(these can be highlighted as their own color to show they have be identified)

# Technology / frameworks

- Use Vue.js (from a CDN)
- If you feel you need a UI framework (you might not)
