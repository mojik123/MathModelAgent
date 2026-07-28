import { useTaskStore } from "@/stores/task";
import { AgentType } from "@/utils/enum";
import type { AgentMessage, Message } from "@/utils/response";
import { watch } from "vue";

const STYLE_ID = "coder-progress-dom-style";
const PANEL_ATTR = "data-coder-progress-panel";
const OLD_CURRENT_HIDDEN_ATTR = "data-coder-default-current-hidden";
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
	label: string;
	detail: string;
	streaming: boolean;
	time: string;
	order: number;
}

interface ScopeProgress {
	scope: string;
	count: number;
	actions: CodeAction[];
}

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
[${OLD_CURRENT_HIDDEN_ATTR}="true"] { display: none !important; }

[${PANEL_ATTR}="true"] {
	margin-top: .55rem;
	border: 1px solid rgba(148, 163, 184, .28);
	border-radius: .8rem;
	background: rgba(255, 255, 255, .68);
	box-shadow: inset 0 1px 0 rgba(255, 255, 255, .72);
	overflow: hidden;
}

[${PANEL_ATTR}="true"] .coder-progress-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: .5rem;
	padding: .45rem .6rem;
	border-bottom: 1px solid rgba(148, 163, 184, .18);
	font-size: 10px;
	color: rgb(71 85 105);
}

[${PANEL_ATTR}="true"] .coder-progress-count {
	flex: 0 0 auto;
	border: 1px solid rgba(59, 130, 246, .18);
	border-radius: 999px;
	background: rgba(239, 246, 255, .86);
	padding: 2px 7px;
	font-weight: 700;
	color: rgb(29 78 216);
}

[${PANEL_ATTR}="true"] .coder-action-list {
	display: flex;
	flex-direction: column;
	padding: .2rem .35rem .35rem;
}

[${PANEL_ATTR}="true"] .coder-action {
	position: relative;
	border-radius: .65rem;
	transition: background .18s ease, box-shadow .18s ease;
}

[${PANEL_ATTR}="true"] .coder-action + .coder-action {
	border-top: 1px solid rgba(148, 163, 184, .12);
}

[${PANEL_ATTR}="true"] .coder-action > summary {
	display: grid;
	grid-template-columns: auto minmax(0, 1fr) auto;
	align-items: center;
	gap: .45rem;
	min-height: 30px;
	padding: .35rem .42rem;
	cursor: pointer;
	list-style: none;
	font-size: 11px;
	color: rgb(51 65 85);
}

[${PANEL_ATTR}="true"] .coder-action > summary::-webkit-details-marker { display: none; }

[${PANEL_ATTR}="true"] .coder-action-chevron {
	width: 0;
	height: 0;
	border-top: 4px solid transparent;
	border-bottom: 4px solid transparent;
	border-left: 5px solid currentColor;
	opacity: .45;
	transition: transform .16s ease;
}

[${PANEL_ATTR}="true"] .coder-action[open] .coder-action-chevron {
	transform: rotate(90deg);
}

[${PANEL_ATTR}="true"] .coder-action-title {
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
	font-weight: 650;
}

[${PANEL_ATTR}="true"] .coder-action-state {
	flex: 0 0 auto;
	border-radius: 999px;
	padding: 2px 6px;
	font-size: 9px;
	font-weight: 750;
}

[${PANEL_ATTR}="true"] .coder-action-detail {
	margin: 0 .45rem .45rem 1.35rem;
	max-height: 9rem;
	overflow: auto;
	white-space: pre-wrap;
	word-break: break-word;
	border: 1px solid rgba(148, 163, 184, .18);
	border-radius: .55rem;
	background: rgba(248, 250, 252, .9);
	padding: .48rem .55rem;
	font: 10px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
	color: rgb(71 85 105);
	scrollbar-width: thin;
}

[${PANEL_ATTR}="true"] .coder-action[data-active="true"] {
	background: linear-gradient(105deg, rgba(236, 253, 245, .72), rgba(239, 246, 255, .76), rgba(250, 245, 255, .72));
	box-shadow: 0 0 0 1px rgba(59, 130, 246, .08), 0 5px 18px rgba(59, 130, 246, .08);
	overflow: hidden;
}

[${PANEL_ATTR}="true"] .coder-action[data-active="true"]::after {
	content: "";
	position: absolute;
	inset: 0;
	pointer-events: none;
	background: linear-gradient(105deg, transparent 30%, rgba(255,255,255,.72) 48%, transparent 66%);
	transform: translateX(-120%);
	animation: coderActionSweep 2.2s ease-in-out infinite;
}

[${PANEL_ATTR}="true"] .coder-action[data-active="true"] .coder-action-title {
	color: rgb(15 118 110);
}

[${PANEL_ATTR}="true"] .state-thinking,
[${PANEL_ATTR}="true"] .state-generating,
[${PANEL_ATTR}="true"] .state-executing {
	background: rgb(236 253 245);
	color: rgb(4 120 87);
}

[${PANEL_ATTR}="true"] .state-completed,
[${PANEL_ATTR}="true"] .state-finished {
	background: rgb(239 246 255);
	color: rgb(29 78 216);
}

[${PANEL_ATTR}="true"] .state-error,
[${PANEL_ATTR}="true"] .state-incomplete {
	background: rgb(255 247 237);
	color: rgb(194 65 12);
}

@keyframes coderActionSweep {
	0%, 22% { transform: translateX(-120%); opacity: 0; }
	42% { opacity: .75; }
	68%, 100% { transform: translateX(120%); opacity: 0; }
}

@media (prefers-reduced-motion: reduce) {
	[${PANEL_ATTR}="true"] .coder-action[data-active="true"]::after { animation: none; }
}
`;
	document.head.appendChild(style);
}

function textOf(node: Element | null) {
	return (node?.textContent || "").replace(/\s+/g, " ").trim();
}

function messageCorpus(message: Message) {
	return [
		message.content ?? "",
		message.group_id ?? "",
		message.agent_instance_id ?? "",
		message.phase ?? "",
	]
		.join("\n")
		.replace(/\\/g, "/");
}

function scopeOfMessage(message: Message) {
	if (typeof message.question_index === "number" && message.question_index > 0) {
		return `q${message.question_index}`;
	}
	const corpus = messageCorpus(message);
	const qMatch = corpus.match(/q(?:ues)?(\d+)|子问题组#?(\d+)|问题\s*(\d+)/i);
	if (qMatch) return `q${qMatch[1] || qMatch[2] || qMatch[3]}`;
	const subtask = corpus.match(/子任务[：:]\s*([^\n]+)/)?.[1]?.trim().toLowerCase();
	if (subtask === "eda" || /\bEDA\b|数据探索|描述性统计|数据预处理/i.test(corpus)) {
		return "eda";
	}
	if (
		subtask === "sensitivity_analysis" ||
		/灵敏度分析|敏感性分析|sensitivity_analysis/i.test(corpus)
	) {
		return "sensitivity";
	}
	return "";
}

function scopeOfCard(card: HTMLElement) {
	const text = textOf(card);
	const qMatch = text.match(/(?:问题|子问题组)\s*(\d+)|\bQ(\d+)\b/i);
	if (qMatch) return `q${qMatch[1] || qMatch[2]}`;
	if (/\bEDA\b|数据探索|描述性统计|数据预处理/i.test(text)) return "eda";
	if (/灵敏度分析|敏感性分析/.test(text)) return "sensitivity";
	return "";
}

function parseProgress(message: Message, order: number): CodeAction | null {
	const content = message.content ?? "";
	if (message.feedback_kind !== "coder_progress" && !content.startsWith("代码求解进度：")) {
		return null;
	}
	const scope = scopeOfMessage(message);
	if (!scope) return null;
	const firstLine = content.split("\n")[0] ?? "";
	const title = firstLine
		.replace(/^代码求解进度[：:]/, "")
		.replace(/｜已生成\s*\d+\s*段代码.*$/, "")
		.trim();
	const state = (content.match(/状态[：:]\s*([^\n]+)/)?.[1]?.trim() || "thinking") as CodeAction["state"];
	const count = Number(content.match(/(?:已生成|共生成)\s*(\d+)\s*段代码/)?.[1] || 0);
	const codeIndex = Number(content.match(/代码序号[：:]\s*(\d+)/)?.[1] || 0);
	const label = content.match(/代码名称[：:]\s*([^\n]+)/)?.[1]?.trim() || "";
	const key =
		codeIndex > 0 && ["generating", "executing", "completed", "error"].includes(state)
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
		label,
		detail: label && title !== label ? label : "",
		streaming: ["thinking", "generating", "executing"].includes(state),
		time: message.created_at ?? "",
		order,
	};
}

function parseCodeStream(message: AgentMessage, order: number): CodeAction | null {
	if (message.feedback_kind !== "coder_code_stream") return null;
	const scope = scopeOfMessage(message);
	if (!scope) return null;
	const content = message.content ?? "";
	const [heading = "", ...codeLines] = content.split("\n");
	const match = heading.match(/第\s*(\d+)\s*段代码[：:]\s*(.*)/);
	const codeIndex = Number(match?.[1] || 0);
	if (!codeIndex) return null;
	const label = match?.[2]?.trim() || `第 ${codeIndex} 段代码`;
	return {
		key: `code-${codeIndex}`,
		scope,
		state: message.stream_state === "streaming" ? "generating" : "executing",
		title:
			message.stream_state === "streaming"
				? `正在生成第 ${codeIndex} 段代码：${label}`
				: `第 ${codeIndex} 段代码已生成，准备执行：${label}`,
		count: codeIndex,
		codeIndex,
		label,
		detail: codeLines.join("\n"),
		streaming: message.stream_state === "streaming",
		time: message.created_at ?? "",
		order,
	};
}

function regularCoderStream(message: AgentMessage, count: number, order: number): CodeAction | null {
	if (
		message.agent_type !== AgentType.CODER ||
		message.feedback_kind === "coder_code_stream" ||
		message.stream_state !== "streaming"
	) {
		return null;
	}
	const scope = scopeOfMessage(message);
	if (!scope) return null;
	return {
		key: `thinking-${count}`,
		scope,
		state: "thinking",
		title: `正在思考并准备第 ${count + 1} 段代码`,
		count,
		codeIndex: count + 1,
		label: "",
		detail: message.content ?? "",
		streaming: true,
		time: message.created_at ?? "",
		order,
	};
}

function mergeAction(target: Map<string, CodeAction>, next: CodeAction) {
	const previous = target.get(next.key);
	if (!previous) {
		target.set(next.key, next);
		return;
	}
	const statePriority: Record<CodeAction["state"], number> = {
		thinking: 1,
		generating: 2,
		executing: 3,
		completed: 4,
		error: 4,
		finished: 5,
		incomplete: 5,
	};
	const keepState =
		statePriority[next.state] >= statePriority[previous.state]
			? next.state
			: previous.state;
	target.set(next.key, {
		...previous,
		...next,
		state: keepState,
		detail: next.detail || previous.detail,
		streaming:
			keepState === "completed" || keepState === "error" || keepState === "finished"
				? false
				: next.streaming,
		order: Math.max(previous.order, next.order),
	});
}

function collectProgress(messages: Message[]) {
	const byScope = new Map<string, Map<string, CodeAction>>();
	const counts = new Map<string, number>();
	messages.forEach((message, order) => {
		const progress = parseProgress(message, order);
		if (progress) {
			const map = byScope.get(progress.scope) ?? new Map<string, CodeAction>();
			mergeAction(map, progress);
			byScope.set(progress.scope, map);
			counts.set(progress.scope, Math.max(counts.get(progress.scope) ?? 0, progress.count));
			return;
		}
		if (message.msg_type !== "agent") return;
		const codeStream = parseCodeStream(message as AgentMessage, order);
		if (codeStream) {
			const map = byScope.get(codeStream.scope) ?? new Map<string, CodeAction>();
			mergeAction(map, codeStream);
			byScope.set(codeStream.scope, map);
			counts.set(codeStream.scope, Math.max(counts.get(codeStream.scope) ?? 0, codeStream.count));
			return;
		}
		const scope = scopeOfMessage(message);
		const stream = regularCoderStream(
			message as AgentMessage,
			counts.get(scope) ?? 0,
			order,
		);
		if (!stream) return;
		const map = byScope.get(stream.scope) ?? new Map<string, CodeAction>();
		mergeAction(map, stream);
		byScope.set(stream.scope, map);
	});

	const result = new Map<string, ScopeProgress>();
	for (const [scope, actionsMap] of byScope) {
		const actions = [...actionsMap.values()]
			.sort((left, right) => left.order - right.order)
			.slice(-MAX_ACTIONS);
		result.set(scope, {
			scope,
			count: Math.max(counts.get(scope) ?? 0, ...actions.map((action) => action.count)),
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

function activeState(state: CodeAction["state"]) {
	return ["thinking", "generating", "executing"].includes(state);
}

function createPanel() {
	const panel = document.createElement("div");
	panel.setAttribute(PANEL_ATTR, "true");
	panel.innerHTML = `
		<div class="coder-progress-head">
			<span class="coder-progress-caption">代码求解动态</span>
			<span class="coder-progress-count">已生成 0 段代码</span>
		</div>
		<div class="coder-action-list"></div>
	`;
	return panel;
}

function actionNode(action: CodeAction) {
	const details = document.createElement("details");
	details.className = "coder-action";
	details.dataset.actionKey = action.key;
	details.innerHTML = `
		<summary>
			<span class="coder-action-chevron" aria-hidden="true"></span>
			<span class="coder-action-title"></span>
			<span class="coder-action-state"></span>
		</summary>
		<pre class="coder-action-detail"></pre>
	`;
	return details;
}

function updateActionNode(node: HTMLDetailsElement, action: CodeAction, isLatest: boolean) {
	node.dataset.active = isLatest && activeState(action.state) ? "true" : "false";
	const title = node.querySelector<HTMLElement>(".coder-action-title");
	const state = node.querySelector<HTMLElement>(".coder-action-state");
	const detail = node.querySelector<HTMLElement>(".coder-action-detail");
	if (title && title.textContent !== action.title) title.textContent = action.title;
	if (state) {
		state.className = `coder-action-state state-${action.state}`;
		state.textContent = stateLabel(action.state);
	}
	if (detail) {
		const detailText = action.detail || `${action.title}\n已生成 ${action.count} 段代码`;
		if (detail.textContent !== detailText) detail.textContent = detailText;
		if (action.streaming && isLatest) {
			detail.setAttribute("data-streaming-detail", "true");
			detail.classList.add("streaming-detail");
		} else {
			detail.removeAttribute("data-streaming-detail");
			detail.classList.remove("streaming-detail");
		}
	}
}

function hideDefaultCurrent(card: HTMLElement, hidden: boolean) {
	for (const child of Array.from(card.querySelectorAll<HTMLElement>("div.mt-2"))) {
		if (child.hasAttribute(PANEL_ATTR)) continue;
		if (!textOf(child).startsWith("当前")) continue;
		if (hidden) child.setAttribute(OLD_CURRENT_HIDDEN_ATTR, "true");
		else child.removeAttribute(OLD_CURRENT_HIDDEN_ATTR);
	}
}

function renderCard(card: HTMLElement, progress: ScopeProgress | undefined) {
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
	const count = panel.querySelector<HTMLElement>(".coder-progress-count");
	if (count) count.textContent = `已生成 ${progress.count} 段代码`;
	const list = panel.querySelector<HTMLElement>(".coder-action-list");
	if (!list) return;
	const existing = new Map(
		Array.from(list.querySelectorAll<HTMLDetailsElement>("details[data-action-key]")).map(
			(node) => [node.dataset.actionKey || "", node],
		),
	);
	const wanted = new Set(progress.actions.map((action) => action.key));
	for (const [key, node] of existing) {
		if (!wanted.has(key)) node.remove();
	}
	progress.actions.forEach((action, index) => {
		let node = existing.get(action.key);
		if (!node || !node.isConnected) node = actionNode(action);
		updateActionNode(node, action, index === progress.actions.length - 1);
		list.appendChild(node);
	});
}

function syncCoderProgress() {
	const taskStore = useTaskStore();
	const progressByScope = collectProgress(taskStore.messages as Message[]);
	const cards = Array.from(
		document.querySelectorAll<HTMLElement>(".glass-left-panel .subproblem-group-card"),
	);
	for (const card of cards) {
		const scope = scopeOfCard(card);
		if (!scope) continue;
		renderCard(card, progressByScope.get(scope));
	}
}

function scheduleSync() {
	if (scheduled) return;
	scheduled = true;
	requestAnimationFrame(() => {
		scheduled = false;
		syncCoderProgress();
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
				.map(
					(message) =>
						`${message.id}:${message.content?.length ?? 0}:${message.feedback_kind ?? ""}:${
							message.msg_type === "agent" ? message.stream_state ?? "" : ""
						}`,
				)
				.join("|"),
		scheduleSync,
		{ immediate: true, flush: "post" },
	);
	const observer = new MutationObserver(scheduleSync);
	observer.observe(document.body, { childList: true, subtree: true });
	window.setInterval(scheduleSync, 700);
}
