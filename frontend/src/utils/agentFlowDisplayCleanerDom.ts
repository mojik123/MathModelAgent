const STYLE_ID = "agent-flow-display-cleaner-style";
const HIDDEN_CLASS = "agent-flow-low-value-hidden";

const KEEP_LABEL_PARTS = [
	"移交建模任务",
	"提交求解方案",
	"下达",
	"求解",
	"提交组",
	"整合全部求解结果",
	"分发写作任务",
	"启动终稿整合",
	"交付终稿",
	"返回图片修订结果",
	"返回文本修订结果",
];

const DROP_LABEL_PARTS = [
	"启动任务",
	"任务处理完毕",
	"终止任务",
	"分配任务",
	"工作指令",
	"请求确认问题",
	"确认问题划分",
	"请求确认模型",
	"返回确认方案",
	"候选模型就绪",
	"联网检索方法",
	"提交草稿",
	"请求修改图片",
	"请求修改文本",
];

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
.${HIDDEN_CLASS}{display:none!important;}
.workflow-chip.${HIDDEN_CLASS},.coordination-chip.${HIDDEN_CLASS}{display:none!important;}
.action-line.${HIDDEN_CLASS}{display:none!important;}
`;
	document.head.appendChild(style);
}

function includesAny(text: string, parts: string[]) {
	return parts.some((part) => text.includes(part));
}

function shouldHideFlow(fromText: string, toText: string, labelText: string) {
	const merged = `${fromText} ${toText} ${labelText}`;
	if (includesAny(labelText, KEEP_LABEL_PARTS)) return false;
	if (fromText.includes("System") || toText.includes("System")) return true;
	if (fromText.includes("User") || toText.includes("User")) {
		return !labelText.includes("交付终稿") && !labelText.includes("返回图片修订结果") && !labelText.includes("返回文本修订结果");
	}
	if (includesAny(merged, DROP_LABEL_PARTS)) return true;
	return false;
}

function refreshWorkflowChips() {
	document.querySelectorAll<HTMLElement>(".workflow-chip").forEach((chip) => {
		const parties = Array.from(chip.querySelectorAll<HTMLElement>(".workflow-party")).map((el) => el.textContent?.trim() || "");
		const label = chip.querySelector<HTMLElement>(".workflow-label")?.textContent?.trim() || "";
		chip.classList.toggle(HIDDEN_CLASS, shouldHideFlow(parties[0] || "", parties[1] || "", label));
	});

	document.querySelectorAll<HTMLElement>(".coordination-chip").forEach((chip) => {
		const text = chip.textContent || "";
		chip.classList.toggle(HIDDEN_CLASS, text.includes("System") || text.includes("工作指令"));
	});
}

function refreshRecentComms() {
	document.querySelectorAll<HTMLElement>(".comms-list").forEach((list) => {
		const children = Array.from(list.children) as HTMLElement[];
		for (let i = 0; i < children.length; i += 4) {
			const row = children.slice(i, i + 4);
			if (row.length < 4) continue;
			const fromText = row[0].textContent?.trim() || "";
			const toText = row[2].textContent?.trim() || "";
			const labelText = row[3].textContent?.trim() || "";
			const hide = shouldHideFlow(fromText, toText, labelText);
			row.forEach((el) => el.classList.toggle(HIDDEN_CLASS, hide));
		}
	});
}

function refreshLowValueActionRows() {
	document.querySelectorAll<HTMLElement>(".action-line").forEach((row) => {
		const text = row.textContent || "";
		const lowValue =
			text.includes("传递：工作指令") ||
			text.includes("启动：任务流程") ||
			text.includes("更新：任务流程") ||
			text.includes("等待：确认问题划分") ||
			text.includes("确认：问题划分") ||
			text.includes("等待：用户确认方案") ||
			text.includes("启动：正式建模") ||
			text.includes("返回：") && text.includes("草稿") && text.includes("System");
		row.classList.toggle(HIDDEN_CLASS, lowValue);
	});
}

let pending = false;
function refresh() {
	if (pending) return;
	pending = true;
	requestAnimationFrame(() => {
		pending = false;
		refreshWorkflowChips();
		refreshRecentComms();
		refreshLowValueActionRows();
	});
}

export function installAgentFlowDisplayCleanerDomPatch() {
	if (typeof document === "undefined") return;
	addStyle();
	refresh();
	new MutationObserver(refresh).observe(document.body, { childList: true, subtree: true, characterData: true });
	window.setInterval(refresh, 1200);
}
