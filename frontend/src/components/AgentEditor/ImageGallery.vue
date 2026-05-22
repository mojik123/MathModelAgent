<script setup lang="ts">
import {
	getFiles,
	getImageCode,
	getPaper,
	reviseImageChat,
} from "@/apis/filesApi";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { useFilePreview } from "@/composables/useFilePreview";
import { useTaskStore } from "@/stores/task";
import { AgentType } from "@/utils/enum";
import { IMAGE_EXTENSION_RE_FRAGMENT } from "@/utils/imageConstants";
import { resolveTaskImageUrl } from "@/utils/markdown";
import type { InterpreterMessage } from "@/utils/response";
import {
	CheckCircle2,
	ImageIcon,
	ListTree,
	PanelLeftClose,
	PanelLeftOpen,
	Pencil,
	RefreshCw,
	XCircle,
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

interface ImageItem {
	filename: string;
	title: string;
	url: string;
}

interface ChatMessage {
	role: "user" | "assistant";
	content: string;
}

interface RevisionState {
	status: "idle" | "running" | "success" | "failed";
	message: string;
	updatedAt: number;
}

interface ImageCodeState {
	found: boolean;
	code?: string | null;
	cellIndex?: number | null;
	section?: string | null;
	description?: string | null;
	altText?: string | null;
	caption?: string | null;
	loading?: boolean;
}

const props = defineProps<{ refreshKey?: number }>();
const emit = defineEmits<{ "paper-updated": [] }>();
const route = useRoute();
const taskStore = useTaskStore();
const taskId = computed(() => route.params.task_id as string);
const images = ref<ImageItem[]>([]);
const paperContent = ref("");
const activeImage = ref<ImageItem | null>(null);
const dialogOpen = ref(false);
const imageChatHistories = ref<Record<string, ChatMessage[]>>({});
const chatMessages = ref<ChatMessage[]>([]);
const chatInput = ref("");
const chatSending = ref(false);
const chatScrollHost = ref<HTMLElement | null>(null);
const loading = ref(false);
const { toast } = useToast();
const { openPreview } = useFilePreview();
const showToc = ref(true);
const activeImageId = ref<string>("");
const hoveredImageId = ref<string>("");
const imageTocScrollHost = ref<HTMLElement | null>(null);
const imageScrollHost = ref<HTMLElement | null>(null);
const revisionStates = ref<Record<string, RevisionState>>({});
const lastRevisionStatus = ref<RevisionState | null>(null);
const imageCodeStates = ref<Record<string, ImageCodeState>>({});
const imageRefreshVersion = ref(Date.now());
let revisionMemoryTimer: ReturnType<typeof setInterval> | null = null;

/** 从文件名中提取所属章节目录名（如 5.1_问题1的模型建立与求解），无目录则返回空字符串 */
function sectionPath(filename: string) {
	const idx = filename.lastIndexOf("/");
	return idx > 0 ? filename.slice(0, idx) : "";
}

/** 章节目录名 → 人类可读标签 */
function sectionLabel(dirName: string) {
	if (!dirName) return "未归类";
	const match = dirName.match(/^[\d.]+_(.+)$/);
	return match ? match[1] : dirName;
}

/** 将图片路径转为安全的 DOM ID（替换 / 为中划线） */
function imageDomId(filename: string) {
	return filename.replace(/\//g, "-");
}

/** 按章节目录分组的图片映射 */
const sectionGroups = computed(() => {
	const groups = new Map<string, ImageItem[]>();
	for (const img of images.value) {
		const dir = sectionPath(img.filename);
		if (!groups.has(dir)) groups.set(dir, []);
		groups.get(dir)!.push(img);
	}
	const sorted = Array.from(groups.entries()).sort(([a], [b]) =>
		a.localeCompare(b, "en", { numeric: true }),
	);
	return sorted;
});

const currentImageRevision = computed(() =>
	activeImage.value ? revisionStates.value[activeImage.value.filename] : null,
);

function getRevisionMemoryKey() {
	return `image-revision-memory:${taskId.value}`;
}

function persistRevisionMemory() {
	if (typeof window === "undefined" || !taskId.value) return;
	window.localStorage.setItem(
		getRevisionMemoryKey(),
		JSON.stringify({
			chats: imageChatHistories.value,
			states: revisionStates.value,
			last: lastRevisionStatus.value,
		}),
	);
}

function restoreRevisionMemory() {
	if (typeof window === "undefined" || !taskId.value) return;
	const previousActive = activeImage.value?.filename ?? "";
	try {
		const raw = window.localStorage.getItem(getRevisionMemoryKey());
		if (!raw) {
			imageChatHistories.value = {};
			revisionStates.value = {};
			lastRevisionStatus.value = null;
			return;
		}
		const parsed = JSON.parse(raw) as {
			chats?: Record<string, ChatMessage[]>;
			states?: Record<string, RevisionState>;
			last?: RevisionState | null;
		};
		imageChatHistories.value = parsed.chats ?? {};
		revisionStates.value = parsed.states ?? {};
		lastRevisionStatus.value = parsed.last ?? null;
		if (previousActive) {
			chatMessages.value = [
				...(imageChatHistories.value[previousActive] ?? []),
			];
		}
	} catch {
		imageChatHistories.value = {};
		revisionStates.value = {};
		lastRevisionStatus.value = null;
	}
}

function hasRunningRevision() {
	return Object.values(revisionStates.value).some(
		(state) => state.status === "running",
	);
}

function imageUrl(filename: string) {
	return resolveTaskImageUrl(
		`${filename}?v=${imageRefreshVersion.value}`,
		taskId.value,
	);
}

function titleFromFilename(filename: string) {
	return filename.replace(
		new RegExp(`\\.(?:${IMAGE_EXTENSION_RE_FRAGMENT})$`, "i"),
		"",
	);
}

function openImagePreview(image: ImageItem) {
	openPreview(image.url, image.filename);
}

function getPaperImageDescription(filename: string) {
	const pattern = new RegExp(
		`!\\[([^\\]]*)\\]\\([^)]*${filename.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\)`,
		"i",
	);
	const match = paperContent.value.match(pattern);
	if (!match) return "";
	const imageStart = match.index ?? 0;
	const imageEnd = imageStart + match[0].length;
	const before = paperContent.value.slice(
		Math.max(0, imageStart - 300),
		imageStart,
	);
	const after = paperContent.value.slice(imageEnd, imageEnd + 500);
	const beforeLastBlock = before.lastIndexOf("\n\n");
	const afterNextBlock = after.indexOf("\n\n");
	const contextBefore =
		beforeLastBlock > 0 ? before.slice(beforeLastBlock + 2) : before;
	const contextAfter =
		afterNextBlock > 0 ? after.slice(0, afterNextBlock) : after;
	return `${contextBefore}\n${contextAfter}`
		.replace(/!\[.*?\]\(.*?\)/g, "")
		.replace(/#{1,6}\s/g, "")
		.trim()
		.slice(0, 800);
}

function getIndexedImageDescription(filename: string) {
	const state = imageCodeStates.value[filename];
	return (
		state?.caption?.trim() ||
		state?.description?.trim() ||
		state?.altText?.trim() ||
		""
	);
}

function getImageDescription(filename: string) {
	return (
		getIndexedImageDescription(filename) || getPaperImageDescription(filename)
	);
}

function codeBlockNumberForImage(filename: string) {
	const code = imageCodeStates.value[filename]?.code?.trim();
	if (!code) return null;
	let codeNumber = 0;
	for (const message of taskStore.interpreterMessage as InterpreterMessage[]) {
		if (!message.input?.code) continue;
		codeNumber += 1;
		if (message.input.code.trim() === code) return codeNumber;
	}
	return null;
}

function imageCodeStatusLabel(filename: string) {
	const state = imageCodeStates.value[filename];
	if (state?.loading) return "匹配代码中";
	if (!state?.found) return "未关联代码";
	const codeNumber = codeBlockNumberForImage(filename);
	return codeNumber == null ? "已关联代码" : `已关联代码 #${codeNumber}`;
}

function filenameFromImageSrc(src: string) {
	const path = src.replace(/\\/g, "/").split(/[?#]/)[0];
	const staticMatch = path.match(/(?:^|\/)static\/+(.+)$/);
	const afterStatic = staticMatch?.[1] ?? path;
	const segments = afterStatic.split("/").filter(Boolean);
	return segments.length > 1 && segments[0] === taskId.value
		? segments.slice(1).join("/")
		: afterStatic;
}

function setRevisionState(filename: string, state: RevisionState) {
	revisionStates.value = {
		...revisionStates.value,
		[filename]: state,
	};
	lastRevisionStatus.value = state;
	persistRevisionMemory();
}

function setImageChatHistory(filename: string, messages: ChatMessage[]) {
	imageChatHistories.value = {
		...imageChatHistories.value,
		[filename]: [...messages],
	};
	if (activeImage.value?.filename === filename) {
		chatMessages.value = [...messages];
	}
	persistRevisionMemory();
}

function getErrorMessage(error: unknown) {
	if (typeof error === "object" && error && "response" in error) {
		const response = (error as { response?: { data?: { detail?: string } } })
			.response;
		if (response?.data?.detail) return response.data.detail;
	}
	return error instanceof Error ? error.message : "网络错误，请重试";
}

async function refreshImageCodeStates(items: ImageItem[]) {
	const nextState: Record<string, ImageCodeState> = {};
	for (const image of items) {
		nextState[image.filename] = imageCodeStates.value[image.filename] ?? {
			found: false,
			loading: true,
		};
	}
	imageCodeStates.value = nextState;

	await Promise.all(
		items.map(async (image) => {
			try {
				const res = await getImageCode(taskId.value, image.filename);
				imageCodeStates.value = {
					...imageCodeStates.value,
					[image.filename]: {
						found: res.data.found,
						code: res.data.code,
						cellIndex: res.data.cell_index,
						section: res.data.section,
						description: res.data.description,
						altText: res.data.alt_text,
						caption: res.data.caption,
						loading: false,
					},
				};
			} catch (error) {
				imageCodeStates.value = {
					...imageCodeStates.value,
					[image.filename]: {
						found: false,
						loading: false,
					},
				};
			}
		}),
	);
}

async function loadImages() {
	loading.value = true;
	try {
		const [filesRes, paperRes] = await Promise.all([
			getFiles(taskId.value),
			getPaper(taskId.value),
		]);
		paperContent.value = paperRes.data.content || "";
		const fileImages = (Array.isArray(filesRes.data) ? filesRes.data : [])
			.map((file) => file.filename)
			.filter(
				(filename): filename is string =>
					Boolean(filename) &&
					new RegExp(`\\.(?:${IMAGE_EXTENSION_RE_FRAGMENT})$`, "i").test(
						filename,
					),
			);
		const markdownImages = Array.from(
			paperContent.value.matchAll(
				new RegExp(
					`!\\[(.*?)\\]\\((.*?\\.(?:${IMAGE_EXTENSION_RE_FRAGMENT}))\\)`,
					"gi",
				),
			),
		)
			.map((match) => {
				const src = match[2] ?? "";
				const filename = filenameFromImageSrc(src);
				return { title: match[1] || titleFromFilename(filename), filename };
			})
			.filter((item) => Boolean(item.filename));
		const orderedImages: ImageItem[] = [];
		const seenFilenames = new Set<string>();
		for (const item of markdownImages) {
			if (seenFilenames.has(item.filename)) continue;
			seenFilenames.add(item.filename);
			orderedImages.push({
				filename: item.filename,
				title: item.title,
				url: imageUrl(item.filename),
			});
		}
		for (const filename of [...fileImages].sort((a, b) =>
			a.localeCompare(b, "en", { numeric: true }),
		)) {
			if (seenFilenames.has(filename)) continue;
			seenFilenames.add(filename);
			orderedImages.push({
				filename,
				title: titleFromFilename(filename),
				url: imageUrl(filename),
			});
		}
		images.value = orderedImages;
		void refreshImageCodeStates(images.value);
		if (!activeImageId.value || !seenFilenames.has(activeImageId.value)) {
			activeImageId.value = images.value[0]?.filename ?? "";
		}
	} catch (error) {
		console.error("读取图片失败:", error);
	} finally {
		loading.value = false;
	}
}

function scrollToImage(id: string) {
	activeImageId.value = id;
	keepActiveImageTocVisible();
	nextTick(() =>
		document
			.getElementById(imageDomId(id))
			?.scrollIntoView({ behavior: "smooth", block: "start" }),
	);
}

function keepActiveImageTocVisible() {
	if (!activeImageId.value) return;
	nextTick(() => {
		const toc = imageTocScrollHost.value;
		const activeButton = toc?.querySelector<HTMLElement>(
			`[data-image-id="${CSS.escape(imageDomId(activeImageId.value))}"]`,
		);
		activeButton?.scrollIntoView({ behavior: "smooth", block: "nearest" });
	});
}

function updateActiveImage() {
	const container = imageScrollHost.value;
	if (!container) return;
	const cards = Array.from(
		container.querySelectorAll<HTMLElement>("section[id]"),
	);
	if (!cards.length) {
		activeImageId.value = images.value[0]?.filename ?? "";
		return;
	}
	const top = container.scrollTop + container.clientHeight * 0.35;
	let current = cards[0]?.id ?? "";
	for (const card of cards) {
		if (card.offsetTop <= top) current = card.id;
	}
	activeImageId.value = current.replace(/-/g, "/");
}

function bindImageScroll() {
	requestAnimationFrame(() => {
		const el = imageScrollHost.value;
		if (!el) return;
		el.removeEventListener("scroll", updateActiveImage);
		el.addEventListener("scroll", updateActiveImage, { passive: true });
		updateActiveImage();
	});
}

function openRevision(image: ImageItem) {
	activeImage.value = image;
	chatMessages.value = [...(imageChatHistories.value[image.filename] ?? [])];
	chatInput.value = "";
	dialogOpen.value = true;
	scrollChatToBottom();
}

function scrollChatToBottom() {
	nextTick(() => {
		const el = chatScrollHost.value;
		if (el) el.scrollTop = el.scrollHeight;
	});
}

async function sendChatMessage() {
	if (!activeImage.value || !chatInput.value.trim() || chatSending.value)
		return;

	const image = activeImage.value;
	const instruction = chatInput.value.trim();
	const description = getImageDescription(image.filename);
	const existingMessages =
		imageChatHistories.value[image.filename] ?? chatMessages.value;
	const history = existingMessages.map((m) => ({
		role: m.role,
		content: m.content,
	}));

	chatInput.value = "";
	chatSending.value = true;
	const withUserMessage: ChatMessage[] = [
		...existingMessages,
		{ role: "user", content: instruction },
	];
	setImageChatHistory(image.filename, withUserMessage);
	setRevisionState(image.filename, {
		status: "running",
		message: "AI 正在修改代码并重新生成图片...",
		updatedAt: Date.now(),
	});
	taskStore.addUserAction(
		"修改",
		`图片 ${image.filename}`,
		`用户请求修改图片 ${image.filename}：${instruction}`,
		{
			from: "User",
			to: "CoderAgent",
			label: "请求图片重画",
		},
	);
	scrollChatToBottom();

	try {
		const res = await reviseImageChat(
			taskId.value,
			image.filename,
			instruction,
			image.title,
			description,
			history.length > 0 ? history : undefined,
		);
		const result = res.data;
		const assistantText = [
			result.analysis_text,
			result.revised_code
				? "已生成修改后的绘图代码，并尝试重新运行生成图片。"
				: "",
			result.updated_alt_text ? `新 alt-text：${result.updated_alt_text}` : "",
			result.updated_caption ? `新图片说明：${result.updated_caption}` : "",
		]
			.filter(Boolean)
			.join("\n\n");

		const withAssistantMessage: ChatMessage[] = [
			...(imageChatHistories.value[image.filename] ?? withUserMessage),
			{
				role: "assistant",
				content: assistantText || result.message || "修改完成",
			},
		];
		setImageChatHistory(image.filename, withAssistantMessage);
		if (result.updated_alt_text || result.updated_caption) {
			const previous: ImageCodeState = imageCodeStates.value[
				image.filename
			] ?? {
				found: true,
			};
			imageCodeStates.value = {
				...imageCodeStates.value,
				[image.filename]: {
					...previous,
					altText: result.updated_alt_text ?? previous.altText,
					caption: result.updated_caption ?? previous.caption,
					description:
						result.updated_caption ??
						result.updated_alt_text ??
						previous.description,
				},
			};
		}
		setRevisionState(image.filename, {
			status: result.status === "failed" ? "failed" : "success",
			message:
				result.message ||
				(result.paper_updated
					? "图片已重新生成，说明已同步到论文"
					: "图片已重新生成"),
			updatedAt: Date.now(),
		});
		const { dismiss } = toast({
			title: result.status === "failed" ? "修改失败" : "修改成功",
			description:
				result.message ||
				(result.paper_updated ? "图片已重新生成并同步论文" : "图片已重新生成"),
			variant: result.status === "failed" ? "destructive" : undefined,
		});
		setTimeout(dismiss, 5000);
		if (result.status !== "failed") {
			imageRefreshVersion.value = Date.now();
			if (result.image_url) {
				activeImage.value = {
					...image,
					url: imageUrl(image.filename),
				};
			}
		}
		if (result.paper_updated || result.status !== "failed") {
			taskStore.addAgentAction(
				AgentType.CODER,
				"重画",
				`图片 ${image.filename}`,
				result.message ||
					(result.paper_updated
						? "图片已重新生成，并同步更新论文说明。"
						: "图片已重新生成。"),
				{
					from: "CoderAgent",
					to: result.paper_updated ? "WriterAgent" : "User",
					label: result.paper_updated ? "同步论文图文" : "返回图片结果",
				},
			);
			emit("paper-updated");
			await loadImages();
		}
	} catch (error) {
		const message = getErrorMessage(error);
		console.error("AI 修改图片失败:", error);
		setImageChatHistory(image.filename, [
			...(imageChatHistories.value[image.filename] ?? withUserMessage),
			{
				role: "assistant",
				content: `修改失败：${message}`,
			},
		]);
		setRevisionState(image.filename, {
			status: "failed",
			message,
			updatedAt: Date.now(),
		});
		const { dismiss: dismissErr } = toast({
			title: "修改失败",
			description: message,
			variant: "destructive",
		});
		setTimeout(dismissErr, 5000);
	} finally {
		chatSending.value = false;
		scrollChatToBottom();
	}
}

onMounted(() => {
	restoreRevisionMemory();
	void loadImages();
	bindImageScroll();
	revisionMemoryTimer = setInterval(() => {
		if (hasRunningRevision()) restoreRevisionMemory();
	}, 1000);
});

onBeforeUnmount(() => {
	imageScrollHost.value?.removeEventListener("scroll", updateActiveImage);
	dialogOpen.value = false;
	if (revisionMemoryTimer) {
		clearInterval(revisionMemoryTimer);
		revisionMemoryTimer = null;
	}
	persistRevisionMemory();
});

watch(
	() => props.refreshKey,
	() => {
		void loadImages();
	},
);

watch(
	images,
	() => {
		bindImageScroll();
	},
	{ deep: true },
);

watch(
	() => taskId.value,
	() => {
		restoreRevisionMemory();
		if (activeImage.value) {
			chatMessages.value = [
				...(imageChatHistories.value[activeImage.value.filename] ?? []),
			];
		}
	},
);
</script>

<template>
  <div class="relative flex h-full min-h-0 bg-white/70 backdrop-blur-sm">
    <aside v-if="showToc" class="w-60 shrink-0 bg-slate-50/90 backdrop-blur-xl">
      <div class="flex items-center justify-between bg-gradient-to-b from-white/70 to-white/35 px-3 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.85)] backdrop-blur-md">
        <div class="flex items-center gap-2 text-sm font-semibold text-slate-800">
          <ListTree class="h-4 w-4" />
          <span class="bg-gradient-to-b from-slate-900 to-slate-500 bg-clip-text text-transparent">图片目录</span>
        </div>
        <Button variant="ghost" size="icon" @click="showToc = false"><PanelLeftClose class="h-4 w-4" /></Button>
      </div>
      <div ref="imageTocScrollHost" class="image-toc-scroll h-[calc(100%-45px)] overflow-y-auto overflow-x-hidden">
        <div class="p-2">
          <template v-for="[dir, groupImages] in sectionGroups" :key="`toc-sec-${dir}`">
            <div v-if="dir" class="mt-2 mb-1 px-2 text-[11px] font-semibold text-slate-400 uppercase tracking-wide">{{ sectionLabel(dir) }}</div>
            <button
              v-for="image in groupImages"
              :key="`toc-${image.filename}`"
              type="button"
              :data-image-id="imageDomId(image.filename)"
              class="image-toc-item block w-full rounded px-2 py-1.5 text-left text-xs leading-5 transition-colors"
              :class="activeImageId === image.filename ? 'image-toc-item-active bg-blue-100 text-blue-700 ring-1 ring-blue-200' : hoveredImageId === image.filename ? 'bg-blue-50/80 text-blue-600 ring-1 ring-blue-300/50' : 'text-slate-600 hover:bg-white hover:text-blue-600'"
              @click="scrollToImage(image.filename)"
            >{{ image.title }}</button>
          </template>
        </div>
      </div>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col bg-white/80 backdrop-blur-sm">
      <div class="flex items-center justify-between bg-gradient-to-b from-white/72 to-white/42 px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.85)] backdrop-blur-md">
        <div class="flex items-center gap-2">
          <Button v-if="!showToc" variant="ghost" size="icon" @click="showToc = true"><PanelLeftOpen class="h-4 w-4" /></Button>
          <ImageIcon class="h-4 w-4 text-slate-600" />
          <h2 class="text-base font-semibold text-gray-900">图片结果</h2>
          <span class="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">{{ images.length }} 张</span>
        </div>
        <Button variant="ghost" size="sm" :disabled="loading" @click="loadImages"><RefreshCw class="mr-1 h-4 w-4" :class="{ 'animate-spin': loading }" />刷新</Button>
      </div>

      <div ref="imageScrollHost" class="image-content-scroll min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        <div v-if="images.length" class="flex flex-col gap-3 p-4">
          <template v-for="[dir, groupImages] in sectionGroups" :key="`sec-${dir}`">
            <div v-if="dir" class="section-header mb-1 mt-2 text-sm font-bold text-slate-500">{{ dir }}</div>
            <section v-for="image in groupImages" :id="imageDomId(image.filename)" :key="image.filename" class="image-card flex gap-4 overflow-hidden rounded-md border bg-white shadow-sm p-4 transition-all duration-300" :class="{ 'image-card-hover': hoveredImageId === image.filename }" @mouseenter="hoveredImageId = image.filename" @mouseleave="hoveredImageId = ''">
            <div class="flex min-h-44 w-[55%] shrink-0 items-center justify-center rounded bg-slate-50">
              <img :src="image.url" :alt="image.title" class="max-h-[460px] max-w-full cursor-zoom-in rounded object-contain transition hover:opacity-90" @click="openImagePreview(image)" />
            </div>
            <div class="flex min-w-0 flex-1 flex-col justify-between">
              <div class="min-h-0 flex-1">
                <div class="mb-1 text-sm font-semibold text-slate-800">{{ image.title }}</div>
                <div class="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  <span>{{ image.filename }}</span>
                  <span
                    class="rounded border px-1.5 py-0.5"
                    :class="imageCodeStates[image.filename]?.found ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'"
                  >
                    {{ imageCodeStatusLabel(image.filename) }}
                  </span>
                </div>
                <p class="line-clamp-[14] whitespace-pre-wrap text-xs leading-5 text-slate-500">{{ getImageDescription(image.filename) || "暂无图片说明" }}</p>
              </div>
              <div class="mt-2 flex items-center justify-between border-t border-slate-100 pt-2">
                <div class="min-w-0 text-xs" :class="revisionStates[image.filename]?.status === 'failed' ? 'text-red-500' : revisionStates[image.filename]?.status === 'success' ? 'text-emerald-600' : 'text-slate-400'">
                  {{ revisionStates[image.filename]?.message || "未修改" }}
                </div>
                <Button size="sm" variant="outline" :disabled="revisionStates[image.filename]?.status === 'running' || imageCodeStates[image.filename]?.loading || !imageCodeStates[image.filename]?.found" @click="openRevision(image)">
                  <RefreshCw v-if="revisionStates[image.filename]?.status === 'running'" class="mr-1 h-4 w-4 animate-spin" />
                  <Pencil v-else class="mr-1 h-4 w-4" />
                  {{ revisionStates[image.filename]?.status === "running" ? "正在修改..." : "修改代码重画" }}
                </Button>
              </div>
            </div>
          </section>
          </template>
        </div>
        <div v-else class="glass-card m-4 flex h-56 items-center justify-center text-sm text-slate-500">暂无图片结果</div>
      </div>
    </div>

    <div v-if="lastRevisionStatus" class="revision-status-panel fixed bottom-4 right-4 z-40 flex max-w-sm items-start gap-2 rounded-md border px-3 py-2 text-xs shadow-lg backdrop-blur-xl" :class="lastRevisionStatus.status === 'failed' ? 'border-red-200 bg-red-50/85 text-red-700' : lastRevisionStatus.status === 'running' ? 'border-blue-200 bg-blue-50/85 text-blue-700' : 'border-emerald-200 bg-emerald-50/85 text-emerald-700'">
      <RefreshCw v-if="lastRevisionStatus.status === 'running'" class="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
      <XCircle v-else-if="lastRevisionStatus.status === 'failed'" class="mt-0.5 h-4 w-4 shrink-0" />
      <CheckCircle2 v-else class="mt-0.5 h-4 w-4 shrink-0" />
      <span>{{ lastRevisionStatus.message }}</span>
    </div>

    <Dialog v-model:open="dialogOpen">
      <DialogContent class="sm:max-w-[640px]">
        <DialogHeader>
          <DialogTitle>修改图片 - AI 对话</DialogTitle>
        </DialogHeader>
        <div class="flex max-h-[70vh] flex-col gap-4">
          <div v-if="activeImage" class="shrink-0 rounded border bg-slate-50 p-2">
            <img :src="activeImage.url" :alt="activeImage.title" class="max-h-48 w-full cursor-zoom-in object-contain transition hover:opacity-90" @click="openImagePreview(activeImage)" />
            <p class="mt-1 truncate text-xs text-slate-500">{{ activeImage.filename }}</p>
            <p class="mt-1 text-xs" :class="imageCodeStates[activeImage.filename]?.found ? 'text-emerald-600' : 'text-amber-600'">
              {{ imageCodeStates[activeImage.filename]?.found ? "已找到生成该图片的代码，修改会执行：AI 改代码 → 重跑 → 覆盖生成新图片。" : "没有找到这张图片的代码映射，无法自动重画；请先重新运行生成该图的代码。" }}
            </p>
            <p v-if="getImageDescription(activeImage.filename)" class="mt-2 line-clamp-3 text-xs leading-5 text-slate-500">{{ getImageDescription(activeImage.filename) }}</p>
          </div>

          <div ref="chatScrollHost" class="min-h-[220px] flex-1 space-y-3 overflow-y-auto rounded-lg border bg-slate-50 p-3">
            <div v-if="chatMessages.length === 0" class="flex h-full min-h-[170px] items-center justify-center text-sm text-slate-400">
              输入修改指令，AI 会修改绘图代码并重新运行生成新图片
            </div>
            <div v-for="(msg, idx) in chatMessages" :key="idx" :class="['flex', msg.role === 'user' ? 'justify-end' : 'justify-start']">
              <div :class="['max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap', msg.role === 'user' ? 'bg-blue-500 text-white' : 'border bg-white text-slate-700 shadow-sm']">
                {{ msg.content }}
              </div>
            </div>
            <div v-if="chatSending" class="flex justify-start">
              <div class="rounded-lg border bg-white px-3 py-2 text-sm text-slate-400 shadow-sm">
                <RefreshCw class="mr-1 inline-block h-3 w-3 animate-spin" />AI 正在修改...
              </div>
            </div>
          </div>

          <div v-if="currentImageRevision" class="rounded border px-3 py-2 text-xs" :class="currentImageRevision.status === 'failed' ? 'border-red-200 bg-red-50 text-red-700' : currentImageRevision.status === 'running' ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'">
            {{ currentImageRevision.message }}
          </div>

          <div class="flex gap-2">
            <Textarea v-model="chatInput" rows="2" placeholder="描述你想如何修改这张图，例如配色、标题、坐标轴、标注、图例..." :disabled="chatSending" class="flex-1" @keydown.enter.exact.prevent="sendChatMessage" />
            <Button :disabled="chatSending || !chatInput.trim()" class="shrink-0 self-end" @click="sendChatMessage">
              <RefreshCw v-if="chatSending" class="mr-1 h-4 w-4 animate-spin" />
              {{ chatSending ? "正在修改..." : "发送" }}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>

<style scoped>
.image-toc-item {
  position: relative;
}

.image-toc-item-active::before {
  position: absolute;
  top: 0.35rem;
  bottom: 0.35rem;
  left: 0.25rem;
  width: 3px;
  border-radius: 999px;
  background: #2563eb;
  content: "";
}

.image-toc-scroll,
.image-content-scroll {
  background: rgba(255, 255, 255, 0.68);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  mask-image: linear-gradient(
    to bottom,
    transparent 0,
    #000 1.25rem,
    #000 calc(100% - 1.25rem),
    transparent 100%
  );
  -webkit-mask-image: linear-gradient(
    to bottom,
    transparent 0,
    #000 1.25rem,
    #000 calc(100% - 1.25rem),
    transparent 100%
  );
}

.image-toc-scroll::-webkit-scrollbar,
.image-content-scroll::-webkit-scrollbar {
  width: 4px;
}

.image-toc-scroll::-webkit-scrollbar-track,
.image-content-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.image-toc-scroll::-webkit-scrollbar-thumb,
.image-content-scroll::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.75);
}

.image-card {
  border-color: rgba(255, 255, 255, 0.25);
  background: rgba(255, 255, 255, 0.4);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-radius: 1rem;
  box-shadow:
    0 4px 24px rgba(0, 0, 0, 0.04),
    0 0 0 1px rgba(255, 255, 255, 0.5) inset;
  transition: box-shadow 0.3s ease, border-color 0.3s ease;
}
.image-card:hover {
  border-color: rgba(59, 130, 246, 0.45);
}

.glass-card {
  border: 1px solid rgba(255, 255, 255, 0.25);
  background: rgba(255, 255, 255, 0.4);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-radius: 1rem;
  box-shadow:
    0 4px 24px rgba(0, 0, 0, 0.04),
    0 0 0 1px rgba(255, 255, 255, 0.5) inset;
}

.revision-status-panel {
  box-shadow:
    0 12px 28px rgba(15, 23, 42, 0.14),
    inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

/* ====== 图片卡片玻璃泛光 ====== */
.image-card-hover {
  border-color: rgba(59, 130, 246, 0.3) !important;
  background: linear-gradient(135deg, rgba(255,255,255,0.95), rgba(241,245,249,0.9)) !important;
  box-shadow:
    0 0 16px 2px rgba(59, 130, 246, 0.15),
    0 0 32px 6px rgba(59, 130, 246, 0.06),
    0 0 0 1px rgba(255, 255, 255, 0.5) inset,
    0 8px 24px rgba(15, 23, 42, 0.08) !important;
}

.image-card-hover::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: radial-gradient(ellipse 70% 50% at 50% 30%, rgba(147,197,253,0.12), transparent 60%);
  pointer-events: none;
}
</style>
