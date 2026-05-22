# CUMCM LaTeX Skill

Use this project skill when MathModelAgent needs to turn the final Markdown
paper into a China Undergraduate Mathematical Contest in Modeling style
LaTeX/PDF paper.

The intended pipeline is:

1. Writer agent outputs `res.md` in a complete modeling-paper structure.
2. Backend converts `res.md` to `res.tex` with the CUMCM Pandoc template.
3. Backend compiles `res.tex` with XeLaTeX to `res.pdf`.

Formatting goals:

- Chinese mathematical-modeling paper style for CUMCM / national contest use.
- One title page signal, abstract, keywords, problem restatement, analysis,
  assumptions, notation, model construction and solution, sensitivity analysis,
  model evaluation, and references.
- Chinese typography through `ctex` and Noto CJK fonts.
- Pandoc-friendly Markdown only: standard headings, tables, images, and
  `$...$` / `$$...$$` math.

Upstream template reference:

- `latexstudio/CUMCMThesis` on GitHub is the preferred third-party CUMCM
  LaTeX template reference.
- If the repository is available locally, place it under
  `third_party/CUMCMThesis/` for documentation/reference.
- The backend uses `backend/app/config/cumcm_pandoc_template.tex` as the
  integrated runtime template so Docker can run without reaching GitHub.

