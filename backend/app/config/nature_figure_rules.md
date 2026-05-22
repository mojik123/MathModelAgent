# Nature-style figure rules for MathModelAgent

This project includes the original `nature-figure` skill under `skills/nature-figure/`.
MathModelAgent does not load Codex skills automatically, so the operational rules below
are injected into the Coder and Writer prompts.

## Figure contract

Before plotting, every figure must have a clear claim, evidence role, and output purpose.
Prefer figures that defend a modeling conclusion rather than decorative EDA.

## Python plotting rules

- Use Python/matplotlib/seaborn for generated modeling figures.
- Use a white background, restrained low-saturation colors, and consistent palettes.
- Prefer SVG/PDF plus PNG export when possible; keep SVG text editable.
- Use `svg.fonttype = "none"` and `pdf.fonttype = 42`.
- Use font sizes suitable for papers: around 7-9 pt for figure text.
- Remove top/right spines, avoid dense gridlines, avoid pie charts and decorative 3D.
- Prefer direct labels and clear captions over crowded legends.
- Use panel labels `(a)`, `(b)`, `(c)` for multi-panel figures.
- Every axis label must include units when units exist.
- Every statistical plot must report sample size, metric definition, uncertainty meaning,
  and key numerical results in `print()` output.

## Writer rules

- Explain what each figure proves, not only what it shows.
- Every inserted figure needs a concise caption and at least one paragraph of analysis.
- Do not invent values; use the Coder's printed figure summaries.
- Mention uncertainty intervals, sample size, and evaluation metrics when available.
