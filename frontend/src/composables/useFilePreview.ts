import { ref } from "vue";
import { getArtifactDisplayInfo } from "@/utils/artifactDisplay";

export type PreviewFormat =
	| "image"
	| "code"
	| "csv"
	| "pdf"
	| "markdown"
	| "unsupported";

const isOpen = ref(false);
const fileUrl = ref("");
const fileName = ref("");
const format = ref<PreviewFormat>("unsupported");
const sizeBytes = ref<number | undefined>();
const scale = ref(1);

// ---- 格式检测规则 ----

const imageExts = new Set([
	"png",
	"jpg",
	"jpeg",
	"gif",
	"webp",
	"svg",
	"bmp",
	"ico",
]);

const codeExts = new Set([
	"py",
	"ts",
	"js",
	"vue",
	"json",
	"tex",
	"ipynb",
	"yaml",
	"yml",
	"toml",
	"cfg",
	"ini",
	"sh",
	"r",
	"java",
	"cpp",
	"c",
	"h",
	"css",
	"scss",
	"html",
	"xml",
	"sql",
	"txt",
	"log",
	"env",
	"bib",
]);

const csvExts = new Set(["csv", "tsv", "xlsx", "xls"]);

const pdfExts = new Set(["pdf"]);

const mdExts = new Set(["md", "markdown"]);

function detectFormat(name: string): PreviewFormat {
	const cleanName = name.split(/[?#]/)[0].split(/[\\/]/).pop() ?? name;
	const ext = cleanName.split(".").pop()?.toLowerCase() ?? "";
	if (imageExts.has(ext)) return "image";
	if (codeExts.has(ext)) return "code";
	if (csvExts.has(ext)) return "csv";
	if (pdfExts.has(ext)) return "pdf";
	if (mdExts.has(ext)) return "markdown";
	return "unsupported";
}

// ---- Public API ----

function openPreview(url: string, name: string, size?: number) {
	const info = getArtifactDisplayInfo(name);

	fileUrl.value = url;
	fileName.value = info.fullName;
	format.value = detectFormat(info.fileName);
	sizeBytes.value = size;
	scale.value = 1;
	isOpen.value = true;
}

function closePreview() {
	isOpen.value = false;
	if (fileUrl.value.startsWith("blob:")) {
		URL.revokeObjectURL(fileUrl.value);
	}
	setTimeout(() => {
		fileUrl.value = "";
		fileName.value = "";
		format.value = "unsupported";
		sizeBytes.value = undefined;
		scale.value = 1;
	}, 350);
}

function zoomIn() {
	scale.value = Math.min(scale.value + 0.25, 3);
}

function zoomOut() {
	scale.value = Math.max(scale.value - 0.25, 0.25);
}

function resetZoom() {
	scale.value = 1;
}

/** 将 base64 数据转为 Blob URL（供 NotebookCell 图片预览） */
function base64ToBlobUrl(base64: string, mimeType: string): string {
	const byteChars = atob(base64);
	const chunks: Uint8Array[] = [];
	for (let offset = 0; offset < byteChars.length; offset += 512) {
		const slice = byteChars.slice(offset, offset + 512);
		const arr = new Uint8Array(slice.length);
		for (let i = 0; i < slice.length; i++) {
			arr[i] = slice.charCodeAt(i);
		}
		chunks.push(arr);
	}
	return URL.createObjectURL(new Blob(chunks, { type: mimeType }));
}

/** 构造文件 URL（和 resolveTaskImageUrl 一致的模式） */
function buildFileUrl(filename: string, taskId: string): string {
	const raw = (filename || "").trim().replace(/^['"]|['"]$/g, "");
	if (!raw) return raw;
	if (/^(https?:|data:|blob:)/i.test(raw)) return raw;

	const base = (
		import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
	).replace(/\/$/, "");

	const fallbackTaskId =
		taskId ||
		window.localStorage.getItem("currentTaskId") ||
		window.location.pathname.match(/\/task\/([^/]+)/)?.[1] ||
		"";
	if (!fallbackTaskId) return raw;

	const suffixMatch = raw.match(/[?#].*$/);
	const suffix = suffixMatch?.[0] ?? "";
	let cleanName = (suffix ? raw.slice(0, -suffix.length) : raw)
		.replace(/\\/g, "/")
		.replace(/^\.?\//, "")
		.replace(/^\/+/, "");

	const workDirMatch = cleanName.match(/(?:^|\/)work_dir\/([^/]+)\/(.+)$/);
	let effectiveTaskId = fallbackTaskId;
	if (workDirMatch) {
		effectiveTaskId = workDirMatch[1] || fallbackTaskId;
		cleanName = workDirMatch[2] || cleanName;
	} else {
		const staticMatch = cleanName.match(/(?:^|\/)static\/+(.+)$/);
		if (staticMatch) cleanName = staticMatch[1] || cleanName;
	}

	const segments = cleanName.split("/").filter(Boolean);
	if (segments.length > 1 && segments[0] === effectiveTaskId) {
		segments.shift();
	}
	const encoded = segments.map((s) => encodeURIComponent(s)).join("/");
	return `${base}/static/${effectiveTaskId}/${encoded}${suffix}`;
}

export function useFilePreview() {
	return {
		isOpen,
		fileUrl,
		fileName,
		format,
		sizeBytes,
		scale,
		openPreview,
		closePreview,
		zoomIn,
		zoomOut,
		resetZoom,
		base64ToBlobUrl,
		buildFileUrl,
	};
}
