<script setup lang="ts">
import {
	getImageCode,
	getPaper,
	reviseImageChat,
	reviseTextChat,
	savePaper,
} from "@/apis/filesApi";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useTaskStore } from "@/stores/task";
import { AgentType } from "@/utils/enum";
import { renderMarkdown } from "@/utils/markdown";
import type { InterpreterMessage, WriterMessage } from "@/utils/response";
import {
	CheckCircle2,
	ChevronDown,
	Code2,
	ImageIcon,
	ListTree,
	MessageSquare,
	PanelLeftClose,
	PanelLeftOpen,
	RefreshCw,
	Send,
	X,
} from "lucide-vue-next";
import {
	computed,
	nextTick,
	onBeforeUnmount,
	onMounted,
	ref,
	watch,
} from "vue";
import { useRoute } from "vue-router";

// ---- Types ----

interface TocItem {
	id: string;
	level: number;
	text: string;
}

interface SelectedImage {
	filename: string;
	src: string;
	alt?: string;
	code?: string | null;
	cellIndex?: number | null;
	description?: string | null;
	caption?: string | null;
}

interface RevisionSession {
	id: string;
	type: "image" | "text";
	status:
		| "idle"
		| "pending"
		| "running"
		| "streaming"
		| "success"
		| "failed"
		| "applied";
	messages: Array<{ role: "user" | "assistant"; content: string }>;
	filename?: string;
	src?: string;
	alt?: string;
	selectedText: string;
	selectedImage?: SelectedImage;
	context?: string;
	latestRevisedText?: string;
	autoApplied?: boolean;
	createdAt?: number;
	updatedAt?: number;
	position?: { top: number; left: number };
	minimized: boolean;
}

// ---- Props ----

const props = defineProps<{
	messages: WriterMessage[];
	writerSequence: string[];
	refreshKey?: number;
}>();

// ---- Router & Store ----

const route = useRoute();
const taskStore = useTaskStore();
const taskId = computed(() => route.params.task_id as string);

// ---- TOC ----

const showToc = ref(true);
const tocScrollHost = ref<HTMLDivElement | null>(null);
const activeHeadingId = ref<string | null>(null);

// ---- Text selection ----

const hoveredEl = ref<HTMLElement | null>(null);
const selectStartEl = ref<HTMLElement | null>(null);
const isSelecting = ref(false);
const selectedText = ref("");
const selectedContext = ref("");
const selectionType = ref<"text" | "image" | null>(null);

// Image selection
const hoveredImageEl = ref<HTMLImageElement | null>(null);
const selectedImage = ref<SelectedImage | null>(null);

// Floating action button
const showActionBtn = ref(false);
const actionBtnPos = ref({ top: 0, left: 0 });
let actionBtnTimer: ReturnType<typeof setTimeout> | null = null;
let imageHoverTimer: ReturnType<typeof setTimeout> | null = null;

// ---- Revision sessions ----

const revisionSessions = ref<RevisionSession[]>([]);
const activeSessionId = ref<string | null>(null);
const expandedSession = computed<RevisionSession | null>(
	() =>
		revisionSessions.value.find(
			(s) => s.id === activeSessionId.value && !s.minimized,
		) ?? null,
);
const chatInput = ref("");
const chatSending = ref(false);
const applyingSessionId = ref<string | null>(null);
const highlightedSessionId = ref<string | null>(null);
const dockedSessions = computed<RevisionSession[]>(() =>
	revisionSessions.value.filter(
		(s) => s.id !== activeSessionId.value || s.minimized,
	),
);

// ---- 拖拽状态 ----

const dragging = ref<{
	sessionId: string;
	offsetX: number;
	offsetY: number;
	startX: number;
	startY: number;
} | null>(null);

function startDrag(e: MouseEvent, sessionId: string) {
	const panel = (e.currentTarget as HTMLElement).closest(".revision-expanded");
	if (!panel) return;
	const rect = panel.getBoundingClientRect();
	dragging.value = {
		sessionId,
		offsetX: e.clientX - rect.left,
		offsetY: e.clientY - rect.top,
		startX: rect.left,
		startY: rect.top,
	};
	document.addEventListener("mousemove", onDrag);
	document.addEventListener("mouseup", stopDrag);
	e.preventDefault();
}

function onDrag(e: MouseEvent) {
	if (!dragging.value) return;
	const session = revisionSessions.value.find(
		(s) => s.id === dragging.value?.sessionId,
	);
	if (!session) return;
	session.position = {
		left: e.clientX - dragging.value.offsetX,
		top: e.clientY - dragging.value.offsetY,
	};
}

function stopDrag() {
	if (dragging.value) {
		persistRevisionSessions();
		dragging.value = null;
	}
	document.removeEventListener("mousemove", onDrag);
	document.removeEventListener("mouseup", stopDrag);
}

/** 默认将对话框放在右下角 */
function defaultDialogPos() {
	return {
		top: Math.max(60, window.innerHeight - 520),
		left: Math.max(60, window.innerWidth - 460),
	};
}

// ---- Paper content ----

const paperMarkdown = ref("");
const renderedContent = ref("");
const loadingPaper = ref(false);
const paperImageVersion = ref(
	(() => {
		if (typeof window !== "undefined" && taskId.value) {
			const saved = window.localStorage.getItem(
				`paper-image-version:${taskId.value}`,
			);
			return saved ? Number(saved) : Date.now();
		}
		return Date.now();
	})(),
);
const writerScrollHost = ref<HTMLDivElement | null>(null);
const tocItems = ref<TocItem[]>([]);

// ---- Image preview ----

const previewSrc = ref("");
const previewFilename = ref("");

// ---- Helpers ----

function extractFilenameFromImageSrc(src: string): string {
	try {
		const url = new URL(src);
		return decodeURIComponent(url.pathname.split("/").pop() || "");
	} catch {
		return decodeURIComponent(src.split("/").pop() || "");
	}
}

function getImageTarget(el: EventTarget | null): HTMLImageElement | null {
	if (!el || !(el instanceof HTMLElement)) return null;
	if (el instanceof HTMLImageElement) return el;
	return (
		el.querySelector("img") || (el.closest("img") as HTMLImageElement | null)
	);
}

function getSentenceTarget(el: EventTarget | null): HTMLElement | null {
	if (!el || !(el instanceof HTMLElement)) return null;
	return el.closest("[data-sentence]") as HTMLElement | null;
}

function openPreview(src: string, filename: string) {
	previewSrc.value = src;
	previewFilename.value = filename;
}

function clearHover() {
	if (hoveredEl.value) {
		hoveredEl.value.classList.remove("sentence-hover");
		hoveredEl.value = null;
	}
}

function clearImageHoverTimer() {
	if (imageHoverTimer) {
		clearTimeout(imageHoverTimer);
		imageHoverTimer = null;
	}
}

function clearImageHover() {
	clearImageHoverTimer();
	if (hoveredImageEl.value) {
		hoveredImageEl.value.classList.remove("image-hovered");
		hoveredImageEl.value = null;
	}
}

async function loadImageMetadata(filename: string) {
	if (!filename || !taskId.value) return;
	try {
		const res = await getImageCode(taskId.value, filename);
		const metadata = {
			code: res.data.code ?? null,
			cellIndex: res.data.cell_index ?? null,
			description: res.data.description ?? null,
			caption: res.data.caption ?? null,
			alt: res.data.alt_text ?? undefined,
		};
		if (selectedImage.value?.filename === filename) {
			selectedImage.value = {
				...selectedImage.value,
				...metadata,
				alt: metadata.alt ?? selectedImage.value.alt,
			};
		}
		for (const session of revisionSessions.value) {
			if (
				session.type === "image" &&
				session.selectedImage?.filename === filename
			) {
				session.selectedImage = {
					...session.selectedImage,
					...metadata,
					alt: metadata.alt ?? session.selectedImage.alt,
				};
				session.context =
					metadata.description || metadata.caption || session.context || "";
				session.updatedAt = Date.now();
			}
		}
		persistRevisionSessions();
	} catch (error) {
		console.warn("Load image metadata failed:", error);
	}
}

function codeBlockNumberForCode(code?: string | null) {
	if (!code?.trim()) return null;
	const targetCode = code.trim();
	let codeNumber = 0;
	for (const message of taskStore.interpreterMessage as InterpreterMessage[]) {
		if (!message.input?.code) continue;
		codeNumber += 1;
		if (message.input.code.trim() === targetCode) return codeNumber;
	}
	return null;
}

function imageCodeLocationLabel(image: SelectedImage) {
	const codeNumber = codeBlockNumberForCode(image.code);
	if (codeNumber != null) return `代码 #${codeNumber}`;
	if (image.cellIndex != null) return `Cell ${image.cellIndex}`;
	return "代码 ?";
}

function getSessionStorageKey() {
	return `writer-revision-sessions:${taskId.value}`;
}

function persistRevisionSessions() {
	if (typeof window === "undefined" || !taskId.value) return;
	window.localStorage.setItem(
		getSessionStorageKey(),
		JSON.stringify(revisionSessions.value),
	);
}

function normalizeRevisionSession(
	session: Partial<RevisionSession>,
): RevisionSession | null {
	if (!session?.id || (session.type !== "image" && session.type !== "text")) {
		return null;
	}
	return {
		id: session.id,
		type: session.type,
		status: session.status ?? "idle",
		messages: Array.isArray(session.messages) ? session.messages : [],
		filename: session.filename,
		src: session.src,
		alt: session.alt,
		selectedText: session.selectedText ?? "",
		selectedImage: session.selectedImage,
		context: session.context ?? "",
		latestRevisedText: session.latestRevisedText,
		autoApplied: session.autoApplied ?? false,
		createdAt: session.createdAt,
		updatedAt: session.updatedAt,
		position: session.position,
		minimized: session.minimized ?? true,
	};
}

function restoreRevisionSessions() {
	if (typeof window === "undefined" || !taskId.value) return;
	try {
		const raw = window.localStorage.getItem(getSessionStorageKey());
		if (!raw) {
			revisionSessions.value = [];
			activeSessionId.value = null;
			return;
		}
		const parsed = JSON.parse(raw) as Partial<RevisionSession>[];
		revisionSessions.value = Array.isArray(parsed)
			? parsed
					.map((session) => normalizeRevisionSession(session))
					.filter((session): session is RevisionSession => Boolean(session))
			: [];
		activeSessionId.value = null;
	} catch {
		revisionSessions.value = [];
		activeSessionId.value = null;
	}
}

function getPreviewRoot(): HTMLElement | null {
	return (
		writerScrollHost.value?.querySelector<HTMLElement>(".paper-preview") ?? null
	);
}

function getSelectableSentences(): HTMLElement[] {
	const root = getPreviewRoot();
	if (!root) return [];
	return Array.from(
		root.querySelectorAll<HTMLElement>("[data-sentence]"),
	).filter((el) => Boolean(el.textContent?.trim()));
}

function applySentenceRangeHighlight(from: HTMLElement, to: HTMLElement) {
	const sentences = getSelectableSentences();
	const fromIdx = sentences.indexOf(from);
	const toIdx = sentences.indexOf(to);
	if (fromIdx < 0 || toIdx < 0) return;
	const start = Math.min(fromIdx, toIdx);
	const end = Math.max(fromIdx, toIdx);
	for (const [index, el] of sentences.entries()) {
		el.classList.toggle("sentence-selected", index >= start && index <= end);
	}
}

function wrapPreviewSentences() {
	const root = getPreviewRoot();
	if (!root) return;
	const blocks = Array.from(
		root.querySelectorAll<HTMLElement>("p, li, blockquote, td, th, figcaption"),
	);
	let index = 0;
	for (const block of blocks) {
		if (!block.textContent?.trim()) {
			block.removeAttribute("data-sentence");
			continue;
		}
		if (block.closest("pre, code, .katex, .math-block")) continue;
		block.dataset.sentence = String(index++);
	}
}

/** 从渲染后的标题自动生成目录并注入到 # 目录 标题下方 */
function injectPaperToc() {
	const root = getPreviewRoot();
	if (!root) return;

	const allH1 = Array.from(root.querySelectorAll<HTMLHeadingElement>("h1"));
	const tocHeading = allH1.find((h) => h.textContent?.trim() === "目录") as
		| HTMLHeadingElement
		| undefined;
	if (!tocHeading) return;

	// 移除目录标题之后已有的目录内容，将由前端重新生成
	let nextEl = tocHeading.nextElementSibling;
	while (nextEl) {
		const tag = nextEl.tagName;
		if (tag === "H1") break;
		const toRemove = nextEl;
		nextEl = nextEl.nextElementSibling;
		if (
			tag === "OL" ||
			tag === "UL" ||
			(tag === "P" && !toRemove.querySelector("img"))
		) {
			toRemove.remove();
		}
	}

	const allHeadings = Array.from(
		root.querySelectorAll<HTMLHeadingElement>("h1, h2"),
	);
	const tocIndex = allHeadings.indexOf(tocHeading);
	if (tocIndex < 0) return;
	const paperHeadings = allHeadings.slice(tocIndex + 1);
	if (!paperHeadings.length) return;

	// 估计每个章节页数，生成目录条目
	let page = 1; // 摘要页第1页
	const lines: string[] = [];
	for (let i = 0; i < paperHeadings.length; i++) {
		const h = paperHeadings[i];
		const level = Number(h.tagName.slice(1));
		const text = h.textContent?.trim() || "";
		if (!text) continue;

		const pageStr = String(page);
		const indent = level === 2 ? "　　" : "";
		const totalLen = text.length + indent.length + pageStr.length;
		const dots = ".".repeat(Math.max(2, 40 - totalLen));
		const label = level === 1 ? `<b>${text}</b>` : text;
		lines.push(
			`<p class="toc-line" style="margin:0.2rem 0;text-indent:0;font-size:12pt;line-height:1.8;">${indent}${label} ${dots} ${pageStr}</p>`,
		);

		// 粗略页码估算
		if (level === 1 && i > 0) page += 2;
		else page += 1;
	}

	const wrapper = document.createElement("div");
	wrapper.className = "paper-toc-content";
	wrapper.innerHTML = lines.join("\n");
	tocHeading.insertAdjacentElement("afterend", wrapper);
}

function buildTocFromRendered() {
	const root = getPreviewRoot();
	if (!root) {
		tocItems.value = [];
		activeHeadingId.value = null;
		return;
	}
	// 过滤掉目录标题本身
	const headings = Array.from(
		root.querySelectorAll<HTMLHeadingElement>("h1, h2, h3, h4"),
	).filter((h) => h.textContent?.trim() !== "目录");
	tocItems.value = headings.map((heading, index) => {
		if (!heading.id) heading.id = `paper-heading-${index}`;
		return {
			id: heading.id,
			level: Number(heading.tagName.slice(1)),
			text: heading.textContent?.trim() || `Section ${index + 1}`,
		};
	});
	if (!activeHeadingId.value && tocItems.value.length) {
		activeHeadingId.value = tocItems.value[0].id;
	}
}

function keepActiveHeadingVisible() {
	if (!activeHeadingId.value) return;
	nextTick(() => {
		const toc = tocScrollHost.value;
		const activeButton = toc?.querySelector<HTMLElement>(
			`[data-toc-id="${CSS.escape(activeHeadingId.value ?? "")}"]`,
		);
		activeButton?.scrollIntoView({ behavior: "smooth", block: "nearest" });
	});
}

function syncActiveHeading() {
	const container = writerScrollHost.value;
	const root = getPreviewRoot();
	if (!container || !root) return;
	const headings = Array.from(
		root.querySelectorAll<HTMLHeadingElement>("h1, h2, h3, h4"),
	);
	if (!headings.length) {
		activeHeadingId.value = null;
		return;
	}
	const containerTop = container.getBoundingClientRect().top;
	let current = headings[0];
	for (const heading of headings) {
		if (heading.getBoundingClientRect().top - containerTop <= 96) {
			current = heading;
		}
	}
	activeHeadingId.value = current.id;
}

function attachScrollListener() {
	requestAnimationFrame(() => {
		const el = writerScrollHost.value;
		if (!el) return;
		el.removeEventListener("scroll", syncActiveHeading);
		buildTocFromRendered();
		el.addEventListener("scroll", syncActiveHeading, { passive: true });
		syncActiveHeading();
	});
}

function scrollToSection(id: string) {
	const target = document.getElementById(id);
	if (!target) return;
	activeHeadingId.value = id;
	target.scrollIntoView({ behavior: "smooth", block: "start" });
	keepActiveHeadingVisible();
}

async function loadPaper() {
	if (!taskId.value) return;
	loadingPaper.value = true;
	try {
		const res = await getPaper(taskId.value);
		paperMarkdown.value = res.data?.content ?? "";
		renderedContent.value = paperMarkdown.value
			? String(
					await renderMarkdown(paperMarkdown.value, {
						taskId: taskId.value,
						imageVersion: paperImageVersion.value,
					}),
				)
			: "";
		await nextTick();
		wrapPreviewSentences();
		injectPaperToc();
		attachScrollListener();
	} catch (error) {
		console.error("Load paper failed:", error);
		paperMarkdown.value = "";
		renderedContent.value = "";
		tocItems.value = [];
		activeHeadingId.value = null;
	} finally {
		loadingPaper.value = false;
	}
}

// ---- onPaperMouseOver ----

function onPaperMouseOver(e: MouseEvent) {
	// Image hover
	const imgTarget = getImageTarget(e.target);
	if (imgTarget?.closest(".paper-preview")) {
		clearHover();
		if (hoveredImageEl.value && hoveredImageEl.value !== imgTarget) {
			hoveredImageEl.value.classList.remove("image-hovered");
			clearImageHoverTimer();
		}
		hoveredImageEl.value = imgTarget;
		imgTarget.classList.add("image-hovered");
		// hover 1s to show AI button
		const src = imgTarget.src || imgTarget.getAttribute("src") || "";
		const filename = extractFilenameFromImageSrc(src);
		if (!showActionBtn.value || selectedImage.value?.filename !== filename) {
			clearImageHoverTimer();
			imageHoverTimer = setTimeout(() => {
				showImageActionBtn(imgTarget);
			}, 1000);
		}
		return;
	}
	clearImageHover();

	// Sentence hover
	const target = getSentenceTarget(e.target);
	if (!target) {
		clearHover();
		return;
	}
	if (isSelecting.value && selectStartEl.value) {
		applySentenceRangeHighlight(selectStartEl.value, target);
		return;
	}
	if (hoveredEl.value && hoveredEl.value !== target) {
		hoveredEl.value.classList.remove("sentence-hover");
	}
	hoveredEl.value = target;
	target.classList.add("sentence-hover");
}

function onPaperMouseLeave() {
	clearHover();
	clearImageHover();
}

function collectSelectedText(from: HTMLElement, to: HTMLElement): string {
	const sentences = getSelectableSentences();
	const fromIdx = sentences.indexOf(from);
	const toIdx = sentences.indexOf(to);
	if (fromIdx < 0 || toIdx < 0) return "";
	const start = Math.min(fromIdx, toIdx);
	const end = Math.max(fromIdx, toIdx);
	return sentences
		.slice(start, end + 1)
		.map((el) => el.textContent?.trim() ?? "")
		.filter(Boolean)
		.join("");
}

function collectSelectionContext(from: HTMLElement, to: HTMLElement): string {
	const sentences = getSelectableSentences();
	const fromIdx = sentences.indexOf(from);
	const toIdx = sentences.indexOf(to);
	if (fromIdx < 0 || toIdx < 0) return "";
	const start = Math.max(0, Math.min(fromIdx, toIdx) - 4);
	const end = Math.min(sentences.length - 1, Math.max(fromIdx, toIdx) + 4);
	return sentences
		.slice(start, end + 1)
		.map((el) => el.textContent?.trim() ?? "")
		.filter(Boolean)
		.join("");
}

function clearTextSelection() {
	const sentences = getSelectableSentences();
	for (const el of sentences) el.classList.remove("sentence-selected");
	selectedText.value = "";
	selectedContext.value = "";
	selectStartEl.value = null;
}

function clearImageSelection() {
	if (selectedImage.value && !expandedSession.value) {
		// Remove selected class from the image element
		const container = writerScrollHost.value;
		if (container) {
			const imgs = container.querySelectorAll<HTMLImageElement>(
				".paper-preview img.image-selected",
			);
			for (const img of imgs) img.classList.remove("image-selected");
		}
		selectedImage.value = null;
	}
	selectionType.value = null;
}

function clearAllSelections() {
	clearTextSelection();
	clearImageSelection();
	showActionBtn.value = false;
}

function showImageActionBtn(imgTarget: HTMLImageElement) {
	const src = imgTarget.src || imgTarget.getAttribute("src") || "";
	const filename = extractFilenameFromImageSrc(src);
	if (!filename) return;

	clearTextSelection();
	clearImageSelection();
	imgTarget.classList.add("image-selected");

	selectedImage.value = { filename, src, alt: imgTarget.alt || undefined };
	selectionType.value = "image";

	const rect = imgTarget.getBoundingClientRect();
	actionBtnPos.value = {
		top: Math.min(window.innerHeight - 52, Math.max(12, rect.bottom + 8)),
		left: Math.min(window.innerWidth - 160, Math.max(12, rect.right - 140)),
	};
	showActionBtn.value = true;

	void loadImageMetadata(filename);
	openPreview(src, filename);
}

function onPaperMouseDown(e: MouseEvent) {
	if (
		(e.target as HTMLElement).closest(".revision-overlay, .action-btn-overlay")
	)
		return;
	if (actionBtnTimer) clearTimeout(actionBtnTimer);
	showActionBtn.value = false;
	if (activeSessionId.value) minimizeActiveSession();

	// ── Image click ──
	const imgTarget = getImageTarget(e.target);
	if (imgTarget?.closest(".paper-preview")) {
		e.preventDefault();
		clearTextSelection();
		clearImageSelection();

		imgTarget.classList.add("image-selected");
		const src = imgTarget.src || imgTarget.getAttribute("src") || "";
		const filename = extractFilenameFromImageSrc(src);
		if (!filename) return;

		selectedImage.value = {
			filename,
			src,
			alt: imgTarget.alt || undefined,
		};
		selectionType.value = "image";

		// Position action button at bottom-right of image
		const rect = imgTarget.getBoundingClientRect();
		actionBtnPos.value = {
			top: Math.min(window.innerHeight - 52, Math.max(12, rect.bottom + 8)),
			left: Math.min(window.innerWidth - 160, Math.max(12, rect.right - 140)),
		};
		if (actionBtnTimer) clearTimeout(actionBtnTimer);
		actionBtnTimer = setTimeout(() => {
			showActionBtn.value = true;
		}, 300);

		// Load code metadata in background
		void loadImageMetadata(filename);
		openPreview(src, filename);
		return;
	}

	// ── Text selection start ──
	clearImageSelection();
	const target = getSentenceTarget(e.target);
	if (!target) return;

	isSelecting.value = true;
	clearTextSelection();
	selectStartEl.value = target;
	target.classList.add("sentence-selected");
	selectionType.value = "text";
}

function onPaperMouseUp(e: MouseEvent) {
	if (!isSelecting.value) return;
	isSelecting.value = false;
	if (!selectStartEl.value) return;

	const endEl = getSentenceTarget(e.target) || selectStartEl.value;
	applySentenceRangeHighlight(selectStartEl.value, endEl);

	selectedText.value = collectSelectedText(selectStartEl.value, endEl);
	selectedContext.value = collectSelectionContext(
		selectStartEl.value,
		endEl,
	).slice(0, 2400);
	selectStartEl.value = null;

	if (selectedText.value) {
		// 检查是否已有该文本的修改会话，有则高亮而非显示按钮
		const existingSession = revisionSessions.value.find(
			(s) => s.type === "text" && s.selectedText === selectedText.value,
		);
		if (existingSession) {
			highlightedSessionId.value = existingSession.id;
			setTimeout(() => {
				highlightedSessionId.value = null;
			}, 3000);
			return;
		}
		scheduleActionButton(e);
	}
}

function scheduleActionButton(_e: MouseEvent) {
	if (actionBtnTimer) clearTimeout(actionBtnTimer);
	actionBtnTimer = setTimeout(() => {
		const selectedBlocks = getSelectableSentences().filter((el) =>
			el.classList.contains("sentence-selected"),
		);
		if (!selectedBlocks.length) return;
		const lastBlock = selectedBlocks[selectedBlocks.length - 1];
		const rect = lastBlock.getBoundingClientRect();
		actionBtnPos.value = {
			top: Math.min(window.innerHeight - 52, Math.max(12, rect.bottom + 8)),
			left: Math.min(window.innerWidth - 160, Math.max(12, rect.right - 140)),
		};
		showActionBtn.value = true;
	}, 500);
}

// ---- Session open/close ----

function openRevisionChat() {
	if (actionBtnTimer) clearTimeout(actionBtnTimer);
	showActionBtn.value = false;

	if (selectionType.value === "image" && selectedImage.value) {
		openImageRevisionChat();
	} else {
		openTextRevisionChat();
	}
}

function openTextRevisionChat() {
	const id = `rev-txt-${Date.now()}`;
	const nowTime = Date.now();
	const session: RevisionSession = {
		id,
		type: "text",
		selectedText: selectedText.value,
		context: selectedContext.value,
		messages: [],
		minimized: false,
		position: {
			left: Math.min(actionBtnPos.value.left, window.innerWidth - 420),
			top: Math.min(actionBtnPos.value.top, window.innerHeight - 300),
		},
		status: "idle",
		autoApplied: false,
		createdAt: nowTime,
		updatedAt: nowTime,
	};
	revisionSessions.value.push(session);
	activeSessionId.value = id;
	chatInput.value = "";
	persistRevisionSessions();
}

function openImageRevisionChat() {
	if (!selectedImage.value) return;
	const existing = revisionSessions.value.find(
		(session) =>
			session.type === "image" &&
			session.selectedImage?.filename === selectedImage.value?.filename,
	);
	if (existing) {
		existing.selectedImage = {
			...existing.selectedImage,
			...selectedImage.value,
			code: selectedImage.value.code ?? existing.selectedImage?.code,
			description:
				selectedImage.value.description ?? existing.selectedImage?.description,
			caption: selectedImage.value.caption ?? existing.selectedImage?.caption,
		};
		existing.context =
			selectedImage.value.description ||
			selectedImage.value.caption ||
			existing.context ||
			"";
		activateSession(existing.id);
		persistRevisionSessions();
		return;
	}
	const id = `rev-img-${Date.now()}`;
	const nowTime = Date.now();
	const session: RevisionSession = {
		id,
		type: "image",
		selectedText: selectedImage.value.alt || selectedImage.value.filename,
		selectedImage: { ...selectedImage.value },
		context:
			selectedImage.value.description || selectedImage.value.caption || "",
		messages: [],
		minimized: false,
		position: {
			left: Math.min(actionBtnPos.value.left, window.innerWidth - 420),
			top: Math.min(actionBtnPos.value.top, window.innerHeight - 300),
		},
		status: "idle",
		createdAt: nowTime,
		updatedAt: nowTime,
	};
	revisionSessions.value.push(session);
	activeSessionId.value = id;
	chatInput.value = "";
	persistRevisionSessions();
}

function minimizeSession(id: string) {
	const session = revisionSessions.value.find((s) => s.id === id);
	if (session) {
		session.minimized = !session.minimized;
		session.updatedAt = Date.now();
	}
	if (activeSessionId.value === id && session?.minimized) {
		activeSessionId.value = null;
	}
	persistRevisionSessions();
}

function minimizeActiveSession() {
	if (!activeSessionId.value) return;
	const session = revisionSessions.value.find(
		(s) => s.id === activeSessionId.value,
	);
	if (session) {
		session.minimized = true;
		session.updatedAt = Date.now();
	}
	activeSessionId.value = null;
	persistRevisionSessions();
}

function closeSession(id: string) {
	revisionSessions.value = revisionSessions.value.filter((s) => s.id !== id);
	if (activeSessionId.value === id) activeSessionId.value = null;
	if (typeof window !== "undefined") {
		window.localStorage.setItem(
			getSessionStorageKey(),
			JSON.stringify(revisionSessions.value),
		);
	}
}

function activateSession(id: string) {
	// Minimize previously expanded session
	if (activeSessionId.value && activeSessionId.value !== id) {
		const prev = revisionSessions.value.find(
			(s) => s.id === activeSessionId.value,
		);
		if (prev) prev.minimized = true;
	}
	activeSessionId.value = id;
	const session = revisionSessions.value.find((s) => s.id === id);
	if (session) {
		session.minimized = false;
		session.updatedAt = Date.now();
		// Mark as applied (viewed) when user opens a success session
		if (session.status === "success") {
			session.status = "applied";
		}
	}
	chatInput.value = "";
	persistRevisionSessions();
}

// ---- Chip status class ----

function chipStatusClass(session: RevisionSession): string {
	if (session.status === "running") return "chip-running";
	if (session.status === "success") return "chip-success-unseen";
	if (session.status === "applied") return "chip-applied";
	if (session.status === "failed") return "chip-failed";
	return "";
}

// ---- Paper text replacement ----

function replaceFirstLoose(
	source: string,
	selected: string,
	replacement: string,
) {
	const directIndex = source.indexOf(selected);
	if (directIndex >= 0) {
		return {
			updated:
				source.slice(0, directIndex) +
				replacement +
				source.slice(directIndex + selected.length),
			replaced: true,
		};
	}
	const trimmed = selected.trim();
	if (!trimmed) return { updated: source, replaced: false };
	const pattern = trimmed
		.split(/\s+/)
		.map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
		.join("\\s+");
	const match = source.match(new RegExp(pattern));
	if (!match || match.index == null)
		return { updated: source, replaced: false };
	return {
		updated:
			source.slice(0, match.index) +
			replacement +
			source.slice(match.index + match[0].length),
		replaced: true,
	};
}

async function autoApplyTextRevision(session: RevisionSession) {
	const revisedText = session.latestRevisedText?.trim();
	if (!revisedText || !paperMarkdown.value) return;

	const { updated, replaced } = replaceFirstLoose(
		paperMarkdown.value,
		session.selectedText,
		revisedText,
	);
	if (!replaced) return;

	try {
		await savePaper(taskId.value, updated);
		paperMarkdown.value = updated;
		session.selectedText = revisedText;
		session.context = revisedText;
		session.autoApplied = true;
		clearAllSelections();
		await loadPaper();
	} catch {
		// If auto-apply fails, the Apply button will remain visible
	}
}

async function applyRevisionToPaper(sessionId: string) {
	const session = revisionSessions.value.find((s) => s.id === sessionId);
	const revisedText = session?.latestRevisedText?.trim() ?? "";
	if (!session || !revisedText || applyingSessionId.value) return;

	applyingSessionId.value = sessionId;
	taskStore.addUserAction(
		"应用",
		"文字修改结果",
		`用户将 AI 生成的文字修改应用到论文正文：${session.selectedText.slice(0, 80)}${session.selectedText.length > 80 ? "…" : ""}`,
		{
			from: "User",
			to: "WriterAgent",
			label: "确认替换正文",
		},
	);
	try {
		const { updated, replaced } = replaceFirstLoose(
			paperMarkdown.value,
			session.selectedText,
			revisedText,
		);
		if (!replaced) {
			session.messages.push({
				role: "assistant",
				content:
					"没有在当前论文 Markdown 中定位到这段原文，暂时不能自动替换。可以继续让 AI 缩短选择范围后再应用。",
			});
			session.status = "failed";
			session.updatedAt = Date.now();
			return;
		}
		await savePaper(taskId.value, updated);
		paperMarkdown.value = updated;
		session.selectedText = revisedText;
		session.context = revisedText;
		session.status = "applied";
		session.autoApplied = true;
		session.updatedAt = Date.now();
		session.messages.push({
			role: "assistant",
			content: "已应用到论文正文。",
		});
		clearAllSelections();
		await loadPaper();
	} finally {
		applyingSessionId.value = null;
		persistRevisionSessions();
	}
}

// ---- AI send ----

async function sendReviseMessage(sessionId: string) {
	const session = revisionSessions.value.find((s) => s.id === sessionId);
	if (!session || !chatInput.value.trim() || chatSending.value) return;

	const instruction = chatInput.value.trim();
	chatInput.value = "";
	chatSending.value = true;
	session.status = "running";
	session.updatedAt = Date.now();
	session.messages.push({ role: "user", content: instruction });
	if (session.type === "image" && session.selectedImage) {
		taskStore.addUserAction(
			"修改",
			`图片 ${session.selectedImage.filename}`,
			`用户在论文预览中请求修改图片 ${session.selectedImage.filename}：${instruction}`,
			{
				from: "User",
				to: "CoderAgent",
				label: "请求图片重画",
			},
		);
	} else {
		taskStore.addUserAction(
			"修改",
			"论文文字段落",
			`用户请求修改论文文字：${instruction}\n\n选中文本：${session.selectedText.slice(0, 180)}${session.selectedText.length > 180 ? "…" : ""}`,
			{
				from: "User",
				to: "WriterAgent",
				label: "请求文字修改",
			},
		);
	}
	persistRevisionSessions();

	try {
		if (session.type === "image" && session.selectedImage) {
			await _sendImageRevision(session, instruction);
		} else {
			await _sendTextRevision(session, instruction);
		}
	} finally {
		chatSending.value = false;
		persistRevisionSessions();
	}
}

async function _sendTextRevision(
	session: RevisionSession,
	instruction: string,
) {
	try {
		const res = await reviseTextChat(
			taskId.value,
			instruction,
			session.selectedText,
			session.context,
			session.messages.slice(0, -1),
		);
		const revisedText = res.data?.revised_text ?? "";
		const updatedPaper = res.data?.updated_paper?.trim() ?? "";
		session.latestRevisedText = revisedText || session.latestRevisedText;
		session.updatedAt = Date.now();

		if (res.data?.success && updatedPaper) {
			paperMarkdown.value = updatedPaper;
			session.autoApplied = true;
			session.status = "success";
			taskStore.addAgentAction(
				AgentType.WRITER,
				"返回",
				"整篇论文修改结果",
				res.data.message ||
					"WriterAgent 已根据完整论文、建模思路和代码结果完成整篇论文同步修改。",
				{
					from: "WriterAgent",
					to: "User",
					label: "返回文字结果",
				},
			);
			session.messages.push({
				role: "assistant",
				content:
					res.data.message ||
					"已根据完整论文、建模思路和代码结果完成整篇论文同步修改。",
			});
			clearAllSelections();
			await loadPaper();
		} else if (res.data?.success && revisedText) {
			const orig =
				session.selectedText.slice(0, 100) +
				(session.selectedText.length > 100 ? "…" : "");
			const rev =
				revisedText.slice(0, 100) + (revisedText.length > 100 ? "…" : "");
			session.messages.push({
				role: "user",
				content: "已收到修改建议，准备应用到论文。",
			});
			session.messages.push({
				role: "assistant",
				content: `修改完成！改动如下：\n\n【原文】${orig}\n\n【修改后】${rev}`,
			});
			session.status = "success";
			taskStore.addAgentAction(
				AgentType.WRITER,
				"返回",
				"文字修改结果",
				`WriterAgent 已生成段落修改建议：${rev}`,
				{
					from: "WriterAgent",
					to: "User",
					label: "返回文字结果",
				},
			);
			// Auto-apply in background; if it fails, Apply button remains
			await autoApplyTextRevision(session);
		} else {
			session.status = res.data?.success ? "success" : "failed";
			session.messages.push({
				role: "assistant",
				content: res.data?.message ?? "修改完成",
			});
		}
	} catch (error) {
		session.status = "failed";
		session.updatedAt = Date.now();
		session.messages.push({
			role: "assistant",
			content: `修改失败：${error instanceof Error ? error.message : "网络错误"}`,
		});
	}
}

async function _sendImageRevision(
	session: RevisionSession,
	instruction: string,
) {
	if (!session.selectedImage) return;
	try {
		const res = await reviseImageChat(
			taskId.value,
			session.selectedImage.filename,
			instruction,
			session.selectedImage.alt || session.selectedImage.filename,
			session.selectedImage.description ||
				session.selectedImage.caption ||
				undefined,
			session.messages.slice(0, -1),
		);
		session.updatedAt = Date.now();

		if (res.data?.success) {
			// Update image metadata in session
			if (res.data.updated_alt_text) {
				session.selectedImage = {
					...session.selectedImage,
					alt: res.data.updated_alt_text,
				};
			}
			if (res.data.updated_caption) {
				session.selectedImage = {
					...session.selectedImage,
					caption: res.data.updated_caption,
					description: res.data.updated_caption,
				};
			}
			if (res.data.image_url) {
				session.selectedImage = {
					...session.selectedImage,
					src: `${res.data.image_url}?t=${Date.now()}`,
				};
			}

			const captionLine = res.data.updated_caption
				? `\n\n**新图说明**：${res.data.updated_caption}`
				: "";
			const altLine = res.data.updated_alt_text
				? `\n**新图标题**：${res.data.updated_alt_text}`
				: "";
			session.messages.push({
				role: "user",
				content: "已收到图片修改结果，论文正在同步更新。",
			});
			session.messages.push({
				role: "assistant",
				content: `图片修改完成！改动如下：\n\n${res.data.analysis_text}${altLine}${captionLine}\n\n图片已重新生成，论文已同步更新。`,
			});
			session.status = "success";
			taskStore.addAgentAction(
				AgentType.CODER,
				"重画",
				`图片 ${session.selectedImage.filename}`,
				res.data.analysis_text || "图片已重新生成，论文已同步更新。",
				{
					from: "CoderAgent",
					to: "WriterAgent",
					label: "同步论文图文",
				},
			);

			// 更新图片版本号，确保刷新后能加载新图片（绕过浏览器缓存）
			paperImageVersion.value = Date.now();
			// 持久化版本号到localStorage，重启后保持一致
			if (typeof window !== "undefined" && taskId.value) {
				window.localStorage.setItem(
					`paper-image-version:${taskId.value}`,
					String(paperImageVersion.value),
				);
			}
			// Auto-reload paper (backend already regenerated image + updated markdown)
			await loadPaper();
		} else {
			session.status = "failed";
			session.messages.push({
				role: "assistant",
				content: `修改失败：${res.data?.message || "未知错误"}\n\n${res.data?.analysis_text || ""}`,
			});
		}
	} catch (error) {
		session.status = "failed";
		session.updatedAt = Date.now();
		session.messages.push({
			role: "assistant",
			content: `图片修改失败：${error instanceof Error ? error.message : "网络错误"}`,
		});
	}
}

// ---- Global pointer handler ----

function onDocumentPointerDown(e: PointerEvent) {
	if (!activeSessionId.value) return;
	const target = e.target as HTMLElement | null;
	if (target?.closest(".revision-overlay, .action-btn-overlay")) return;
	minimizeActiveSession();
}

// ---- Lifecycle ----

onMounted(() => {
	restoreRevisionSessions();
	attachScrollListener();
	document.addEventListener("pointerdown", onDocumentPointerDown);
});

onBeforeUnmount(() => {
	writerScrollHost.value?.removeEventListener("scroll", syncActiveHeading);
	if (actionBtnTimer) clearTimeout(actionBtnTimer);
	document.removeEventListener("pointerdown", onDocumentPointerDown);
	showActionBtn.value = false;
	activeSessionId.value = null;
	selectedText.value = "";
	selectedImage.value = null;
});

watch(
	() => [props.messages, props.writerSequence, props.refreshKey, taskId.value],
	() => {
		void loadPaper();
	},
	{ immediate: true, deep: true },
);

watch(
	renderedContent,
	() => {
		attachScrollListener();
		nextTick(() => {
			wrapPreviewSentences();
			injectPaperToc();
		});
	},
	{ flush: "post" },
);

watch(
	() => taskId.value,
	() => {
		restoreRevisionSessions();
		// 加载当前任务的图片版本号
		if (typeof window !== "undefined" && taskId.value) {
			const saved = window.localStorage.getItem(
				`paper-image-version:${taskId.value}`,
			);
			paperImageVersion.value = saved ? Number(saved) : Date.now();
		}
	},
);
</script>

<template>
	<div class="flex h-full min-h-0 bg-white/70 backdrop-blur-sm">
		<!-- 目录侧栏 -->
		<aside v-if="showToc" class="w-60 shrink-0 bg-slate-50/90 backdrop-blur-xl">
			<div class="flex items-center justify-between bg-gradient-to-b from-white/70 to-white/35 px-3 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.85)] backdrop-blur-md">
				<div class="flex items-center gap-2 text-sm font-semibold text-slate-800">
					<ListTree class="h-4 w-4" />
					<span class="bg-gradient-to-b from-slate-900 to-slate-500 bg-clip-text text-transparent">论文目录</span>
				</div>
				<Button variant="ghost" size="icon" @click="showToc = false"><PanelLeftClose class="h-4 w-4" /></Button>
			</div>
			<div ref="tocScrollHost" class="paper-toc-scroll h-[calc(100%-45px)] overflow-y-auto overflow-x-hidden">
				<div class="p-2">
					<button
						v-for="item in tocItems"
						:key="item.id"
						type="button"
						:data-toc-id="item.id"
						class="toc-item block w-full rounded px-2 py-1.5 text-left text-xs leading-5 transition-colors"
						:class="activeHeadingId === item.id ? 'toc-item-active bg-blue-100 text-blue-700 ring-1 ring-blue-200' : 'text-slate-600 hover:bg-white hover:text-blue-600'"
						:style="{ paddingLeft: `${8 + (item.level - 1) * 12}px` }"
						@click="scrollToSection(item.id)"
					>{{ item.text }}</button>
				</div>
			</div>
		</aside>

		<!-- 论文正文区域 -->
		<div class="flex min-w-0 flex-1 flex-col bg-white/80 backdrop-blur-sm">
			<div class="flex items-center justify-between bg-gradient-to-b from-white/72 to-white/42 px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.85)] backdrop-blur-md">
				<div class="flex items-center gap-2">
					<Button v-if="!showToc" variant="ghost" size="icon" @click="showToc = true"><PanelLeftOpen class="h-4 w-4" /></Button>
					<h2 class="text-base font-semibold text-gray-900">论文内容</h2>
				</div>
				<span v-if="loadingPaper" class="text-xs text-slate-500">加载中...</span>
			</div>
			<div
				ref="writerScrollHost"
				class="paper-content-scroll min-h-0 flex-1 overflow-y-auto overflow-x-hidden"
				@mouseover="onPaperMouseOver"
				@mouseleave="onPaperMouseLeave"
				@mousedown="onPaperMouseDown"
				@mouseup="onPaperMouseUp"
			>
				<article class="mx-auto max-w-4xl px-8 py-6">
					<div v-if="renderedContent" class="paper-preview glass-card prose prose-slate max-w-none" v-html="renderedContent" />
					<div v-else class="glass-card flex h-40 items-center justify-center text-sm text-slate-500">暂无论文内容</div>
				</article>
			</div>
		</div>

		<!-- =====================================================
		     Teleport 浮层：动作按钮 + 修改会话面板
		     ===================================================== -->
		<Teleport to="body">
			<template v-if="showActionBtn || dockedSessions.length > 0 || expandedSession">

			<!-- 浮动 AI 修改按钮 -->
			<div
				v-if="showActionBtn"
				class="action-btn-overlay fixed z-[70]"
				:style="{ top: `${actionBtnPos.top}px`, left: `${actionBtnPos.left}px` }"
			>
				<Button
					size="sm"
					class="glass-action-btn rounded-full px-3 py-1.5 text-xs shadow-lg"
					@click.stop="openRevisionChat"
				>
					<ImageIcon v-if="selectionType === 'image'" class="mr-1 h-3.5 w-3.5" />
					<MessageSquare v-else class="mr-1 h-3.5 w-3.5" />
					{{ selectionType === 'image' ? 'AI 修图' : 'AI 修改' }}
				</Button>
			</div>

			<!-- 修改会话 dock + 展开面板（可拖拽） -->
			<div
				class="revision-overlay fixed inset-0 z-[60] pointer-events-none"
			>
				<!-- dock 固定在右下角 -->
				<div class="fixed bottom-4 right-4 flex flex-col-reverse items-end gap-2" style="max-width: 440px;"
				>
				<!-- 最小化 chip（停靠栏） -->
				<div
					v-for="session in dockedSessions"
					:key="session.id"
					class="revision-minibar flex items-center gap-2 rounded-lg border border-white/30 bg-white/90 backdrop-blur-md px-3 py-1.5 text-xs shadow-lg cursor-pointer select-none"
					:class="[chipStatusClass(session), { 'highlight-pulse': highlightedSessionId === session.id }]"
					style="pointer-events: auto;"
					@click="activateSession(session.id)"
				>
					<!-- 状态指示 -->
					<RefreshCw v-if="session.status === 'running'" class="h-3.5 w-3.5 shrink-0 animate-spin text-blue-500" />
					<ImageIcon v-else-if="session.type === 'image'" class="h-3.5 w-3.5 shrink-0 text-violet-500" />
					<MessageSquare v-else class="h-3.5 w-3.5 shrink-0 text-blue-500" />

					<!-- 图片缩略图（图片会话） -->
					<img
						v-if="session.type === 'image' && session.selectedImage?.src"
						:src="session.selectedImage.src"
						:alt="session.selectedImage.alt || 'preview'"
						class="h-6 w-6 rounded object-cover border border-white/40 shrink-0"
					/>

					<span class="truncate max-w-[180px] text-slate-600">
						{{ session.type === 'image'
							? (session.selectedImage?.alt || session.selectedImage?.filename || '图片修改')
							: session.selectedText.slice(0, 40) + (session.selectedText.length > 40 ? '…' : '')
						}}
					</span>
					<button
						type="button"
						class="ml-1 rounded p-0.5 text-slate-400 hover:text-red-500 transition-colors"
						@click.stop="closeSession(session.id)"
					>
						<X class="h-3.5 w-3.5" />
					</button>
				</div>
				</div>

				<!-- 展开面板（可拖拽，位置记忆） -->
				<div
					v-if="expandedSession"
					class="revision-expanded fixed w-[400px] flex flex-col gap-3 rounded-xl border border-white/40 bg-white/92 backdrop-blur-xl p-4 shadow-2xl cursor-default"
					:class="{ 'shadow-[0_16px_48px_rgba(0,0,0,0.2)]': dragging?.sessionId === expandedSession.id }"
					:style="{
						pointerEvents: 'auto',
						left: `${expandedSession.position?.left ?? 0}px`,
						top: `${expandedSession.position?.top ?? 0}px`,
					}"
				>
					<!-- 标题栏（拖拽手柄） -->
					<div
						class="flex items-center justify-between cursor-grab active:cursor-grabbing select-none"
						@mousedown="startDrag($event, expandedSession.id)"
					>
						<div class="flex items-center gap-2">
							<ImageIcon v-if="expandedSession.type === 'image'" class="h-4 w-4 text-violet-500" />
							<MessageSquare v-else class="h-4 w-4 text-blue-500" />
							<span class="text-sm font-semibold text-slate-800">
								{{ expandedSession.type === 'image' ? 'AI 图片修改' : 'AI 文字修改' }}
							</span>
						</div>
						<div class="flex items-center gap-1">
							<Button variant="ghost" size="icon" class="h-7 w-7" @click="minimizeSession(expandedSession.id)">
								<ChevronDown class="h-4 w-4" />
							</Button>
							<Button variant="ghost" size="icon" class="h-7 w-7" @click="closeSession(expandedSession.id)">
								<X class="h-4 w-4" />
							</Button>
						</div>
					</div>

					<!-- 图片会话：图片预览 + 代码摘要 -->
					<template v-if="expandedSession.type === 'image' && expandedSession.selectedImage">
						<div class="flex gap-3 rounded-lg border bg-slate-50 p-2">
							<img
								:src="expandedSession.selectedImage.src"
								:alt="expandedSession.selectedImage.alt || '图片预览'"
								class="h-20 w-20 shrink-0 rounded-md object-cover border border-slate-200"
							/>
							<div class="min-w-0 flex-1 text-xs text-slate-600 space-y-1">
								<div class="font-medium text-slate-800 truncate">{{ expandedSession.selectedImage.filename }}</div>
								<div v-if="expandedSession.selectedImage.alt" class="truncate text-slate-500">
									标题：{{ expandedSession.selectedImage.alt }}
								</div>
								<div v-if="expandedSession.selectedImage.description || expandedSession.selectedImage.caption" class="line-clamp-2 text-slate-500">
									{{ expandedSession.selectedImage.description || expandedSession.selectedImage.caption }}
								</div>
								<div v-if="expandedSession.selectedImage.code" class="flex items-center gap-1 text-violet-600">
									<Code2 class="h-3 w-3" />
									<span>已找到生成代码（{{ imageCodeLocationLabel(expandedSession.selectedImage) }}）</span>
								</div>
								<div v-else class="text-amber-600 text-[10px]">未找到生成代码，修改可能受限</div>
							</div>
						</div>
					</template>

					<!-- 文字会话：选中文字预览 -->
					<template v-else>
						<div class="rounded-lg border bg-slate-50 p-2 text-xs leading-5 text-slate-600 max-h-24 overflow-y-auto">
							{{ expandedSession.selectedText.slice(0, 500) }}{{ expandedSession.selectedText.length > 500 ? '…' : '' }}
						</div>
					</template>

					<!-- 对话历史 -->
					<div class="flex-1 min-h-[120px] max-h-[260px] overflow-y-auto space-y-2 rounded-lg border bg-slate-50 p-2">
						<div
							v-if="expandedSession.messages.length === 0"
							class="text-xs text-slate-400 text-center py-6"
						>
							{{ expandedSession.type === 'image'
								? '输入修改指令，AI 将修改绘图代码重新生成图片'
								: '输入修改指令，AI 将基于选中内容进行修改' }}
						</div>
						<div
							v-for="(msg, idx) in expandedSession.messages"
							:key="idx"
							class="text-xs"
							:class="msg.role === 'user' ? 'text-right' : 'text-left'"
						>
							<span
								class="inline-block rounded-lg px-2.5 py-1.5 max-w-[90%] whitespace-pre-wrap"
								:class="msg.role === 'user' ? 'bg-blue-500 text-white' : 'bg-white border text-slate-700 shadow-sm'"
							>{{ msg.content }}</span>
						</div>
						<div v-if="chatSending && activeSessionId === expandedSession.id" class="text-left">
							<span class="inline-flex items-center gap-1 rounded-lg border bg-white px-2.5 py-1.5 text-xs text-slate-400 shadow-sm">
								<RefreshCw class="h-3 w-3 animate-spin" />AI 正在修改...
							</span>
						</div>
					</div>

					<!-- 输入栏 -->
					<div class="flex gap-2">
						<Textarea
							v-model="chatInput"
							rows="2"
							:placeholder="expandedSession.type === 'image' ? '描述你想如何修改这张图片...' : '描述你想如何修改这段文字...'"
							:disabled="chatSending"
							class="flex-1 text-xs"
							@keydown.enter.exact.prevent="sendReviseMessage(expandedSession.id)"
						/>
						<Button
							size="sm"
							:disabled="chatSending || !chatInput.trim()"
							class="shrink-0 self-end"
							@click="sendReviseMessage(expandedSession.id)"
						>
							<Send v-if="!chatSending" class="h-3.5 w-3.5" />
							<RefreshCw v-else class="h-3.5 w-3.5 animate-spin" />
						</Button>
					</div>

					<!-- 手动应用按钮（文字会话，auto-apply 失败时显示） -->
					<Button
						v-if="expandedSession.type === 'text' && expandedSession.latestRevisedText && !expandedSession.autoApplied && expandedSession.status !== 'applied'"
						size="sm"
						variant="outline"
						class="w-full text-xs font-medium text-green-700 border-green-300 hover:bg-green-50"
						:disabled="!!applyingSessionId"
						@click="applyRevisionToPaper(expandedSession.id)"
					>
						<CheckCircle2 class="mr-1.5 h-3.5 w-3.5" />
						{{ applyingSessionId === expandedSession.id ? '应用中...' : '应用到论文' }}
					</Button>

					<!-- 已应用提示 -->
					<div
						v-if="expandedSession.type === 'text' && expandedSession.autoApplied"
						class="flex items-center gap-1.5 text-xs text-green-700"
					>
						<CheckCircle2 class="h-3.5 w-3.5" />已自动应用到论文
					</div>
				</div>
			</div>

			</template>
		</Teleport>
	</div>
</template>

<style scoped>
@import 'katex/dist/katex.min.css';

/* ---- 论文预览（中文学术排版规范） ----
   论文题目/一级标题: 黑体 四号(14pt) 居中
   二级标题: 黑体 小四(12pt) 左对齐
   正文: 宋体(中文) + Times New Roman(西文/数字) 小四(12pt)
   段首缩进2字符, 多倍行距1.25
---- */
.paper-preview { color: #000; }

/* 一级标题（论文题目 + 摘要/问题重述等章节标题）: 黑体 四号 居中 */
.paper-preview :deep(h1) {
	margin: 1.5rem 0 1rem;
	text-align: center;
	font-family: "SimHei", "黑体", "Microsoft YaHei", "微软雅黑", sans-serif;
	font-size: 14pt;
	font-weight: 700;
	color: #000;
}

/* 二级标题（2.1 模型假设等）: 黑体 小四 左对齐 */
.paper-preview :deep(h2) {
	margin: 1.25rem 0 0.75rem;
	text-align: left;
	font-family: "SimHei", "黑体", "Microsoft YaHei", "微软雅黑", sans-serif;
	font-size: 12pt;
	font-weight: 700;
	color: #000;
}

/* 三级标题 */
.paper-preview :deep(h3) {
	margin: 1rem 0 0.5rem;
	text-align: left;
	font-family: "SimHei", "黑体", "Microsoft YaHei", "微软雅黑", sans-serif;
	font-size: 12pt;
	font-weight: 700;
	color: #000;
}

/* 正文: 宋体 + Times New Roman, 小四(12pt), 首行缩进2字符, 多倍行距1.25 */
.paper-preview :deep(p) {
	margin: 0;
	padding: 0;
	text-indent: 2em;
	line-height: 1.5;
	font-family: "Times New Roman", "SimSun", "宋体", serif;
	font-size: 12pt;
	color: #000;
}

/* 图片所在的段落不缩进 */
.paper-preview :deep(p:has(img)),
.paper-preview :deep(p:has(figure)) {
t/* 目录（自动生成） */
.paper-preview :deep(.paper-toc-content) {
	margin: 1rem 0;
	padding: 0.5rem 1rem;
}
.paper-preview :deep(.toc-line) {
	font-family: "Times New Roman", "SimSun", "宋体", serif !important;
}
	text-indent: 0;
}

/* 列表 */
.paper-preview :deep(ul), .paper-preview :deep(ol) {
	margin: 0.5rem 0;
	padding-left: 2em;
	font-family: "Times New Roman", "SimSun", "宋体", serif;
	font-size: 12pt;
	line-height: 1.5;
}
.paper-preview :deep(ul) { list-style: disc; }
.paper-preview :deep(ol) { list-style: decimal; }
.paper-preview :deep(li) { margin: 0.15rem 0; }

/* 表格 — 三线表风格 */
.paper-preview :deep(.markdown-table-wrapper) { margin: 1rem 0; overflow-x: auto; }
.paper-preview :deep(table) {
	margin: 0 auto;
	width: 100%;
	border-collapse: collapse;
	border: none;
}
.paper-preview :deep(th), .paper-preview :deep(td) {
	border: none;
	padding: 0.3rem 0.5rem;
	font-family: "Times New Roman", "SimSun", "宋体", serif;
	font-size: 10.5pt;
	line-height: 1.3;
	text-align: center;
}
.paper-preview :deep(thead) {
	border-top: 1.5px solid #000;
	border-bottom: 0.75px solid #000;
}
.paper-preview :deep(th) {
	background: transparent;
	font-weight: 700;
}
.paper-preview :deep(tbody) {
	border-bottom: 1.5px solid #000;
}
.paper-preview :deep(tr) {
	border: none;
}
/* 表标题由 WriterAgent 以加粗段落形式输出，此处做居中处理 */
.paper-preview :deep(.markdown-table-caption) {
	text-align: center;
	font-family: "SimHei", "黑体", "Microsoft YaHei", sans-serif;
	font-size: 10.5pt;
	font-weight: 700;
	margin-bottom: 0.35rem;
}

/* figure 图片容器 */
.paper-preview :deep(figure) { margin: 0.75rem 0; text-align: center; }
.paper-preview :deep(figcaption) {
	margin-top: 0.35rem;
	text-align: center;
	font-family: "SimHei", "黑体", "Microsoft YaHei", sans-serif;
	font-size: 10.5pt;
	font-weight: 600;
	text-indent: 0;
}

/* 图片 */
.paper-preview :deep(img) {
	margin: 0.5rem auto;
	max-width: 100%;
	display: block;
	cursor: pointer;
	transition: outline 0.15s ease, box-shadow 0.15s ease;
	user-select: none;
}

/* 公式块 */
.paper-preview :deep(.math-block), .paper-preview :deep(.katex-display) { overflow-x: auto; text-align: center; }

/* 代码块 */
.paper-preview :deep(pre) { overflow: auto; border-radius: 0.25rem; background: rgba(248, 250, 252, 0.88); padding: 0.75rem; }

/* ---- 图片悬停 / 选中 ---- */
.paper-preview :deep(img.image-hovered) {
	outline: 2px solid rgba(139, 92, 246, 0.45);
	box-shadow: 0 0 0 5px rgba(139, 92, 246, 0.10);
}
.paper-preview :deep(img.image-selected) {
	outline: 2px solid rgba(139, 92, 246, 0.80);
	box-shadow: 0 0 0 7px rgba(139, 92, 246, 0.15);
}

/* ---- 句子悬停高亮 ---- */
.paper-preview :deep(.sentence-hover) {
	background: linear-gradient(90deg, rgba(59,130,246,0.10), rgba(59,130,246,0.04));
	border-radius: 4px;
	outline: 1px solid rgba(59,130,246,0.15);
	transition: background 0.12s ease, outline 0.12s ease;
	cursor: pointer;
}

/* ---- 句子选中高亮 ---- */
.paper-preview :deep(.sentence-selected) {
	background: linear-gradient(90deg, rgba(59,130,246,0.16), rgba(59,130,246,0.08));
	border-radius: 4px;
	border-left: 3px solid rgba(59,130,246,0.65);
	padding-left: 8px;
}

/* ---- 目录 ---- */
.toc-item { position: relative; }
.toc-item-active::before {
	position: absolute;
	top: 0.35rem;
	bottom: 0.35rem;
	left: 0.25rem;
	width: 3px;
	border-radius: 999px;
	background: #2563eb;
	content: "";
}

/* ---- 滚动 ---- */
.paper-toc-scroll,
.paper-content-scroll {
	background: rgba(255, 255, 255, 0.68);
	backdrop-filter: blur(10px);
	-webkit-backdrop-filter: blur(10px);
	mask-image: linear-gradient(to bottom, transparent 0, #000 1.25rem, #000 calc(100% - 1.25rem), transparent 100%);
	-webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 1.25rem, #000 calc(100% - 1.25rem), transparent 100%);
}
.paper-toc-scroll::-webkit-scrollbar,
.paper-content-scroll::-webkit-scrollbar,
.paper-preview :deep(pre::-webkit-scrollbar),
.paper-preview :deep(.math-block::-webkit-scrollbar),
.paper-preview :deep(.katex-display::-webkit-scrollbar) { width: 4px; height: 4px; }
.paper-toc-scroll::-webkit-scrollbar-track,
.paper-content-scroll::-webkit-scrollbar-track,
.paper-preview :deep(pre::-webkit-scrollbar-track),
.paper-preview :deep(.math-block::-webkit-scrollbar-track),
.paper-preview :deep(.katex-display::-webkit-scrollbar-track) { background: transparent; }
.paper-toc-scroll::-webkit-scrollbar-thumb,
.paper-content-scroll::-webkit-scrollbar-thumb,
.paper-preview :deep(pre::-webkit-scrollbar-thumb),
.paper-preview :deep(.math-block::-webkit-scrollbar-thumb),
.paper-preview :deep(.katex-display::-webkit-scrollbar-thumb) { border-radius: 999px; background: rgba(148, 163, 184, 0.75); }
.paper-preview :deep(pre),
.paper-preview :deep(.math-block),
.paper-preview :deep(.katex-display) {
	background-color: rgba(248, 250, 252, 0.68);
	backdrop-filter: blur(8px);
	-webkit-backdrop-filter: blur(8px);
}

/* ---- 玻璃卡片 ---- */
.glass-card {
	border: 1px solid rgba(255, 255, 255, 0.68);
	background: linear-gradient(180deg, rgba(255, 255, 255, 0.82), rgba(248, 250, 252, 0.68));
	box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.8);
	border-radius: 1rem;
	padding: 0.5rem 0;
}

/* ---- 修改按钮（Teleport，用 :global） ---- */
:global(.glass-action-btn) {
	background: linear-gradient(135deg, rgba(59,130,246,0.92), rgba(37,99,235,0.88));
	color: white;
	border: 1px solid rgba(255,255,255,0.3);
	backdrop-filter: blur(8px);
	box-shadow: 0 4px 20px rgba(59,130,246,0.30), 0 0 0 1px rgba(255,255,255,0.2) inset;
	animation: action-btn-in 0.25s ease-out;
}
@keyframes action-btn-in {
	from { opacity: 0; transform: translateY(6px) scale(0.9); }
	to { opacity: 1; transform: translateY(0) scale(1); }
}

/* ---- 修改会话 dock（Teleport） ---- */
:global(.revision-minibar) {
	animation: panel-in 0.2s ease-out;
	box-shadow: 0 4px 16px rgba(0,0,0,0.10), 0 1px 0 rgba(255,255,255,0.6) inset;
}
:global(.revision-expanded) {
	animation: panel-in 0.25s ease-out;
	max-height: min(520px, 82vh);
	overflow-y: auto;
	box-shadow: 0 16px 48px rgba(0,0,0,0.14), 0 1px 0 rgba(255,255,255,0.7) inset;
}
@keyframes panel-in {
	from { opacity: 0; transform: translateY(10px); }
	to { opacity: 1; transform: translateY(0); }
}

/* ================================================================
   Chip 三态动画
   ================================================================ */

/* ── 工作中：彩虹流动边框 ── */
@keyframes chip-rainbow {
	0%   { border-color: #ff6b6b; box-shadow: 0 0 7px rgba(255,107,107,0.55); }
	16%  { border-color: #ffd93d; box-shadow: 0 0 7px rgba(255,217,61,0.55); }
	33%  { border-color: #6bcb77; box-shadow: 0 0 7px rgba(107,203,119,0.55); }
	50%  { border-color: #4d96ff; box-shadow: 0 0 7px rgba(77,150,255,0.55); }
	66%  { border-color: #c77dff; box-shadow: 0 0 7px rgba(199,125,255,0.55); }
	83%  { border-color: #ff9f43; box-shadow: 0 0 7px rgba(255,159,67,0.55); }
	100% { border-color: #ff6b6b; box-shadow: 0 0 7px rgba(255,107,107,0.55); }
}

:global(.chip-running) {
	border-width: 1.5px !important;
	border-style: solid !important;
	animation: chip-rainbow 2.4s linear infinite !important;
}

/* ── 修改完成未查看：蓝色呼吸 ── */
@keyframes chip-breathe-blue {
	0%, 100% {
		border-color: rgba(59,130,246,0.35);
		box-shadow: 0 0 4px rgba(59,130,246,0.15);
	}
	50% {
		border-color: rgba(59,130,246,0.85);
		box-shadow: 0 0 14px rgba(59,130,246,0.45);
	}
}

:global(.chip-success-unseen) {
	border-width: 1.5px !important;
	border-style: solid !important;
	animation: chip-breathe-blue 2s ease-in-out infinite !important;
}

/* ── 已查看/完成：绿色静止 ── */
:global(.chip-applied) {
	border-width: 1.5px !important;
	border-style: solid !important;
	border-color: rgba(34,197,94,0.55) !important;
	box-shadow: 0 0 8px rgba(34,197,94,0.22) !important;
}

/* ── 失败：琥珀脉冲 ── */
@keyframes chip-pulse-amber {
	0%, 100% { border-color: rgba(245,158,11,0.5); }
	50%       { border-color: rgba(245,158,11,0.9); box-shadow: 0 0 8px rgba(245,158,11,0.4); }
}

:global(.chip-failed) {
	border-width: 1.5px !important;
	border-style: solid !important;
	animation: chip-pulse-amber 1.8s ease-in-out infinite !important;
}

/* ====== 高亮的停靠 chip ====== */
:global(.revision-minibar.highlight-pulse) {
	animation: chip-highlight 0.6s ease-in-out 3;
	border-color: #3b82f6 !important;
	box-shadow:
		0 0 16px rgba(59, 130, 246, 0.35),
		0 0 32px rgba(59, 130, 246, 0.15),
		0 0 0 1px rgba(255, 255, 255, 0.6) inset !important;
}

@keyframes chip-highlight {
	0%, 100% { box-shadow: 0 0 8px rgba(59, 130, 246, 0.15); }
	50% { box-shadow: 0 0 20px rgba(59, 130, 246, 0.45), 0 0 32px rgba(59, 130, 246, 0.2); }
}

</style>
