import { useTaskStore } from "@/stores/task";
import { AgentType } from "@/utils/enum";
import type { AgentMessage, Message } from "@/utils/response";
import { watch } from "vue";

const STYLE_ID = "coder-progress-dom-style";
const PANEL_ATTR = "data-coder-progress-panel";
const HIDDEN_CURRENT_ATTR = "data-coder-default-current-hidden";
const TIMELINE_SELECTOR = "[data-agent-timeline-scroll='true']";
const CURRENT_ACTION_DOCK_SELECTOR = '[data-current-action-generated="dock"]';
const MAX_ACTIONS = 5;

let installed = false;
let scheduled = false;

interface CodeAction {
	key: string;
	scope: string;
	state:
		| "thinking"
		| "generating"
		| "executing"
		| "completed"
		| "error"
		| "finished"
		| "incomplete";
	title: string;
	count: number;
	codeIndex: number;
	code: string;
	streaming: boolean;
	order: number;
}

interface ScopeProgress {
	count: number;
	actions: CodeAction[];
}

const ACTIVE_STATES = new Set<CodeAction["state"]>([
	"thinking",
	"generating",
	"executing",
]);

const PRIORITY: Record<CodeAction["state"], number> = {
	thinking: 1,
	generating: 2,
	executing: 3,
	completed: 4,
	error: 4,
	finished: 5,
	incomplete: 5,
};

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[${HIDDEN_CURRENT_ATTR}="true"]{display:none!important}
[${PANEL_ATTR}="true"]{margin-top:.45rem;background:transparent}
[${PANEL_ATTR}="true"] .cp-head{display:flex;align-items:center;justify-content:space-between;gap:.5rem;padding:.05rem .2rem .3rem;font-size:10px;color:rgb(148 163 184)}
[${PANEL_ATTR}="true"] .cp-head>span:first-child{font-weight:600;color:rgb(100 116 139)}
[${PANEL_ATTR}="true"] .cp-count{white-space:nowrap;color:rgb(100 116 139)}
[${PANEL_ATTR}="true"] .cp-list{display:flex;flex-direction:column;padding:0}
[${PANEL_ATTR}="true"] .cp-action{width:100%;margin:0}
[${PANEL_ATTR}="true"] .cp-action>summary{display:grid;grid-template-columns:1rem minmax(0,1fr) auto .75rem;align-items:center;gap:.42rem;min-height:30px;padding:.32rem .28rem;cursor:pointer;list-style:none;border:0;border-radius:.4rem;background:transparent;font-size:11px;color:rgb(100 116 139);transition:background .16s ease,color .16s ease}
[${PANEL_ATTR}="true"] .cp-action>summary::-webkit-details-marker{display:none}
[${PANEL_ATTR}="true"] .cp-action>summary:focus{outline:none}
[${PANEL_ATTR}="true"] .cp-action>summary:focus-visible{background:rgba(226,232,240,.55);color:rgb(30 41 59)}
[${PANEL_ATTR}="true"] .cp-event-icon{display:grid;width:1rem;height:1rem;place-items:center;color:rgb(148 163 184)}
[${PANEL_ATTR}="true"] .cp-event-icon::before{content:"";width:.35rem;height:.35rem;border:1.5px solid currentColor;border-radius:999px}
[${PANEL_ATTR}="true"] .cp-title{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500}
[${PANEL_ATTR}="true"] .cp-state{white-space:nowrap;font-size:9px;color:rgb(148 163 184)}
[${PANEL_ATTR}="true"] .cp-arrow{font-size:14px;line-height:1;font-weight:750;color:rgb(71 85 105);opacity:0;transform:translateX(-4px);transition:opacity .16s ease,transform .16s ease}
[${PANEL_ATTR}="true"] .cp-action[data-expandable="true"]>summary:hover{background:rgba(226,232,240,.55);color:rgb(30 41 59)}
[${PANEL_ATTR}="true"] .cp-action[data-expandable="true"]>summary:hover .cp-state{color:rgb(71 85 105)}
[${PANEL_ATTR}="true"] .cp-action[data-expandable="true"]>summary:hover .cp-arrow,[${PANEL_ATTR}="true"] .cp-action[open] .cp-arrow{opacity:1;transform:translateX(0)}
[${PANEL_ATTR}="true"] .cp-action[open] .cp-arrow{transform:rotate(90deg)}
[${PANEL_ATTR}="true"] .cp-action[open]>summary{background:rgba(226,232,240,.48);color:rgb(30 41 59)}
[${PANEL_ATTR}="true"] .cp-action[data-expandable="false"]>summary{cursor:default}
[${PANEL_ATTR}="true"] .cp-action[data-expandable="false"] .cp-arrow{visibility:hidden}
[${PANEL_ATTR}="true"] .cp-action:not([open])>.cp-detail{display:none}
[${PANEL_ATTR}="true"] .cp-detail{margin:.12rem .2rem .38rem 1.42rem;max-height:13rem;overflow:auto;overscroll-behavior:auto!important;scrollbar-gutter:stable;white-space:pre;word-break:normal;border-radius:.45rem;background:rgb(15 23 42);padding:.62rem .7rem;font:10px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:rgb(226 232 240);scrollbar-width:thin}
[${PANEL_ATTR}="true"] .cp-action[data-expandable="false"] .cp-detail{display:none}
[${PANEL_ATTR}="true"] .cp-action[data-active="true"] .cp-event-icon{color:rgb(16 185 129)}
[${PANEL_ATTR}="true"] .cp-action[data-active="true"] .cp-event-icon::before{background:currentColor;animation:cpDotPulse 1.6s ease-in-out infinite}
[${PANEL_ATTR}="true"] .cp-action[data-active="true"] .cp-title{color:rgb(15 118 110)}
[${PANEL_ATTR}="true"] .cp-active{color:rgb(5 150 105)}
[${PANEL_ATTR}="true"] .cp-done{color:rgb(37 99 235)}
[${PANEL_ATTR}="true"] .cp-warn{color:rgb(194 65 12)}
@keyframes cpDotPulse{0%,100%{opacity:.45}50%{opacity:1}}
@media(prefers-reduced-motion:reduce){[${PANEL_ATTR}="true"] .cp-action[data-active="true"] .cp-event-icon::before{animation:none}}
`;
	document.head.appendChild(style);
}

function compactText(node: Element | null) {
	return (node?.textContent || "").replace(/\s+/g, " ").trim();
}

function messageScope(message: Message) {
	if (
		typeof message.question_index === "number" &&
		message.question_index > 0
	) {
		return `q${message.question_index}`;
	}
	const identity = `${message.group_id ?? ""}\n${message.agent_instance_id ?? ""}`;
	const identityQuestion = identity.match(/q(?:ues)?(\d+)/i);
	if (identityQuestion) return `q${identityQuestion[1]}`;
	if (/process\.eda|\beda\.coder/i.test(identity)) return "eda";
	if (/sensitivity/i.test(identity)) return "sensitivity";

	const content = (message.content ?? "").replace(/\\/g, "/");
	const subtask = content
		.match(/子任务[：:]\s*([^\n]+)/)?.[1]
		?.trim()
		.toLowerCase();
	if (subtask === "eda") return "eda";
	if (subtask === "sensitivity_analysis") return "sensitivity";
	const question = content.match(/子问题组#?(\d+)|问题\s*(\d+)/i);
	if (question) return `q${question[1] || question[2]}`;
	if (/\bEDA\b|数据探索|描述性统计|数据预处理/i.test(content)) return "eda";
	if (/灵敏度分析|敏感性分析/.test(content)) return "sensitivity";
	return "";
}

function cardScope(card: HTMLElement) {
	if (card.dataset.coderProgressScope) return card.dataset.coderProgressScope;
	const header = card.firstElementChild;
	const text = compactText(header || card);
	const question = text.match(/(?:问题|子问题组)\s*(\d+)|\bQ(\d+)\b/i);
	let scope = "";
	if (question) scope = `q${question[1] || question[2]}`;
	else if (/\bEDA\b|数据探索|描述性统计|数据预处理/i.test(text)) scope = "eda";
	else if (/灵敏度分析|敏感性分析/.test(text)) scope = "sensitivity";
	if (scope) card.dataset.coderProgressScope = scope;
	return scope;
}

function progressAction(message: Message, order: number): CodeAction | null {
	const content = message.content ?? "";
	if (
		message.feedback_kind !== "coder_progress" &&
		!content.startsWith("代码求解进度：")
	) {
		return null;
	}
	const scope = messageScope(message);
	if (!scope) return null;
	const firstLine = content.split("\n")[0] ?? "";
	const title = firstLine
		.replace(/^代码求解进度[：:]/, "")
		.replace(/｜已生成\s*\d+\s*段代码.*$/, "")
		.trim();
	const state = (content.match(/状态[：:]\s*([^\n]+)/)?.[1]?.trim() ||
		"thinking") as CodeAction["state"];
	const count = Number(
		content.match(/(?:已生成|共生成)\s*(\d+)\s*段代码/)?.[1] || 0,
	);
	const explicitCodeIndex = Number(
		content.match(/代码序号[：:]\s*(\d+)/)?.[1] || 0,
	);
	const codeIndex = explicitCodeIndex || (state === "thinking" ? count + 1 : 0);
	const key =
		codeIndex &&
		["generating", "executing", "completed", "error"].includes(state)
			? `code-${codeIndex}`
			: state === "thinking"
				? `thinking-${count}`
				: `${state}-${codeIndex || count}`;
	return {
		key,
		scope,
		state,
		title,
		count,
		codeIndex,
		code: "",
		streaming: ACTIVE_STATES.has(state),
		order,
	};
}

function codeStreamAction(
	message: AgentMessage,
	order: number,
): CodeAction | null {
	if (message.feedback_kind !== "coder_code_stream") return null;
	const scope = messageScope(message);
	if (!scope) return null;
	const [heading = "", ...codeLines] = (message.content ?? "").split("\n");
	const match = heading.match(/第\s*(\d+)\s*段代码[：:]\s*(.*)/);
	const codeIndex = Number(match?.[1] || 0);
	if (!codeIndex) return null;
	const label = match?.[2]?.trim() || `第 ${codeIndex} 段代码`;
	const streaming = message.stream_state === "streaming";
	return {
		key: `code-${codeIndex}`,
		scope,
		state: streaming ? "generating" : "executing",
		title: streaming
			? `正在生成第 ${codeIndex} 段代码：${label}`
			: `第 ${codeIndex} 段代码已生成，准备执行：${label}`,
		count: codeIndex,
		codeIndex,
		code: codeLines.join("\n").trimStart(),
		streaming,
		order,
	};
}

function thinkingAction(
	message: AgentMessage,
	count: number,
	order: number,
): CodeAction | null {
	if (
		message.agent_type !== AgentType.CODER ||
		message.feedback_kind === "coder_code_stream" ||
		message.stream_state !== "streaming"
	) {
		return null;
	}
	const scope = messageScope(message);
	if (!scope) return null;
	return {
		key: `thinking-${count}`,
		scope,
		state: "thinking",
		title: `正在思考并准备第 ${count + 1} 段代码`,
		count,
		codeIndex: count + 1,
		code: "",
		streaming: true,
		order,
	};
}

function mergeAction(map: Map<string, CodeAction>, action: CodeAction) {
	const previous = map.get(action.key);
	if (!previous) {
		map.set(action.key, action);
		return;
	}
	const state =
		PRIORITY[action.state] >= PRIORITY[previous.state]
			? action.state
			: previous.state;
	const code =
		action.code.length >= previous.code.length ? action.code : previous.code;
	map.set(action.key, {
		...previous,
		...action,
		state,
		code,
		streaming: ACTIVE_STATES.has(state) && action.streaming,
		order: Math.max(previous.order, action.order),
	});
}

function collectProgress(messages: Message[]) {
	const maps = new Map<string, Map<string, CodeAction>>();
	const counts = new Map<string, number>();
	messages.forEach((message, order) => {
		const progress = progressAction(message, order);
		if (progress) {
			const map = maps.get(progress.scope) ?? new Map<string, CodeAction>();
			mergeAction(map, progress);
			maps.set(progress.scope, map);
			counts.set(
				progress.scope,
				Math.max(counts.get(progress.scope) ?? 0, progress.count),
			);
			return;
		}
		if (message.msg_type !== "agent") return;
		const code = codeStreamAction(message as AgentMessage, order);
		if (code) {
			const map = maps.get(code.scope) ?? new Map<string, CodeAction>();
			mergeAction(map, code);
			maps.set(code.scope, map);
			counts.set(code.scope, Math.max(counts.get(code.scope) ?? 0, code.count));
			return;
		}
		const scope = messageScope(message);
		const thinking = thinkingAction(
			message as AgentMessage,
			counts.get(scope) ?? 0,
			order,
		);
		if (!thinking) return;
		const map = maps.get(thinking.scope) ?? new Map<string, CodeAction>();
		mergeAction(map, thinking);
		maps.set(thinking.scope, map);
	});

	const result = new Map<string, ScopeProgress>();
	for (const [scope, map] of maps) {
		const merged = [...map.values()].sort(
			(left, right) => left.order - right.order,
		);
		const codeIndexes = new Set(
			merged
				.filter((action) => action.key.startsWith("code-"))
				.map((action) => action.codeIndex),
		);
		const latestThinking = merged
			.filter((action) => action.state === "thinking")
			.at(-1);
		const actions = merged
			.filter(
				(action) =>
					action.state !== "thinking" ||
					(action === latestThinking && !codeIndexes.has(action.codeIndex)),
			)
			.slice(-MAX_ACTIONS);
		result.set(scope, {
			count: Math.max(
				counts.get(scope) ?? 0,
				...actions.map((action) => action.count),
			),
			actions,
		});
	}
	return result;
}

function stateLabel(state: CodeAction["state"]) {
	if (state === "thinking") return "正在思考";
	if (state === "generating") return "正在生成";
	if (state === "executing") return "正在执行";
	if (state === "completed") return "已完成";
	if (state === "finished") return "求解完成";
	if (state === "error") return "需修正";
	return "未完成";
}

function stateClass(state: CodeAction["state"]) {
	if (ACTIVE_STATES.has(state)) return "cp-active";
	if (state === "completed" || state === "finished") return "cp-done";
	return "cp-warn";
}

function createPanel() {
	const panel = document.createElement("div");
	panel.setAttribute(PANEL_ATTR, "true");
	panel.innerHTML = `<div class="cp-head"><span>实时代码</span><span class="cp-count">0 段</span></div><div class="cp-list"></div>`;
	return panel;
}

function revealExpandedAction(node: HTMLDetailsElement) {
	requestAnimationFrame(() => {
		requestAnimationFrame(() => {
			if (!node.open || !node.isConnected) return;
			const timeline = node.closest(TIMELINE_SELECTOR);
			if (!(timeline instanceof HTMLElement)) return;

			const timelineRect = timeline.getBoundingClientRect();
			const dock = document.querySelector<HTMLElement>(
				CURRENT_ACTION_DOCK_SELECTOR,
			);
			const dockRect =
				dock && dock.getClientRects().length > 0
					? dock.getBoundingClientRect()
					: null;
			const safeTop = timelineRect.top + 10;
			const safeBottom = Math.min(
				timelineRect.bottom - 10,
				dockRect ? dockRect.top - 12 : timelineRect.bottom - 10,
			);
			const actionRect = node.getBoundingClientRect();
			const availableHeight = Math.max(80, safeBottom - safeTop);

			let scrollDelta = 0;
			if (actionRect.height >= availableHeight) {
				scrollDelta = actionRect.top - safeTop;
			} else if (actionRect.bottom > safeBottom) {
				scrollDelta = actionRect.bottom - safeBottom;
			} else if (actionRect.top < safeTop) {
				scrollDelta = actionRect.top - safeTop;
			}
			if (Math.abs(scrollDelta) < 2) return;
			timeline.scrollBy({
				top: scrollDelta,
				behavior: "smooth",
			});
		});
	});
}

function createActionNode(key: string) {
	const node = document.createElement("details");
	node.className = "cp-action";
	node.dataset.actionKey = key;
	node.innerHTML = `<summary><span class="cp-event-icon" aria-hidden="true"></span><span class="cp-title"></span><span class="cp-state"></span><span class="cp-arrow" aria-hidden="true">›</span></summary><pre class="cp-detail"></pre>`;
	node.querySelector("summary")?.addEventListener("click", (event) => {
		if (node.dataset.expandable !== "true") event.preventDefault();
	});
	node.addEventListener("toggle", () => {
		if (node.open) revealExpandedAction(node);
	});
	return node;
}

function updateActionNode(
	node: HTMLDetailsElement,
	action: CodeAction,
	isLatest: boolean,
) {
	node.dataset.active =
		isLatest && ACTIVE_STATES.has(action.state) ? "true" : "false";
	const hasCode = action.code.trim().length > 0;
	node.dataset.expandable = hasCode ? "true" : "false";
	if (!hasCode) node.open = false;
	const title = node.querySelector<HTMLElement>(".cp-title");
	const status = node.querySelector<HTMLElement>(".cp-state");
	const detail = node.querySelector<HTMLElement>(".cp-detail");
	if (title && title.textContent !== action.title)
		title.textContent = action.title;
	if (status) {
		status.className = `cp-state ${stateClass(action.state)}`;
		status.textContent = stateLabel(action.state);
	}
	if (detail) {
		if (detail.textContent !== action.code) detail.textContent = action.code;
		if (hasCode && isLatest && action.streaming) {
			detail.setAttribute("data-streaming-detail", "true");
			detail.classList.add("streaming-detail");
		} else {
			detail.removeAttribute("data-streaming-detail");
			detail.classList.remove("streaming-detail");
		}
	}
}

function hideDefaultCurrent(card: HTMLElement, hidden: boolean) {
	for (const node of card.querySelectorAll<HTMLElement>("div.mt-2")) {
		if (node.hasAttribute(PANEL_ATTR) || !compactText(node).startsWith("当前"))
			continue;
		if (hidden) node.setAttribute(HIDDEN_CURRENT_ATTR, "true");
		else node.removeAttribute(HIDDEN_CURRENT_ATTR);
	}
}

function placeAt(list: HTMLElement, node: HTMLElement, index: number) {
	const current = list.children.item(index);
	if (current !== node) list.insertBefore(node, current);
}

function renderCard(card: HTMLElement, progress?: ScopeProgress) {
	let panel = card.querySelector<HTMLElement>(`[${PANEL_ATTR}="true"]`);
	if (!progress?.actions.length) {
		panel?.remove();
		hideDefaultCurrent(card, false);
		return;
	}
	if (!panel) {
		panel = createPanel();
		card.appendChild(panel);
	}
	hideDefaultCurrent(card, true);
	const count = panel.querySelector<HTMLElement>(".cp-count");
	if (count) count.textContent = `${progress.count} 段`;
	const list = panel.querySelector<HTMLElement>(".cp-list");
	if (!list) return;

	const existing = new Map(
		Array.from(
			list.querySelectorAll<HTMLDetailsElement>("details[data-action-key]"),
		).map((node) => [node.dataset.actionKey || "", node]),
	);
	const wanted = new Set(progress.actions.map((action) => action.key));
	for (const [key, node] of existing) {
		if (!wanted.has(key)) node.remove();
	}
	progress.actions.forEach((action, index) => {
		const node = existing.get(action.key) ?? createActionNode(action.key);
		updateActionNode(node, action, index === progress.actions.length - 1);
		placeAt(list, node, index);
	});
}

function sync() {
	const taskStore = useTaskStore();
	const progress = collectProgress(taskStore.messages as Message[]);
	for (const card of document.querySelectorAll<HTMLElement>(
		".glass-left-panel .subproblem-group-card",
	)) {
		const scope = cardScope(card);
		if (scope) renderCard(card, progress.get(scope));
	}
}

function scheduleSync() {
	if (scheduled) return;
	scheduled = true;
	requestAnimationFrame(() => {
		scheduled = false;
		sync();
	});
}

export function installCoderProgressDomPatch() {
	if (
		installed ||
		typeof window === "undefined" ||
		typeof document === "undefined"
	) {
		return;
	}
	installed = true;
	addStyle();
	const taskStore = useTaskStore();
	watch(
		() =>
			taskStore.messages
				.map((message) => {
					const streamState =
						message.msg_type === "agent" ? (message.stream_state ?? "") : "";
					return `${message.id}:${message.content?.length ?? 0}:${message.feedback_kind ?? ""}:${streamState}`;
				})
				.join("|"),
		scheduleSync,
		{ immediate: true, flush: "post" },
	);
	const observer = new MutationObserver(scheduleSync);
	observer.observe(document.body, { childList: true, subtree: true });
	window.setInterval(scheduleSync, 700);
}
