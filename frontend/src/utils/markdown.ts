import katex from "katex";
import { marked } from "marked";
import type { Renderer, RendererObject } from "marked";
import { IMAGE_EXTENSION_RE_FRAGMENT } from "./imageConstants";

const IMAGE_PREVIEW_MODAL_ID = "markdown-image-preview-modal";
let imagePreviewListenerRegistered = false;

const defaultOptions = {
	breaks: true,
	gfm: true,
	headerIds: true,
	mangle: false,
	sanitize: false,
};

const apiBaseUrl = () =>
	(import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

const renderMath = (tex: string, displayMode = false) => {
	try {
		return katex.renderToString(tex, {
			displayMode,
			throwOnError: false,
			strict: false,
		});
	} catch (err) {
		console.error("KaTeX rendering error:", err);
		return tex;
	}
};

export const resolveTaskImageUrl = (src: string, taskId?: string) => {
	const raw = (src || "").trim().replace(/^['\"]|['\"]$/g, "");
	if (!raw) return raw;
	if (/^(https?:|data:|blob:)/i.test(raw)) return raw;

	const suffixMatch = raw.match(/[?#].*$/);
	const suffix = suffixMatch?.[0] ?? "";
	const pathPart = suffix ? raw.slice(0, -suffix.length) : raw;
	const normalized = pathPart.replace(/\\/g, "/");
	const currentTaskId = taskId || window.localStorage.getItem("currentTaskId") || "";
	if (!currentTaskId) return raw;

	const staticMatch = normalized.match(/(?:^|\/)static\/+(.+)$/);
	const afterStatic = staticMatch?.[1] ?? normalized;
	const segments = afterStatic.split("/").filter(Boolean);
	const filename = segments.length > 1 && segments[0] === currentTaskId ? segments.slice(1).join("/") : afterStatic;

	return `${apiBaseUrl()}/static/${currentTaskId}/${encodeURI(filename)}${suffix}`;
};

const withImageVersion = (src: string, imageVersion?: string | number) => {
	if (imageVersion === undefined || imageVersion === null || imageVersion === "") return src;
	if (/^(data:|blob:)/i.test(src)) return src;
	const hashIndex = src.indexOf("#");
	const base = hashIndex >= 0 ? src.slice(0, hashIndex) : src;
	const hash = hashIndex >= 0 ? src.slice(hashIndex) : "";
	const separator = base.includes("?") ? "&" : "?";
	return `${base}${separator}v=${encodeURIComponent(String(imageVersion))}${hash}`;
};

const openMarkdownImagePreview = (src: string, alt: string) => {
	if (typeof window === "undefined") return;
	const previous = document.getElementById(IMAGE_PREVIEW_MODAL_ID);
	if (previous) previous.remove();

	const overlay = document.createElement("div");
	overlay.id = IMAGE_PREVIEW_MODAL_ID;
	overlay.style.cssText = ["position:fixed", "inset:0", "z-index:9999", "background:rgba(0,0,0,0.72)", "display:flex", "align-items:center", "justify-content:center", "padding:24px", "box-sizing:border-box"].join(";");
	const close = () => overlay.remove();
	overlay.addEventListener("click", (event) => {
		if (event.target === overlay) close();
	});

	const wrapper = document.createElement("div");
	wrapper.style.cssText = ["position:relative", "max-width:92vw", "max-height:92vh", "display:flex", "align-items:center", "justify-content:center"].join(";");

	const img = document.createElement("img");
	img.src = src;
	img.alt = alt;
	img.style.cssText = ["max-width:92vw", "max-height:92vh", "object-fit:contain", "border-radius:12px", "box-shadow:0 20px 60px rgba(0,0,0,0.45)", "background:#fff"].join(";");

	const button = document.createElement("button");
	button.type = "button";
	button.textContent = "×";
	button.setAttribute("aria-label", "关闭图片预览");
	button.style.cssText = ["position:absolute", "top:-12px", "right:-12px", "width:36px", "height:36px", "border:none", "border-radius:999px", "background:rgba(255,255,255,0.95)", "color:#111", "font-size:24px", "line-height:36px", "cursor:pointer", "box-shadow:0 6px 18px rgba(0,0,0,0.25)"].join(";");
	button.addEventListener("click", close);

	wrapper.appendChild(img);
	wrapper.appendChild(button);
	overlay.appendChild(wrapper);
	document.body.appendChild(overlay);
	button.focus();
};

export const normalizeMarkdownImageUrls = (
	markdown: string,
	taskId?: string,
	imageVersion?: string | number,
) => markdown.replace(new RegExp(`!\\[(.*?)\\]\\((.*?\\.(?:${IMAGE_EXTENSION_RE_FRAGMENT})(?:[?#][^)]+)?)\\)`, "gi"), (_, alt, src) => `![${alt}](${withImageVersion(resolveTaskImageUrl(src, taskId), imageVersion)})`);

const escapeHtml = (value: string) => value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\"/g, "&quot;").replace(/'/g, "&#39;");
const hasChinese = (value: string) => /[\u4e00-\u9fff]/.test(value || "");

const looksLikeFilename = (value: string) => {
	const s = (value || "").trim().replace(/^`|`$/g, "");
	if (!s) return true;
	if (new RegExp(`\\.(?:${IMAGE_EXTENSION_RE_FRAGMENT})(?:[?#].*)?$`, "i").test(s)) return true;
	if (s.includes("/") || s.includes("\\\\")) return true;
	if (!hasChinese(s) && /[A-Za-z]/.test(s) && /[_-]/.test(s)) return true;
	return false;
};

const chineseCaptionFromSrc = (src: string) => {
	const clean = decodeURIComponent((src || "").split(/[?#]/)[0]);
	const base = clean.split("/").pop()?.replace(/\.[^.]+$/, "") || "";
	const lower = base.toLowerCase();
	const words: string[] = [];
	const add = (word: string) => {
		if (!words.includes(word)) words.push(word);
	};
	if (/profit|revenue|收益|利润/.test(lower)) add("利润收益");
	if (/cost|成本/.test(lower)) add("成本");
	if (/crop|作物/.test(lower)) add("作物");
	if (/area|面积/.test(lower)) add("面积");
	if (/yield|产量/.test(lower)) add("产量");
	if (/sales|sale|销量|销售/.test(lower)) add("销量");
	if (/price|价格/.test(lower)) add("价格");
	if (/heatmap|热力/.test(lower)) add("热力图");
	if (/sensitivity|灵敏/.test(lower)) add("灵敏度分析");
	if (/comparison|compare|对比/.test(lower)) add("对比");
	if (/timeline|trend|趋势/.test(lower)) add("趋势");
	if (/distribution|分布/.test(lower)) add("分布");
	return words.length ? `${words.join("与")}图` : "结果图";
};

const visibleImageCaption = (alt: string, src: string) => {
	const raw = (alt || "").trim();
	if (!raw || looksLikeFilename(raw)) return chineseCaptionFromSrc(src);
	return raw;
};

const isTableCaptionText = (value: string) => /^\s*(?:\*\*)?表\s*\d+(?:\.\d+)?[\s　：:、].+?(?:\*\*)?\s*$/.test(value || "");
const stripStrong = (value: string) => value.replace(/^\s*\*\*/, "").replace(/\*\*\s*$/, "").trim();

const renderer: Partial<RendererObject> = {
	heading(this: Renderer, token: { depth: number; text: string }) {
		const tag = `h${Math.min(Math.max(token.depth, 1), 6)}`;
		return `<${tag}>${marked.parseInline(token.text)}</${tag}>`;
	},
	table(this: Renderer, token: { header: Array<string | { text: string }>; rows: Array<Array<string | { text: string }>> }) {
		const cellText = (cell: string | { text: string }) => typeof cell === "string" ? cell : (cell.text ?? "");
		const rows = token.rows.map((row) => `<tr>${row.map((cell) => `<td>${marked.parseInline(cellText(cell))}</td>`).join("")}</tr>`).join("");
		const head = token.header.map((cell) => `<th>${marked.parseInline(cellText(cell))}</th>`).join("");
		return `<div class="markdown-table-wrapper">
			<table class="markdown-table">
				<thead><tr>${head}</tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>`;
	},
	paragraph(this: Renderer, token: { text: string }) {
		let text = token.text;

		if (isTableCaptionText(text)) {
			const caption = escapeHtml(stripStrong(text));
			return `<p class="markdown-table-caption" style="margin:0.75rem 0 0.35rem;text-align:center;font-size:0.95rem;font-weight:400;">${caption}</p>`;
		}

		const imagePattern = /!\[(.*?)\]\((.*?)\)/g;
		const images: Array<[string, string, string]> = [];
		let imageIndex = 0;
		text = text.replace(imagePattern, (match, alt, src) => {
			images.push([match, alt, src]);
			return `__IMAGE_PLACEHOLDER_${imageIndex++}__`;
		});

		text = text.replace(/\$\$([\s\S]*?)\$\$/g, (_, tex) => `<div class="math-block">${renderMath(tex.trim(), true)}</div>`);
		text = text.replace(/\\\((.*?)\\\)/g, (_, tex) => renderMath(tex.trim(), false));

		text = text.replace(/__IMAGE_PLACEHOLDER_(\d+)__/g, (_, index) => {
			const [, alt, src] = images[Number.parseInt(index)];
			const rawAlt = (alt || "图片").trim() || "图片";
			const caption = visibleImageCaption(rawAlt, src);
			const safeAlt = escapeHtml(caption || rawAlt || "图片");
			const safeSrc = escapeHtml(src);
			const captionHtml = caption ? `<figcaption style="margin-top:0.5rem;text-align:center;font-size:0.95rem;font-weight:400;">${escapeHtml(caption)}</figcaption>` : "";
			return `
				<figure class="markdown-figure" style="margin:1.25rem 0;text-align:center;">
					<span class="markdown-image-wrapper" style="position:relative;display:inline-block;max-width:100%;">
						<img src="${safeSrc}" alt="${safeAlt}" class="max-w-full h-auto" style="display:block;" />
						<button type="button" class="markdown-image-zoom-btn" aria-label="放大预览图片" data-src="${safeSrc}" data-alt="${safeAlt}" style="position:absolute;left:10px;bottom:10px;opacity:0;pointer-events:none;width:32px;height:32px;border:none;border-radius:999px;background:rgba(0,0,0,0.62);color:#fff;cursor:pointer;transition:opacity 0.2s ease;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 12px rgba(0,0,0,0.22);">⌕</button>
					</span>
					${captionHtml}
				</figure>`;
		});

		return `<p>${marked.parseInline(text)}</p>`;
	},
};

marked.use({ renderer });

const registerMarkdownImageHoverBehavior = () => {
	if (imagePreviewListenerRegistered || typeof document === "undefined") return;
	imagePreviewListenerRegistered = true;
	document.addEventListener("mouseover", (event) => {
		const target = event.target as HTMLElement | null;
		const wrapper = target?.closest?.(".markdown-image-wrapper") as HTMLElement | null;
		if (!wrapper) return;
		const btn = wrapper.querySelector(".markdown-image-zoom-btn") as HTMLElement | null;
		if (btn) {
			btn.style.opacity = "1";
			btn.style.pointerEvents = "auto";
		}
	});
	document.addEventListener("mouseout", (event) => {
		const target = event.target as HTMLElement | null;
		const wrapper = target?.closest?.(".markdown-image-wrapper") as HTMLElement | null;
		if (!wrapper) return;
		const related = event.relatedTarget as HTMLElement | null;
		if (related && wrapper.contains(related)) return;
		const btn = wrapper.querySelector(".markdown-image-zoom-btn") as HTMLElement | null;
		if (btn) {
			btn.style.opacity = "0";
			btn.style.pointerEvents = "none";
		}
	});
	document.addEventListener("click", (event) => {
		const target = event.target as HTMLElement | null;
		const btn = target?.closest?.(".markdown-image-zoom-btn") as HTMLButtonElement | null;
		if (!btn) return;
		event.preventDefault();
		event.stopPropagation();
		const src = btn.dataset.src || "";
		const alt = btn.dataset.alt || "图片";
		openMarkdownImagePreview(src, alt);
	});
};

export const renderMarkdown = async (content: string, options: Record<string, unknown> & { taskId?: string; imageVersion?: string | number } = {}) => {
	const { taskId, imageVersion, ...markedOptions } = options;
	const normalized = normalizeMarkdownImageUrls(content, taskId, imageVersion)
		.replace(/\\\[\s*\n/g, "\\[")
		.replace(/\n\s*\\\]/g, "\\]")
		.replace(/([a-zA-Z0-9])_\{/g, "$1\\_{")
		.replace(/(\d)~(\d)/g, "$1\\~$2");
	registerMarkdownImageHoverBehavior();
	return marked.parse(normalized, { ...defaultOptions, ...markedOptions });
};

export const getMarkdownLines = (content: string) => content.split("\n").length;

export { marked };
