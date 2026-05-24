const STYLE_ID = "image-gallery-title-fix-style";
let installed = false;

const IMG_RE = /([\w\-.\u4e00-\u9fa5/\\]+\.(?:png|jpg|jpeg|webp|svg))/i;

const TITLE_MAP: Record<string, string> = {
	crop_area_comparison: "种植面积对比",
	profit_comparison: "利润对比",
	revenue_breakdown_s2: "收益结构分解",
	legume_rotation_heatmap: "豆类轮作安排热力图",
	overproduction_ratio: "产量销量比率",
	area_timeline: "种植面积年度变化",
	bean_rotation: "豆类轮作安排",
	profit_distribution: "利润分布",
	profit_timeline: "利润年度变化",
	sensitivity_analysis: "灵敏度分析",
	sensitivity_heatmap: "灵敏度热力图",
	elasticity_heatmap: "替代互补弹性矩阵",
	supply_demand_structure: "供需结构关系",
	endogenous_vs_exogenous_price: "内生外生价格对比",
	planting_radar: "种植结构雷达图",
	demand_equilibrium: "需求均衡结果",
	profit_risk_frontier: "利润风险前沿",
	robustness_radar: "鲁棒性雷达图",
	crop_type_trend: "作物类型种植面积分布",
};

const SECTION_MAP: Record<string, string> = {
	"4.2": "描述性统计",
	"5.1": "问题1的模型建立与求解",
	"5.2": "问题2的模型建立与求解",
	"5.3": "问题3的模型建立与求解",
	"6.1": "灵敏度分析",
};

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[data-image-title-fixed="true"] {
	font-weight: 700 !important;
	color: #1e293b !important;
}
[data-image-toc-fixed="true"] {
	font-weight: 600 !important;
}
`;
	document.head.appendChild(style);
}

function normalizePath(path: string) {
	return (path || "").replace(/\\/g, "/").trim();
}

function imageDomId(filename: string) {
	return normalizePath(filename).replace(/\//g, "-");
}

function sectionPath(filename: string) {
	const normalized = normalizePath(filename);
	const idx = normalized.lastIndexOf("/");
	return idx > 0 ? normalized.slice(0, idx) : "";
}

function baseKey(filename: string) {
	const normalized = normalizePath(filename);
	const base = normalized.split("/").filter(Boolean).pop() || normalized;
	return base.replace(/\.(png|jpg|jpeg|webp|svg)$/i, "");
}

function sectionPrefix(filename: string) {
	const dir = sectionPath(filename);
	const match = dir.match(/^(\d+(?:\.\d+)*)_/);
	return match?.[1] || "";
}

function looksLikeDescription(text: string) {
	const value = (text || "").trim();
	if (!value) return false;
	return (
		value.length > 26 ||
		/[；，。,.]/.test(value) ||
		value.includes("该图") ||
		value.includes("展示") ||
		value.includes("用于支撑") ||
		value.includes("用于说明") ||
		value.includes("数据分析") ||
		value.includes("趋势判断") ||
		value.includes("模型结果解释") ||
		value.includes("作物间") ||
		value.includes("销量") && value.includes("价格")
	);
}

function titleFromFilename(filename: string) {
	const key = baseKey(filename);
	const cleanedKey = key.replace(/^(b\d+_|r\d+_|main_)/i, "");
	const mapped = TITLE_MAP[cleanedKey] || TITLE_MAP[key];
	const prefix = sectionPrefix(filename);
	if (mapped) return prefix ? `${prefix} ${mapped}` : mapped;

	const readable = cleanedKey
		.replace(/^\d+(?:\.\d+)?_/, "")
		.replace(/_/g, " ")
		.replace(/\s+/g, " ")
		.trim();
	return prefix ? `${prefix} ${readable}` : readable;
}

function extractFilenameFromCard(section: HTMLElement) {
	const img = section.querySelector<HTMLImageElement>("img[src]");
	const src = img?.getAttribute("src") || img?.src || "";
	const staticMatch = src.match(/\/static\/[^/]+\/(.+?\.(?:png|jpg|jpeg|webp|svg))(?:[?#].*)?$/i);
	if (staticMatch?.[1]) return normalizePath(decodeURIComponent(staticMatch[1]));

	const filenameChip = Array.from(section.querySelectorAll<HTMLElement>("span, p, div"))
		.map((el) => (el.textContent || "").trim())
		.find((text) => IMG_RE.test(text));
	if (filenameChip) return normalizePath(filenameChip.match(IMG_RE)?.[1] || "");

	const id = section.id || "";
	if (id) {
		// ImageGallery 的 id 是 filename 中 / 替换为 - 后的结果，保底只用于生成可读标题。
		const maybe = id.replace(/-(?=[^/-]+\.(?:png|jpg|jpeg|webp|svg)$)/i, "/");
		return normalizePath(maybe);
	}
	return "";
}

function findCardTitleEl(section: HTMLElement) {
	const candidates = Array.from(section.querySelectorAll<HTMLElement>("div"))
		.filter((el) => {
			const cls = el.getAttribute("class") || "";
			const text = (el.textContent || "").trim();
			return cls.includes("font-semibold") && Boolean(text) && !text.includes("图片结果");
		});
	return candidates.find((el) => looksLikeDescription(el.textContent || "")) || candidates[0] || null;
}

function fixSectionHeaders(root: HTMLElement) {
	const headers = Array.from(root.querySelectorAll<HTMLElement>(".section-header"));
	for (const header of headers) {
		const raw = (header.textContent || "").trim();
		const prefix = raw.match(/^(\d+(?:\.\d+)*)_?/)?.[1];
		if (!prefix) continue;
		const label = SECTION_MAP[prefix] || raw.replace(/^[\d.]+_?/, "");
		header.textContent = `${prefix} ${label}`;
	}
}

function fixTocButtons(root: HTMLElement) {
	const buttons = Array.from(root.querySelectorAll<HTMLElement>("[data-image-id]"));
	for (const button of buttons) {
		const current = (button.textContent || "").trim();
		const dataId = button.getAttribute("data-image-id") || "";
		if (!dataId) continue;
		const target = root.querySelector<HTMLElement>(`section[id="${CSS.escape(dataId)}"]`);
		const filename = target ? extractFilenameFromCard(target) : dataId;
		const title = titleFromFilename(filename);
		if ((looksLikeDescription(current) || current !== title) && title) {
			button.textContent = title;
			button.dataset.imageTocFixed = "true";
		}
	}
}

function fixImageCards(root: HTMLElement) {
	const sections = Array.from(root.querySelectorAll<HTMLElement>("section[id]"));
	for (const section of sections) {
		const filename = extractFilenameFromCard(section);
		if (!filename) continue;
		const title = titleFromFilename(filename);
		const titleEl = findCardTitleEl(section);
		if (titleEl && title && (looksLikeDescription(titleEl.textContent || "") || titleEl.textContent !== title)) {
			titleEl.textContent = title;
			titleEl.dataset.imageTitleFixed = "true";
		}
	}
	fixTocButtons(root);
}

function fixImageGalleryTitles() {
	const root = document.querySelector<HTMLElement>(".image-content-scroll")?.closest<HTMLElement>(".relative.flex.h-full");
	if (!root) return;
	fixSectionHeaders(root);
	fixImageCards(root);
}

export function installImageGalleryTitleDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	addStyle();
	setInterval(fixImageGalleryTitles, 500);
}
