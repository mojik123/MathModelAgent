const STYLE_ID = "paper-preview-dom-patch-style";
let installed = false;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
.paper-preview .paper-toc-content .toc-line,
.paper-preview .paper-toc-content .paper-toc-link {
	cursor: pointer;
	user-select: none;
	border-radius: 6px;
	padding: 2px 6px;
	transition: background .14s ease, color .14s ease;
}

.paper-preview .paper-toc-content .toc-line:hover,
.paper-preview .paper-toc-content .paper-toc-link:hover {
	background: rgba(37, 99, 235, .08);
	color: #1d4ed8;
}

.paper-preview .paper-toc-content [data-sentence] {
	background: transparent !important;
	border-left: none !important;
	outline: none !important;
	padding-left: 6px !important;
}

.paper-preview .paper-toc-content .sentence-hover,
.paper-preview .paper-toc-content .sentence-selected {
	background: transparent !important;
	border-left: none !important;
	outline: none !important;
}

.paper-preview .markdown-table-wrapper {
	margin: 1rem 0;
	overflow-x: auto;
}

.paper-preview table,
.paper-preview .markdown-table {
	width: 100%;
	margin: 0 auto;
	border-collapse: collapse;
	border-top: 1.5px solid #000 !important;
	border-bottom: 1.5px solid #000 !important;
	border-left: none !important;
	border-right: none !important;
}

.paper-preview table thead,
.paper-preview .markdown-table thead {
	border-bottom: 0.75px solid #000 !important;
}

.paper-preview table th,
.paper-preview table td,
.paper-preview .markdown-table th,
.paper-preview .markdown-table td {
	border-left: none !important;
	border-right: none !important;
	border-top: none !important;
	border-bottom: none !important;
	background: transparent !important;
	text-align: center;
}

.paper-preview .markdown-table-caption,
.paper-preview figcaption {
	text-align: center !important;
	font-family: "Times New Roman", "SimSun", "宋体", serif !important;
	font-size: 10.5pt !important;
	font-weight: 400 !important;
	text-indent: 0 !important;
}

.paper-preview math annotation,
.paper-preview .katex-mathml {
	display: none !important;
}
`;
	document.head.appendChild(style);
}

function textOf(node: Element | null) {
	return (node?.textContent || "").replace(/\s+/g, " ").trim();
}

function getPreviewRoot() {
	return document.querySelector<HTMLElement>(".paper-preview");
}

function normalizeTitle(text: string) {
	return text
		.replace(/\.{2,}\s*\d+\s*$/g, "")
		.replace(/\s+\d+\s*$/g, "")
		.replace(/^[\s　]+/g, "")
		.replace(/\s+/g, "")
		.trim();
}

function ensureHeadingIds(root: HTMLElement) {
	const headings = Array.from(root.querySelectorAll<HTMLHeadingElement>("h1, h2, h3, h4"));
	for (const [index, heading] of headings.entries()) {
		if (!heading.id) heading.id = `paper-heading-${index}`;
	}
	return headings.filter((heading) => textOf(heading) !== "目录");
}

function findHeadingForTocLine(headings: HTMLHeadingElement[], lineText: string) {
	const target = normalizeTitle(lineText);
	if (!target) return null;
	return headings.find((heading) => {
		const headingText = normalizeTitle(textOf(heading));
		return headingText && (target.includes(headingText) || headingText.includes(target));
	}) || null;
}

function makeTocClickable() {
	const root = getPreviewRoot();
	if (!root) return;
	const toc = root.querySelector<HTMLElement>(".paper-toc-content");
	if (!toc) return;
	const headings = ensureHeadingIds(root);
	const lines = Array.from(toc.querySelectorAll<HTMLElement>(".toc-line, p, li"));
	for (const line of lines) {
		line.removeAttribute("data-sentence");
		line.classList.remove("sentence-hover", "sentence-selected");
		if (line.dataset.tocClickBound === "true") continue;
		const heading = findHeadingForTocLine(headings, textOf(line));
		if (!heading) continue;
		line.classList.add("paper-toc-link");
		line.dataset.tocTarget = heading.id;
		line.dataset.tocClickBound = "true";
		line.setAttribute("role", "button");
		line.setAttribute("tabindex", "0");
		line.addEventListener("mousedown", (event) => {
			event.preventDefault();
			event.stopPropagation();
		}, true);
		line.addEventListener("mouseup", (event) => {
			event.preventDefault();
			event.stopPropagation();
		}, true);
		line.addEventListener("click", (event) => {
			event.preventDefault();
			event.stopPropagation();
			document.getElementById(heading.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
		}, true);
		line.addEventListener("keydown", (event) => {
			if (event.key !== "Enter" && event.key !== " ") return;
			event.preventDefault();
			document.getElementById(heading.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
		});
	}
}

function patchPaperPreview() {
	makeTocClickable();
}

export function installPaperPreviewDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	addStyle();
	setInterval(patchPaperPreview, 700);
}
