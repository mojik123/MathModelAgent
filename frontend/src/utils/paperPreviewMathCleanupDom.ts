const STYLE_ID = "paper-preview-math-cleanup-style";
let installed = false;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
.paper-preview {
	--tw-prose-body: #000 !important;
	--tw-prose-headings: #000 !important;
	--tw-prose-bold: #000 !important;
}

.paper-preview h1,
.paper-preview h2,
.paper-preview h3,
.paper-preview h4,
.paper-preview h5,
.paper-preview h6,
.paper-preview h1 *,
.paper-preview h2 *,
.paper-preview h3 *,
.paper-preview h4 *,
.paper-preview h5 *,
.paper-preview h6 * {
	color: #000 !important;
	-webkit-text-fill-color: #000 !important;
	background-image: none !important;
}
`;
	document.head.appendChild(style);
}

function textOf(node: Element | null) {
	return (node?.textContent || "").replace(/\s+/g, " ").trim();
}

function isDelimiterPlaceholder(node: HTMLElement) {
	if (!["P", "DIV"].includes(node.tagName)) return false;
	if (node.closest("pre, code, .katex, .math-block")) return false;
	return /^(?:\$\$|\\\[|\\\])$/.test(textOf(node));
}

function removeInvalidMathPlaceholders(root: HTMLElement) {
	for (const node of Array.from(root.querySelectorAll<HTMLElement>("p, div"))) {
		if (isDelimiterPlaceholder(node)) node.remove();
	}

	for (const block of Array.from(
		root.querySelectorAll<HTMLElement>(".math-block, .paper-equation, .katex-display"),
	)) {
		const visibleText = textOf(block);
		const hasMathMarkup = Boolean(
			block.querySelector(".katex-html .mord, .katex-html .mop, .katex-html .mbin, .katex-html .mrel, .katex-html .minner"),
		);
		if (!visibleText && !hasMathMarkup) block.remove();
	}
}

function patchPaperPreview() {
	const root = document.querySelector<HTMLElement>(".paper-preview");
	if (!root) return;
	removeInvalidMathPlaceholders(root);
}

export function installPaperPreviewMathCleanupDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined")
		return;
	installed = true;
	addStyle();
	patchPaperPreview();
	const observer = new MutationObserver(patchPaperPreview);
	observer.observe(document.body, { childList: true, subtree: true });
}
