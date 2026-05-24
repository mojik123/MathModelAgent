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

function extractFilenameFromSection(section: HTMLElement) {
	const id = section.id || "";
	const text = section.textContent || "";
	const fromText = text.match(IMG_RE)?.[1];
	if (fromText) return normalizePath(fromText);
	if (id) return normalizePath(id.replace(/^(\d+(?:\.\d+)?)-/, "$1_").replace(/-/g, "/"));
	return "";
}

function fixSectionHeaders(root: HTMLElement) {
	const headers = Array.from(root.querySelectorAll<HTMLElement>(".section-header"));
	for (const header of headers) {
		const raw = (header.textContent || "").trim();
		const prefix = raw.match(/^(\d+(?:\.\d+)*)_/)?.[1];
		if (!prefix) continue;
		const label = SECTION_MAP[prefix] || raw.replace(/^[\d.]+_/, "");
		header.textContent = `${prefix} ${label}`;
	}
}

function fixImageCards(root: HTMLElement) {
	const sections = Array.from(root.querySelectorAll<HTMLElement>("section[id]"));
	for (const section of sections) {
		const filename = extractFilenameFromSection(section);
		if (!filename) continue;
		const title = titleFromFilename(filename);
		const titleEl = Array.from(section.querySelectorAll<HTMLElement>("div"))
			.find((el) => (el.getAttribute("class") || "").includes("font-semibold") && !el.textContent?.includes("图片结果"));
		if (titleEl && titleEl.textContent !== title) {
			titleEl.textContent = title;
			titleEl.dataset.imageTitleFixed = "true";
		}
		const toc = root.querySelector<HTMLElement>(`[data-image-id="${CSS.escape(imageDomId(filename))}"]`);
		if (toc && toc.textContent !== title) {
			toc.textContent = title;
			toc.dataset.imageTocFixed = "true";
		}
	}
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
	setInterval(fixImageGalleryTitles, 700);
}
