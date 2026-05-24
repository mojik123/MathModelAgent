import { sendArtifactEditMessage } from "@/apis/filesApi";
import { useArtifactEditStore } from "@/stores/artifactEdit";
import { useTaskStore } from "@/stores/task";
import { AgentType } from "@/utils/enum";

const ROOT_ID = "artifact-edit-chat-root";
const STYLE_ID = "artifact-edit-chat-style";
let installed = false;
let inputValue = "";
let sending = false;

function short(text: string, max = 160) {
	const s = (text || "").replace(/\s+/g, " ").trim();
	return s.length > max ? `${s.slice(0, max)}…` : s;
}

function currentTaskId() {
	return window.location.pathname.match(/\/task\/([^/]+)/)?.[1] || window.localStorage.getItem("currentTaskId") || "";
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

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
#${ROOT_ID}{border-top:1px solid rgba(226,232,240,.9);background:rgba(255,255,255,.92);backdrop-filter:blur(12px);padding:.75rem;}
.artifact-edit-chat-ref{display:flex;align-items:flex-start;justify-content:space-between;gap:.75rem;border:1px solid #bfdbfe;background:#eff6ff;color:#1d4ed8;border-radius:1rem;padding:.6rem .75rem;margin-bottom:.5rem;font-size:12px;}
.artifact-edit-chat-ref-title{font-weight:700;color:#1e3a8a;}
.artifact-edit-chat-ref-meta{margin-top:.15rem;color:rgba(29,78,216,.72);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:340px;}
.artifact-edit-chat-ref-excerpt{margin-top:.25rem;color:rgba(30,64,175,.68);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.artifact-edit-chat-clear{border:1px solid #bfdbfe;background:white;color:#1d4ed8;border-radius:999px;padding:.18rem .5rem;font-size:11px;font-weight:700;}
.artifact-edit-chat-row{display:flex;gap:.5rem;align-items:flex-end;}
.artifact-edit-chat-input{min-height:58px;flex:1;resize:none;border:1px solid #cbd5e1;border-radius:.875rem;padding:.55rem .7rem;font-size:13px;line-height:1.45;outline:none;background:white;color:#0f172a;}
.artifact-edit-chat-input:focus{border-color:#60a5fa;box-shadow:0 0 0 3px rgba(96,165,250,.16);}
.artifact-edit-chat-send{border:0;background:#2563eb;color:white;border-radius:.875rem;padding:.55rem .8rem;font-size:13px;font-weight:700;min-height:38px;}
.artifact-edit-chat-send:disabled{background:#94a3b8;cursor:not-allowed;}
.artifact-edit-reference-flash{animation:artifactEditFlash 1.2s ease-out 1;}
@keyframes artifactEditFlash{0%{box-shadow:0 0 0 0 rgba(37,99,235,.45)}100%{box-shadow:0 0 0 14px rgba(37,99,235,0)}}
`;
	document.head.appendChild(style);
}

function getLeftPanel() {
	return document.querySelector<HTMLElement>(".glass-left-panel");
}

function renderInput() {
	const store = useArtifactEditStore();
	let root = document.getElementById(ROOT_ID);
	const panel = getLeftPanel();
	if (!panel) return;
	if (!root) {
		root = document.createElement("div");
		root.id = ROOT_ID;
		panel.appendChild(root);
	}
	const ctx = store.activeContext;
	if (!ctx) {
		root.innerHTML = "";
		root.style.display = "none";
		return;
	}
	root.style.display = "block";
	const typeLabel = ctx.targetType === "image" ? "图片" : "文字";
	root.innerHTML = `
		<div class="artifact-edit-chat-ref artifact-edit-reference-flash">
			<div style="min-width:0;flex:1;">
				<div class="artifact-edit-chat-ref-title">当前修改对象：${ctx.targetLabel}</div>
				<div class="artifact-edit-chat-ref-meta">${typeLabel} · ${ctx.targetPath}</div>
				${ctx.excerpt ? `<div class="artifact-edit-chat-ref-excerpt">${ctx.excerpt}</div>` : ""}
			</div>
			<button class="artifact-edit-chat-clear" type="button">清除</button>
		</div>
		<div class="artifact-edit-chat-row">
			<textarea class="artifact-edit-chat-input" placeholder="${ctx.targetType === "image" ? "输入修图要求，例如：改配色、调标题、放大坐标轴字体..." : "输入文字修改要求，例如：改得更学术、压缩两句话、删掉口语化..."}"></textarea>
			<button class="artifact-edit-chat-send" type="button">${sending ? "修改中" : "发送"}</button>
		</div>
	`;
	const textarea = root.querySelector<HTMLTextAreaElement>("textarea");
	const sendBtn = root.querySelector<HTMLButtonElement>(".artifact-edit-chat-send");
	const clearBtn = root.querySelector<HTMLButtonElement>(".artifact-edit-chat-clear");
	if (textarea) {
		textarea.value = inputValue;
		textarea.disabled = sending;
		textarea.addEventListener("input", () => {
			inputValue = textarea.value;
		});
		textarea.addEventListener("keydown", (event) => {
			if (event.key === "Enter" && !event.shiftKey) {
				event.preventDefault();
				void sendCurrentInstruction();
			}
		});
	}
	if (sendBtn) {
		sendBtn.disabled = sending || !ctx;
		sendBtn.addEventListener("click", () => void sendCurrentInstruction());
	}
	clearBtn?.addEventListener("click", () => {
		store.clearActive();
		inputValue = "";
		renderInput();
	});
}

function addReferenceMessage(ctx: ReturnType<typeof useArtifactEditStore>["activeContext"]) {
	if (!ctx) return;
	const taskStore = useTaskStore();
	const typeLabel = ctx.targetType === "image" ? "图片" : "文字";
	taskStore.addSystemAction(
		"引用",
		`${typeLabel}修改对象`,
		`已引用${typeLabel}：${ctx.targetLabel}\n路径：${ctx.targetPath}${ctx.excerpt ? `\n片段：${short(ctx.excerpt, 220)}` : ""}`,
		{
			from: "User",
			to: ctx.targetType === "image" ? "CoderAgent" : "WriterAgent",
			label: ctx.targetType === "image" ? "引用图片修改" : "引用文字修改",
		},
		"info",
	);
}

function activateImageFromData(data: { filename: string; title?: string; url?: string; description?: string }) {
	const taskId = currentTaskId();
	if (!taskId || !data.filename) return;
	const store = useArtifactEditStore();
	store.restore(taskId);
	const ctx = store.setActive({
		taskId,
		targetType: "image",
		targetPath: data.filename,
		targetLabel: data.title || data.filename.split("/").pop() || data.filename,
		previewUrl: data.url,
		description: data.description,
	});
	addReferenceMessage(ctx);
	inputValue = "";
	renderInput();
	getLeftPanel()?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function activateTextFromData(data: { selectedText: string; context?: string; label?: string }) {
	const taskId = currentTaskId();
	if (!taskId || !data.selectedText.trim()) return;
	const store = useArtifactEditStore();
	store.restore(taskId);
	const excerpt = short(data.selectedText, 400);
	const ctx = store.setActive({
		taskId,
		targetType: "text",
		targetPath: "paper.md",
		targetLabel: data.label || "论文选中文本",
		excerpt,
		description: data.context,
	});
	addReferenceMessage(ctx);
	inputValue = "";
	renderInput();
}

async function sendCurrentInstruction() {
	const store = useArtifactEditStore();
	const taskStore = useTaskStore();
	const ctx = store.activeContext;
	const instruction = inputValue.trim();
	if (!ctx || !instruction || sending) return;
	inputValue = "";
	sending = true;
	store.updateSession(ctx.sessionId, { status: "running" });
	store.appendSessionMessage(ctx.sessionId, "user", instruction);
	taskStore.addUserAction(
		"修改",
		`${ctx.targetType === "image" ? "图片" : "文字"} ${ctx.targetLabel}`,
		`用户请求修改${ctx.targetType === "image" ? "图片" : "文字"} ${ctx.targetLabel}：${instruction}`,
		{
			from: "User",
			to: ctx.targetType === "image" ? "CoderAgent" : "WriterAgent",
			label: ctx.targetType === "image" ? "请求图片修改" : "请求文字修改",
		},
	);
	taskStore.addSystemAction(
		"接收",
		"AI 修改请求",
		`已接收${ctx.targetType === "image" ? "图片" : "文字"}修改请求，正在处理：${ctx.targetLabel}`,
		{
			from: "User",
			to: ctx.targetType === "image" ? "CoderAgent" : "WriterAgent",
			label: "进入修改流程",
		},
		"info",
	);
	renderInput();
	try {
		const currentSession = store.sessions.find((s) => s.sessionId === ctx.sessionId) || ctx;
		const response = await sendArtifactEditMessage({
			task_id: ctx.taskId,
			target_type: ctx.targetType,
			target_path: ctx.targetPath,
			target_label: ctx.targetLabel,
			instruction,
			description: ctx.description,
			selected_text: ctx.excerpt || ctx.targetLabel,
			context: ctx.description || ctx.excerpt,
			conversation_history: currentSession.messages,
		});
		const data = response.data as any;
		const ok = Boolean(data?.success) && data?.status !== "failed";
		const resultText = ctx.targetType === "image"
			? [data?.analysis_text, data?.message, data?.updated_alt_text ? `新标题：${data.updated_alt_text}` : "", data?.updated_caption ? `新说明：${data.updated_caption}` : ""].filter(Boolean).join("\n")
			: [data?.message, data?.revised_text ? `修改后：${data.revised_text}` : ""].filter(Boolean).join("\n");
		store.appendSessionMessage(ctx.sessionId, "assistant", resultText || (ok ? "修改完成" : "修改失败"));
		store.updateSession(ctx.sessionId, { status: ok ? "done" : "failed" });
		if (ok) {
			taskStore.addAgentAction(
				ctx.targetType === "image" ? AgentType.CODER : AgentType.WRITER,
				"返回",
				`${ctx.targetType === "image" ? "图片" : "文字"}修改结果`,
				resultText || `${ctx.targetType === "image" ? "图片" : "文字"}修改完成：${ctx.targetLabel}`,
				{
					from: ctx.targetType === "image" ? "CoderAgent" : "WriterAgent",
					to: "User",
					label: ctx.targetType === "image" ? "返回图片修改结果" : "返回文字修改结果",
				},
			);
			window.dispatchEvent(new CustomEvent("artifact-edit-updated", { detail: { type: ctx.targetType } }));
		} else {
			taskStore.addSystemAction("失败", "AI 修改", resultText || "修改失败", { from: ctx.targetType === "image" ? "CoderAgent" : "WriterAgent", to: "User", label: "返回失败原因" }, "error");
		}
	} catch (error) {
		const message = error instanceof Error ? error.message : "网络错误";
		store.appendSessionMessage(ctx.sessionId, "assistant", `修改失败：${message}`);
		store.updateSession(ctx.sessionId, { status: "failed" });
		taskStore.addSystemAction("失败", "AI 修改", `修改失败：${message}`, { from: ctx.targetType === "image" ? "CoderAgent" : "WriterAgent", to: "User", label: "返回失败原因" }, "error");
	} finally {
		sending = false;
		renderInput();
	}
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
	const title = section.querySelector<HTMLElement>(".font-semibold")?.textContent?.trim() || filename.split("/").pop() || filename;
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
		const selected = document.querySelector<HTMLImageElement>(".paper-preview img.image-selected") || document.querySelector<HTMLImageElement>(".paper-preview img.image-hovered");
		if (!selected) return true;
		activateImageFromData({
			filename: filenameFromSrc(selected.src || selected.getAttribute("src") || ""),
			title: selected.alt || "论文图片",
			url: selected.src,
			description: selected.alt || "",
		});
		return true;
	}
	const selectedTexts = Array.from(document.querySelectorAll<HTMLElement>(".paper-preview .sentence-selected"))
		.map((el) => el.textContent?.trim() || "")
		.filter(Boolean);
	const selected = selectedTexts.join("");
	if (selected) {
		activateTextFromData({ selectedText: selected, context: selectedTexts.join("\n"), label: "论文选中文本" });
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
	addStyle();
	installClickCapture();
	setInterval(renderInput, 700);
	window.addEventListener("popstate", () => renderInput());
}
