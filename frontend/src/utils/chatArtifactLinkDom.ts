const STYLE_ID = "chat-artifact-link-style";
let installed = false;

const FILE_RE = /([\w\-.\u4e00-\u9fa5/\\]+\.(?:png|jpg|jpeg|webp|svg|py|ipynb|csv|xlsx|xls|md|docx|pdf))/i;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[data-chat-artifact-link="true"] {
	cursor: pointer !important;
	border-color: rgba(37, 99, 235, 0.22) !important;
	background: linear-gradient(135deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.82)) !important;
	color: #1d4ed8 !important;
	transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease !important;
}

[data-chat-artifact-link="true"]:hover {
	transform: translateY(-1px);
	border-color: rgba(37, 99, 235, 0.45) !important;
	box-shadow: 0 8px 20px rgba(37, 99, 235, 0.12) !important;
}

[data-chat-artifact-link="true"]::after {
	content: "点击定位";
	margin-left: auto;
	border-radius: 999px;
	background: rgba(37, 99, 235, 0.08);
	padding: 1px 6px;
	font-size: 10px;
	font-weight: 700;
	color: rgba(37, 99, 235, 0.72);
}

[data-chat-artifact-link-highlight="true"] {
	animation: chatArtifactLinkPulse 1.4s ease-out 1;
}

@keyframes chatArtifactLinkPulse {
	0% { box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.42); }
	100% { box-shadow: 0 0 0 16px rgba(37, 99, 235, 0); }
}
`;
	document.head.appendChild(style);
}

function normalizeFile(text: string) {
	return (text || "").replace(/\\/g, "/").trim();
}

function extractFileName(text: string) {
	const match = (text || "").match(FILE_RE);
	return match ? normalizeFile(match[1]) : "";
}

function fileType(file: string) {
	const lower = file.toLowerCase();
	if (/\.(png|jpg|jpeg|webp|svg)$/.test(lower)) return "image";
	if (/\.(py|ipynb)$/.test(lower)) return "code";
	if (/\.(md|docx|pdf)$/.test(lower)) return "paper";
	return "file";
}

function clickTab(label: string) {
	const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>("button"));
	const target = buttons.find((button) => (button.textContent || "").trim().includes(label));
	target?.click();
}

function openArtifact(file: string) {
	const normalized = normalizeFile(file);
	const type = fileType(normalized);
	if (type === "image") clickTab("图片");
	else if (type === "code") clickTab("代码");
	else if (type === "paper") clickTab("论文预览");

	window.dispatchEvent(
		new CustomEvent("chat-artifact-open", {
			detail: { file: normalized, type },
		}),
	);
}

function isLikelyArtifactChip(node: HTMLElement) {
	const text = node.textContent || "";
	if (!FILE_RE.test(text)) return false;
	const cls = node.getAttribute("class") || "";
	return (
		cls.includes("rounded-xl") ||
		cls.includes("rounded-lg") ||
		cls.includes("truncate") ||
		Boolean(node.closest("[data-chat-artifact-link-host]"))
	);
}

function linkArtifactNodes() {
	const panel = document.querySelector<HTMLElement>(".glass-left-panel");
	if (!panel) return;
	const candidates = Array.from(panel.querySelectorAll<HTMLElement>("div, span, p"));
	for (const node of candidates) {
		if (node.dataset.chatArtifactLink === "true") continue;
		if (!isLikelyArtifactChip(node)) continue;
		const file = extractFileName(node.textContent || "");
		if (!file) continue;
		node.dataset.chatArtifactLink = "true";
		node.dataset.artifactFile = file;
		node.setAttribute("role", "button");
		node.setAttribute("tabindex", "0");
		node.setAttribute("title", `点击在右侧定位：${file}`);
	}
}

function handleClick(event: MouseEvent) {
	const target = event.target as HTMLElement | null;
	const node = target?.closest<HTMLElement>("[data-chat-artifact-link='true']");
	if (!node) return;
	const file = node.dataset.artifactFile || extractFileName(node.textContent || "");
	if (!file) return;
	event.preventDefault();
	event.stopPropagation();
	node.setAttribute("data-chat-artifact-link-highlight", "true");
	setTimeout(() => node.removeAttribute("data-chat-artifact-link-highlight"), 1500);
	openArtifact(file);
}

function handleKeydown(event: KeyboardEvent) {
	if (event.key !== "Enter" && event.key !== " ") return;
	const target = event.target as HTMLElement | null;
	const node = target?.closest<HTMLElement>("[data-chat-artifact-link='true']");
	if (!node) return;
	const file = node.dataset.artifactFile || extractFileName(node.textContent || "");
	if (!file) return;
	event.preventDefault();
	openArtifact(file);
}

export function installChatArtifactLinkDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	addStyle();
	document.addEventListener("click", handleClick, true);
	document.addEventListener("keydown", handleKeydown, true);
	setInterval(linkArtifactNodes, 600);
}
