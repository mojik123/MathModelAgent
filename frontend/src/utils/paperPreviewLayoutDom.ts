const STYLE_ID = "paper-preview-layout-dom-style";
let installed = false;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
/* Keep the rendered paper on a stable page axis. Long tables, formulas and figures
   must scroll inside themselves instead of pushing later content left/right. */
.paper-preview {
	position: relative !important;
	display: block !important;
	box-sizing: border-box !important;
	width: 100% !important;
	max-width: 100% !important;
	margin-left: auto !important;
	margin-right: auto !important;
	padding-left: 0 !important;
	padding-right: 0 !important;
	transform: none !important;
	contain: layout paint;
}

.paper-preview *,
.paper-preview *::before,
.paper-preview *::after {
	box-sizing: border-box !important;
}

.paper-preview > * {
	max-width: 100% !important;
	margin-left: 0 !important;
	margin-right: 0 !important;
	transform: none !important;
}

.paper-preview p,
.paper-preview li,
.paper-preview blockquote,
.paper-preview figcaption,
.paper-preview .markdown-table-caption {
	position: relative;
	max-width: 100% !important;
	transform: none !important;
}

.paper-preview p,
.paper-preview li,
.paper-preview blockquote {
	overflow-wrap: anywhere;
	word-break: break-word;
}

.paper-preview h1,
.paper-preview h2,
.paper-preview h3,
.paper-preview h4 {
	max-width: 100% !important;
	clear: both;
}

.paper-preview .math-block,
.paper-preview .katex-display {
	max-width: 100% !important;
	overflow-x: auto !important;
	overflow-y: hidden !important;
	padding: 0.25rem 0 !important;
	text-align: center !important;
	text-indent: 0 !important;
}

.paper-preview .katex {
	max-width: 100% !important;
}

.paper-preview figure,
.paper-preview .markdown-figure,
.paper-preview .markdown-image-wrapper {
	max-width: 100% !important;
	text-indent: 0 !important;
	clear: both;
}

.paper-preview img {
	max-width: 100% !important;
	height: auto !important;
}

.paper-preview .markdown-table-wrapper {
	width: 100% !important;
	max-width: 100% !important;
	overflow-x: auto !important;
	margin-left: 0 !important;
	margin-right: 0 !important;
	padding-left: 0 !important;
	padding-right: 0 !important;
	clear: both;
}

.paper-preview table,
.paper-preview .markdown-table {
	min-width: min(100%, 520px);
	max-width: 100% !important;
}

.paper-preview .paper-toc-content {
	max-width: 100% !important;
	margin-left: 0 !important;
	margin-right: 0 !important;
	text-indent: 0 !important;
}

.paper-preview .paper-toc-content * {
	text-indent: 0 !important;
}

/* Selection should be block-based and predictable. The selected paragraph should not
   change document width or shift neighboring paragraphs. */
.paper-preview [data-sentence] {
	cursor: text;
	border-radius: 6px;
	transition: background .12s ease, box-shadow .12s ease;
}

.paper-preview [data-sentence].sentence-hover {
	background: rgba(37, 99, 235, .055) !important;
	box-shadow: inset 3px 0 0 rgba(37, 99, 235, .28) !important;
}

.paper-preview [data-sentence].sentence-selected {
	background: rgba(37, 99, 235, .105) !important;
	box-shadow: inset 3px 0 0 rgba(37, 99, 235, .65) !important;
}

.paper-preview .paper-toc-content [data-sentence],
.paper-preview .math-block [data-sentence],
.paper-preview .katex [data-sentence],
.paper-preview figure [data-sentence],
.paper-preview figcaption[data-sentence],
.paper-preview .markdown-table-caption[data-sentence] {
	cursor: default !important;
	background: transparent !important;
	box-shadow: none !important;
}
`;
	document.head.appendChild(style);
}

function getPreviewRoot() {
	return document.querySelector<HTMLElement>(".paper-preview");
}

function textOf(node: Element | null) {
	return (node?.textContent || "").replace(/\s+/g, " ").trim();
}

function isBadSelectableBlock(block: HTMLElement) {
	if (!textOf(block)) return true;
	if (block.closest("pre, code, .katex, .math-block, .paper-toc-content, figure, .markdown-figure, .markdown-image-wrapper")) return true;
	if (block.classList.contains("markdown-table-caption")) return true;
	if (/^图\s*\d+/.test(textOf(block)) && block.tagName === "FIGCAPTION") return true;
	return false;
}

function normalizeSelectableBlocks() {
	const root = getPreviewRoot();
	if (!root) return;

	// Remove stale marks first. WriterEditor may mark figcaptions / table cells; this
	// patch narrows text editing to true narrative blocks and valid table cells only.
	for (const node of Array.from(root.querySelectorAll<HTMLElement>("[data-sentence]"))) {
		if (isBadSelectableBlock(node)) {
			node.removeAttribute("data-sentence");
			node.classList.remove("sentence-hover", "sentence-selected");
		}
	}

	const blocks = Array.from(root.querySelectorAll<HTMLElement>("p, li, blockquote, td, th"));
	let index = 0;
	for (const block of blocks) {
		if (isBadSelectableBlock(block)) {
			block.removeAttribute("data-sentence");
			block.classList.remove("sentence-hover", "sentence-selected");
			continue;
		}
		block.dataset.sentence = String(index++);
	}
}

function normalizeLayoutInlineStyles() {
	const root = getPreviewRoot();
	if (!root) return;
	for (const el of Array.from(root.querySelectorAll<HTMLElement>("p, li, blockquote, figure, .markdown-table-wrapper, .math-block"))) {
		// Some generated / injected blocks may carry inline layout values. Clear only
		// properties that can make later content visually drift sideways.
		el.style.removeProperty("margin-left");
		el.style.removeProperty("margin-right");
		el.style.removeProperty("padding-left");
		el.style.removeProperty("transform");
		el.style.removeProperty("float");
	}
}

function patchPaperPreviewLayout() {
	normalizeSelectableBlocks();
	normalizeLayoutInlineStyles();
}

export function installPaperPreviewLayoutDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	addStyle();
	setInterval(patchPaperPreviewLayout, 600);
	window.addEventListener("resize", patchPaperPreviewLayout);
}
