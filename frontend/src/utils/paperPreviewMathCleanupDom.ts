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
			block.querySelector(
				".katex-html .mord, .katex-html .mop, .katex-html .mbin, .katex-html .mrel, .katex-html .minner",
			),
		);
		if (!visibleText && !hasMathMarkup) block.remove();
	}
}

function shouldSkipTextNode(node: Text) {
	const parent = node.parentElement;
	return Boolean(
		!parent ||
			parent.closest(
				"pre, code, .katex, .math-block, .paper-equation, script, style",
			),
	);
}

function cleanInternalMetricText(value: string, parentText: string) {
	let cleaned = value
		.replace(/极大型/g, "正向指标")
		.replace(/极小型/g, "负向指标")
		.replace(/中间型/g, "适中型指标")
		.replace(/区间型/g, "区间型指标")
		.replace(
			/(?<=[\u4e00-\u9fff])\s+SC_[A-Za-z0-9_]+(?![A-Za-z0-9_])/g,
			"",
		)
		.replace(
			/\bSC_[A-Za-z0-9_]+\b\s*(?=[（(](?:正向指标|负向指标|适中型指标|区间型指标|单位|无量纲))/g,
			"",
		);

	if (
		/^\s*SC_[A-Za-z0-9_]+\s*$/.test(cleaned) &&
		/[\u4e00-\u9fff]/.test(parentText)
	) {
		cleaned = "";
	}

	return cleaned
		.replace(/[ \t]+([（(：:，,；;。])/g, "$1")
		.replace(/（\s*，/g, "（")
		.replace(/（\s*）/g, "");
}

function normalizeInternalMetricLabels(root: HTMLElement) {
	const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
	let current = walker.nextNode();
	while (current) {
		const node = current as Text;
		current = walker.nextNode();
		if (shouldSkipTextNode(node)) continue;
		const original = node.nodeValue || "";
		if (!original) continue;
		const cleaned = cleanInternalMetricText(
			original,
			node.parentElement?.textContent || "",
		);
		if (cleaned !== original) node.nodeValue = cleaned;
	}
}

function patchPaperPreview() {
	const root = document.querySelector<HTMLElement>(".paper-preview");
	if (!root) return;
	removeInvalidMathPlaceholders(root);
	normalizeInternalMetricLabels(root);
}

export function installPaperPreviewMathCleanupDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined")
		return;
	installed = true;
	addStyle();
	patchPaperPreview();
	const observer = new MutationObserver(patchPaperPreview);
	observer.observe(document.body, { childList: true, subtree: true, characterData: true });
}
