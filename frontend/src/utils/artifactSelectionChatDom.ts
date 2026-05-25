import { useTaskStore } from "@/stores/task";

const STYLE_ID = "artifact-selection-chat-dom-style";
let installed = false;
let lastImageSignature = "";
let lastTextSignature = "";
let lastEmitTime = 0;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
.revision-expanded[data-selection-chat-synced="image"] {
	box-shadow: 0 18px 56px rgba(37, 99, 235, .18), 0 0 0 1px rgba(96, 165, 250, .18) !important;
}
`;
	document.head.appendChild(style);
}

function textOf(node: Element | null) {
	return (node?.textContent || "").replace(/\s+/g, " ").trim();
}

function filenameFromSrc(src: string) {
	try {
		const url = new URL(src, window.location.href);
		return decodeURIComponent(url.pathname.split("/").pop() || "");
	} catch {
		return decodeURIComponent((src || "").split(/[?#]/)[0].split("/").pop() || "");
	}
}

function isImageRevisionPanel(panel: HTMLElement) {
	return /AI\s*图片修改/.test(textOf(panel));
}

function isTextRevisionPanel(panel: HTMLElement) {
	return /AI\s*文字修改/.test(textOf(panel));
}

function extractImageInfo(panel: HTMLElement) {
	const img = panel.querySelector<HTMLImageElement>("img");
	const src = img?.src || img?.getAttribute("src") || "";
	const filename =
		Array.from(panel.querySelectorAll<HTMLElement>(".font-medium, [class*='font-medium']"))
			.map(textOf)
			.find((value) => /\.(png|jpg|jpeg|svg|webp|gif)$/i.test(value)) ||
		filenameFromSrc(src) ||
		"未识别图片";
	const alt = img?.alt || "";
	const raw = textOf(panel);
	const codeFound = /已找到生成代码/.test(raw);
	const codeLabel = raw.match(/已找到生成代码（([^）]+)）/)?.[1] || "";
	return { filename, alt, codeFound, codeLabel };
}

function extractTextInfo(panel: HTMLElement) {
	const blocks = Array.from(panel.querySelectorAll<HTMLElement>(".rounded-lg, textarea"));
	const candidate = blocks.map(textOf).find((value) => value && !/AI\s*文字修改|输入修改指令/.test(value)) || "";
	return candidate.slice(0, 120);
}

function shouldThrottle(signature: string) {
	const now = Date.now();
	if (signature === lastImageSignature && now - lastEmitTime < 1800) return true;
	lastEmitTime = now;
	return false;
}

function emitImageSelection(panel: HTMLElement) {
	const info = extractImageInfo(panel);
	const signature = `image:${info.filename}:${info.alt}:${info.codeLabel}`;
	if (shouldThrottle(signature)) return;
	lastImageSignature = signature;
	panel.dataset.selectionChatSynced = "image";
	const taskStore = useTaskStore();
	const codeText = info.codeFound
		? `已找到生成代码${info.codeLabel ? `（${info.codeLabel}）` : ""}`
		: "未找到生成代码，后续会优先基于现有图片或上下文修订";
	const titleText = info.alt && info.alt !== info.filename ? `\n图题：${info.alt}` : "";
	taskStore.addUserAction(
		"选择",
		`图片 ${info.filename}`,
		`用户已选中论文图片，准备进行 AI 修图。\n图片文件：${info.filename}${titleText}\n代码状态：${codeText}\n等待用户输入具体修改要求。`,
		{
			from: "User",
			to: "CoderAgent",
			label: "选择图片待修改",
		},
	);
}

function emitTextSelection(panel: HTMLElement) {
	const text = extractTextInfo(panel);
	if (!text) return;
	const signature = `text:${text}`;
	const now = Date.now();
	if (signature === lastTextSignature && now - lastEmitTime < 1800) return;
	lastTextSignature = signature;
	lastEmitTime = now;
	const taskStore = useTaskStore();
	taskStore.addUserAction(
		"选择",
		"论文文字段落",
		`用户已选中论文文段，准备进行 AI 文字修改。\n选中文段：${text}${text.length >= 120 ? "…" : ""}\n等待用户输入具体修改要求。`,
		{
			from: "User",
			to: "WriterAgent",
			label: "选择文字待修改",
		},
	);
}

function syncExpandedRevisionPanel() {
	const panel = document.querySelector<HTMLElement>(".revision-expanded");
	if (!panel) return;
	if (isImageRevisionPanel(panel)) {
		emitImageSelection(panel);
		return;
	}
	if (isTextRevisionPanel(panel)) {
		emitTextSelection(panel);
	}
}

export function installArtifactSelectionChatDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	addStyle();
	setInterval(syncExpandedRevisionPanel, 600);
}
