# CUMCM LaTeX/PDF Output Rules

The final paper is written in Markdown and automatically converted to a
CUMCM-style LaTeX source file and PDF. Follow these constraints strictly.

## Required Markdown Structure

Use this top-level structure:

1. `# 论文题目`
2. `## 摘要`
3. `## 关键词`
4. `## 一、问题重述`
5. `## 二、问题分析`
6. `## 三、模型假设`
7. `## 四、符号说明`
8. `## 五、模型的建立与求解`
9. `## 六、敏感性分析`
10. `## 七、模型评价`
11. `## 参考文献`

Do not skip the abstract, keywords, assumptions, notation, or references.

## Markdown Compatibility

- Use standard Markdown headings only. Do not output raw HTML.
- Use `$...$` for inline math and `$$...$$` for display math.
- Use normal Markdown tables for notation and result tables.
- Use relative image filenames named by paper position, for example `![图5.1 预测结果对比](5.1_预测结果对比.png)`.
- Keep figure/table captions short and explain the result in surrounding text.
- Avoid custom LaTeX macros unless absolutely necessary.

## CUMCM Style Expectations

- The abstract must state the problem, model, method, key quantitative results,
  and conclusion.
- Keywords must be 3 to 5 terms separated by semicolons or Chinese semicolons.
- Section titles should keep Chinese numbering, such as `一、问题重述`.
- The main paper should be formal, concise, and competition-oriented.
- Do not use bullet lists in core argument paragraphs unless the section is a
  notation table, assumption list, or algorithm summary.
