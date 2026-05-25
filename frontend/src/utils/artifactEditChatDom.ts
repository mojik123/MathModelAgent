import { useArtifactEditStore } from "@/stores/artifactEdit";
import { useTaskStore } from "@/stores/task";

let installed = false;

function short(text: string, max = 160) {
	const s = (text || "").replace(/\s+/g, " ").trim();
	return s.length > max ? `${s.slice(0, max)}…` : s;
}

function currentTaskId() {
	return (
		window.location.pathname.match(/\/task\/([^/]+)/)?.[1] ||
		window.localStorage.getItem("currentTaskId") ||
		""
	);
}

function filenameFromSrc(src: string) {
	try {
		const url = new URL(src, window.location.origin);
		const parts = decodeURIComponent(url.pathname).split("/static/");
		const afterStatic = parts[1] || decodeURIComponent(url.pathname).replace(/^\/+/, "");
		const segments = afterStatic.split("/").filter(Boolean);
		const taskId = currentTaskId();
		if (segments[0] === taskId) return segments.slice(1).join("/");
		return segments.join("/");
	} catch {
		return decodeURIComponent(src.split(/[?#]/)[0].split("/static/").pop() || src);
	}
}

function addReferenceMessage(ctx: any, reused = false) {
	if (!ctx) return;
	const taskStore = useTaskStore();
	const typeLabel = ctx.targetType === "image" ? "图片" : "文字";
	taskStore.addSystemAction(
		reused ? "继续修改" : "引用",
		`${typeLabel}修改对象`,
		`${reused ? "继续修改" : "已引用"}${typeLabel}：${ctx.targetLabel}\n路径：${ctx.targetPath}${ctx.excerpt ? `\n片段：${short(ctx.excerpt, 220)}` : ""}`,
		{
			from: "User",
			to: ctx.targetType === "image" ? "CoderAgent" : "WriterAgent",
			label: ctx.targetType === "image" ? "引用图片修改" : "引用文字修改",
		},
		"info",
	);
}

function activateExistingOrCreate(data: {
	taskId: string;
	targetType: "image" | "text";
	targetPath: string;
	targetLabel: string;
	previewUrl?: string;
	description?: string;
	excerpt?: string;
}) {
	const store = useArtifactEditStore();
	store.restore(data.taskId);
	const existing = store.sessions.find(
		(session) =>
			session.taskId === data.taskId &&
			session.targetType === data.targetType &&
			session.targetPath === data.targetPath,
	);
	if (existing) {
		store.updateSession(existing.sessionId, {
			targetLabel: data.targetLabel || existing.targetLabel,
			previewUrl: data.previewUrl || existing.previewUrl,
			description: data.description || existing.description,
			excerpt: data.excerpt || existing.excerpt,
			status: existing.status === "failed" ? "active" : existing.status,
		});
		store.reactivate(existing.sessionId);
		addReferenceMessage(store.activeContext, true);
		return store.activeContext;
	}
	const ctx = store.setActive({
		taskId: data.taskId,
		targetType: data.targetType,
		targetPath: data.targetPath,
		targetLabel: data.targetLabel,
		previewUrl: data.previewUrl,
		description: data.description,
		excerpt: data.excerpt,
	});
	addReferenceMessage(ctx, false);
	return ctx;
}

function activateImageFromData(data: {
	filename: string;
	title?: string;
	url?: string;
	description?: string;
}) {
	const taskId = currentTaskId();
	if (!taskId || !data.filename) return;
	activateExistingOrCreate({
		taskId,
		targetType: "image",
		targetPath: data.filename,
		targetLabel: data.title || data.filename.split("/").pop() || data.filename,
		previewUrl: data.url,
		description: data.description,
	});
	document.querySelector<HTMLElement>('[data-agent-chat-panel]')?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function activateTextFromData(data: {
	selectedText: string;
	context?: string;
	label?: string;
}) {
	const taskId = currentTaskId();
	if (!taskId || !data.selectedText.trim()) return;
	const excerpt = short(data.selectedText, 400);
	activateExistingOrCreate({
		taskId,
		targetType: "text",
		targetPath: `paper.md#${excerpt.slice(0, 40)}`,
		targetLabel: data.label || "论文选中文本",
		excerpt,
		description: data.context,
	});
}

function interceptImageGalleryButton(event: MouseEvent) {
	const target = event.target as HTMLElement | null;
	const button = target?.closest("button") as HTMLButtonElement | null;
	if (!button) return false;
	const text = button.textContent || "";
	if (!text.includes("修改代码重画") && !text.includes("正在修改")) return false;
	const section = button.closest("section") as HTMLElement | null;
	if (!section) return false;
	const img = section.querySelector<HTMLImageElement>("img");
	const filenameText = Array.from(section.querySelectorAll<HTMLElement>("span,div,p"))
		.map((el) => el.textContent?.trim() || "")
		.find((t) => /\.(png|jpg|jpeg|svg|webp)$/i.test(t));
	const filename = filenameText || (img?.src ? filenameFromSrc(img.src) : "");
	const title =
		section.querySelector<HTMLElement>("[data-image-title-fixed='true']")?.textContent?.trim() ||
		section.querySelector<HTMLElement>(".font-semibold")?.textContent?.trim() ||
		filename.split("/").pop() ||
		filename;
	const desc = section.querySelector<HTMLElement>("p")?.textContent?.trim() || "";
	if (!filename) return false;
	event.preventDefault();
	event.stopPropagation();
	event.stopImmediatePropagation();
	activateImageFromData({ filename, title, url: img?.src, description: desc });
	return true;
}

function interceptWriterActionButton(event: MouseEvent) {
	const target = event.target as HTMLElement | null;
	const button = target?.closest("button") as HTMLButtonElement | null;
	if (!button) return false;
	const text = button.textContent || "";
	if (!text.includes("AI 修图") && !text.includes("AI 修改")) return false;
	event.preventDefault();
	event.stopPropagation();
	event.stopImmediatePropagation();
	if (text.includes("AI 修图")) {
		const selected =
			document.querySelector<HTMLImageElement>(".paper-preview img.image-selected") ||
			document.querySelector<HTMLImageElement>(".paper-preview img.image-hovered");
		if (!selected) return true;
		activateImageFromData({
			filename: filenameFromSrc(selected.src || selected.getAttribute("src") || ""),
			title: selected.alt || "论文图片",
			url: selected.src,
			description: selected.alt || "",
		});
		return true;
	}
	const selectedTexts = Array.from(
		document.querySelectorAll<HTMLElement>(".paper-preview .sentence-selected"),
	)
		.map((el) => el.textContent?.trim() || "")
		.filter(Boolean);
	const selected = selectedTexts.join("");
	if (selected) {
		activateTextFromData({
			selectedText: selected,
			context: selectedTexts.join("\n"),
			label: "论文选中文本",
		});
	}
	return true;
}

function installClickCapture() {
	document.addEventListener(
		"click",
		(event) => {
			if (interceptImageGalleryButton(event)) return;
			interceptWriterActionButton(event);
		},
		true,
	);
}

export function installArtifactEditChatDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	installClickCapture();
}
