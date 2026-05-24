const STYLE_ID = "compact-timeline-progress-style";
let installed = false;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[data-compact-live-progress-hidden="true"] {
	display: none !important;
}
`;
	document.head.appendChild(style);
}

function isLiveModelingProgress(text: string) {
	return (
		/正在检索文献/.test(text) ||
		/正在生成模型方案/.test(text) ||
		/正在生成建模方案/.test(text) ||
		/生成模型方案/.test(text)
	);
}

function isImportantCard(text: string) {
	return (
		/候选建模方案已生成/.test(text) ||
		/等待用户确认/.test(text) ||
		/建模方案已确认/.test(text) ||
		/问题划分已确认/.test(text) ||
		/代码手开始求解/.test(text) ||
		/求解完成/.test(text) ||
		/写作完成/.test(text) ||
		/任务执行失败/.test(text) ||
		/错误/.test(text)
	);
}

function closestTimelineRow(node: HTMLElement) {
	let current: HTMLElement | null = node;
	while (current && current.parentElement) {
		const parent = current.parentElement;
		const cls = current.getAttribute("class") || "";
		const parentCls = parent.getAttribute("class") || "";
		if (
			cls.includes("justify-start") &&
			parentCls.includes("overflow-y-auto")
		) {
			return current;
		}
		current = parent;
	}
	return node;
}

function compactLiveProgressCards() {
	const panel = document.querySelector<HTMLElement>(".glass-left-panel");
	if (!panel) return;

	const candidates = Array.from(panel.querySelectorAll<HTMLElement>("div"))
		.map((node) => closestTimelineRow(node))
		.filter((node, index, arr) => arr.indexOf(node) === index)
		.filter((node) => {
			const text = node.textContent || "";
			return isLiveModelingProgress(text) && !isImportantCard(text);
		});

	if (candidates.length <= 1) {
		for (const node of candidates) node.removeAttribute("data-compact-live-progress-hidden");
		return;
	}

	const latest = candidates[candidates.length - 1];
	for (const node of candidates) {
		node.setAttribute(
			"data-compact-live-progress-hidden",
			node === latest ? "false" : "true",
		);
	}
	latest.removeAttribute("data-compact-live-progress-hidden");
}

export function installCompactTimelineDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined") return;
	installed = true;
	addStyle();
	setInterval(compactLiveProgressCards, 350);
}
