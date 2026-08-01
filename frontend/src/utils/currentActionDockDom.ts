const STYLE_ID = "current-action-dock-style";
const TIMELINE_SELECTOR = "[data-agent-timeline-scroll='true']";
const GENERATED_ATTR = "data-current-action-generated";
const DOCK_ATTR = "data-current-action-dock";
const LEGACY_COMPACT_ATTR = "data-history-compact-row";
const ORIGINAL_ORDER_ATTR = "data-current-action-original-order";

let installed = false;
let scheduled = false;
let syncing = false;

interface CurrentAction {
	actor: string;
	title: string;
	detail: string;
	status: string;
}

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
${TIMELINE_SELECTOR}{
	padding-bottom:var(--current-action-dock-space,.75rem)!important;
}
[${GENERATED_ATTR}="dock"]{
	position:fixed;
	z-index:60;
	box-sizing:border-box;
	margin:0;
	padding:.42rem .55rem .52rem;
	overflow:hidden;
	border:1px solid rgba(96,165,250,.32);
	border-radius:.9rem .9rem .35rem .35rem;
	background:linear-gradient(180deg,rgba(248,250,252,.96),rgba(255,255,255,.98));
	box-shadow:0 -10px 28px rgba(15,23,42,.09),inset 0 1px rgba(255,255,255,.8);
	backdrop-filter:blur(18px) saturate(1.12);
	-webkit-backdrop-filter:blur(18px) saturate(1.12);
}
[${GENERATED_ATTR}="dock"] .action-dock-label{
	margin:0 0 .3rem .16rem;
	font-size:10px;
	line-height:1;
	font-weight:750;
	letter-spacing:.02em;
	color:rgb(30 64 175);
}
[${GENERATED_ATTR}="dock"] .action-mini-chat{
	display:flex;
	align-items:flex-start;
	gap:.45rem;
	min-width:0;
}
[${GENERATED_ATTR}="dock"] .action-mini-avatar{
	display:grid;
	flex:0 0 1.55rem;
	width:1.55rem;
	height:1.55rem;
	place-items:center;
	margin-top:.08rem;
	border:1px solid rgba(255,255,255,.88);
	border-radius:999px;
	background:linear-gradient(145deg,rgb(37 99 235),rgb(20 184 166));
	box-shadow:0 3px 9px rgba(37,99,235,.22);
	font-size:9px;
	font-weight:800;
	color:white;
}
[${GENERATED_ATTR}="dock"] .action-mini-bubble{
	position:relative;
	flex:1 1 auto;
	min-width:0;
	padding:.42rem .55rem .45rem;
	border:1px solid rgba(96,165,250,.2);
	border-radius:.28rem .8rem .8rem .8rem;
	background:linear-gradient(115deg,rgba(239,246,255,.92),rgba(240,253,250,.82));
	box-shadow:0 3px 12px rgba(37,99,235,.07);
}
[${GENERATED_ATTR}="dock"] .action-mini-meta{
	display:flex;
	align-items:center;
	gap:.34rem;
	min-width:0;
	font-size:9px;
	line-height:1.2;
	color:rgb(100 116 139);
}
[${GENERATED_ATTR}="dock"] .action-mini-actor{
	overflow:hidden;
	text-overflow:ellipsis;
	white-space:nowrap;
	font-weight:750;
	color:rgb(51 65 85);
}
[${GENERATED_ATTR}="dock"] .action-mini-status{
	display:inline-flex;
	align-items:center;
	gap:.22rem;
	margin-left:auto;
	white-space:nowrap;
	font-weight:700;
	color:rgb(5 150 105);
}
[${GENERATED_ATTR}="dock"] .action-mini-status::before{
	content:"";
	width:.35rem;
	height:.35rem;
	border-radius:999px;
	background:rgb(16 185 129);
	box-shadow:0 0 0 3px rgba(16,185,129,.12);
	animation:actionDockPulse 1.7s ease-in-out infinite;
}
[${GENERATED_ATTR}="dock"] .action-mini-title{
	overflow:hidden;
	margin-top:.2rem;
	text-overflow:ellipsis;
	white-space:nowrap;
	font-size:11px;
	line-height:1.35;
	font-weight:700;
	color:rgb(30 41 59);
}
[${GENERATED_ATTR}="dock"] .action-mini-detail{
	overflow:hidden;
	margin-top:.08rem;
	text-overflow:ellipsis;
	white-space:nowrap;
	font-size:9px;
	line-height:1.3;
	color:rgb(100 116 139);
}
@keyframes actionDockPulse{
	0%,100%{opacity:.55;transform:scale(.88)}
	50%{opacity:1;transform:scale(1)}
}
@media(prefers-reduced-motion:reduce){
	[${GENERATED_ATTR}="dock"] .action-mini-status::before{animation:none}
}
`;
	document.head.appendChild(style);
}

function compactText(node: Element | null) {
	return (node?.textContent || "").replace(/\s+/g, " ").trim();
}

function getTimeline() {
	return document.querySelector<HTMLElement>(TIMELINE_SELECTOR);
}

function getRows(timeline: HTMLElement) {
	return Array.from(timeline.children).filter(
		(node): node is HTMLElement =>
			node instanceof HTMLElement &&
			!node.hasAttribute(GENERATED_ATTR) &&
			compactText(node).length > 0,
	);
}

function restoreLegacyRows(timeline: HTMLElement, rows: HTMLElement[]) {
	for (const generated of timeline.querySelectorAll<HTMLElement>(
		`[${GENERATED_ATTR}]:not([${GENERATED_ATTR}="dock"])`,
	)) {
		generated.remove();
	}
	for (const row of rows) {
		const originalOrder = row.getAttribute(ORIGINAL_ORDER_ATTR);
		if (originalOrder != null) row.style.order = originalOrder;
		row.removeAttribute(DOCK_ATTR);
		row.removeAttribute("data-current-action-heading");
		row.removeAttribute("data-current-action-hidden");
		row.removeAttribute("data-current-action-source");
		row.removeAttribute(ORIGINAL_ORDER_ATTR);
		row.removeAttribute(LEGACY_COMPACT_ATTR);
		for (const property of [
			"left",
			"right",
			"bottom",
			"width",
			"max-height",
			"visibility",
		]) {
			row.style.removeProperty(property);
		}
		for (const label of row.querySelectorAll<HTMLElement>(
			"[data-history-compact-label='true']",
		)) {
			label.remove();
		}
	}
}

function runningScore(row: HTMLElement) {
	let score = 0;
	if (row.querySelector(".cp-action[data-active='true']")) score += 100;
	if (row.querySelector("[data-running-card='true']")) score += 80;
	if (row.querySelector("[data-streaming-detail='true'], .streaming-detail"))
		score += 60;
	if (row.querySelector(".animate-spin")) score += 40;
	const text = compactText(row);
	if (/进行中|正在生成|正在执行|正在求解|正在思考/.test(text)) score += 20;
	if (/已停止|已完成|求解完成/.test(text) && score < 40) score = 0;
	return score;
}

function selectRunningRow(rows: HTMLElement[]) {
	let selected: HTMLElement | null = null;
	let selectedScore = 0;
	for (const row of rows) {
		const score = runningScore(row);
		if (score >= selectedScore && score > 0) {
			selected = row;
			selectedScore = score;
		}
	}
	return selected;
}

function shortText(value: string, limit: number) {
	const normalized = value.replace(/\s+/g, " ").trim();
	return normalized.length > limit
		? `${normalized.slice(0, Math.max(1, limit - 1))}…`
		: normalized;
}

function findActor(row: HTMLElement) {
	const match = compactText(row).match(
		/(SubCoordinatorAgent|CoordinatorAgent|ModelerAgent|CoderAgent|WriterAgent|SystemMonitor)/,
	);
	if (match?.[1]) return match[1];
	const value = row
		.querySelector<HTMLElement>("[data-agent-card]")
		?.getAttribute("data-agent-card");
	return value && value !== "true" ? shortText(value, 24) : "Agent";
}

function findTitle(row: HTMLElement) {
	const activeTitle = compactText(
		row.querySelector(".cp-action[data-active='true'] .cp-title"),
	);
	if (activeTitle) return shortText(activeTitle, 72);
	const selectors = [
		"[data-running-card='true'] .font-semibold",
		".mt-1.font-semibold",
		".message-title",
		"h3",
		".font-semibold",
	];
	for (const selector of selectors) {
		const matches = row.querySelectorAll(selector);
		for (const match of matches) {
			const title = compactText(match);
			if (
				title &&
				!/^(SubCoordinatorAgent|CoordinatorAgent|CoderAgent|WriterAgent|ModelerAgent)$/.test(
					title,
				)
			) {
				return shortText(title, 72);
			}
		}
	}
	return shortText(compactText(row), 72) || "正在处理当前任务";
}

function currentAction(row: HTMLElement): CurrentAction {
	const actor = findActor(row);
	const title = findTitle(row);
	let state = compactText(
		row.querySelector(".cp-action[data-active='true'] .cp-state"),
	);
	if (!state) {
		const status = Array.from(row.querySelectorAll("span")).find((node) =>
			/^(正在思考|正在生成|正在执行|正在求解|进行中)$/.test(compactText(node)),
		);
		state = compactText(status || null);
	}
	const count = compactText(
		row.querySelector("[data-coder-progress-panel] .cp-count"),
	);
	const scope = row.dataset.coderProgressScope?.toUpperCase() || "";
	return {
		actor,
		title,
		detail: shortText(
			[scope, count].filter(Boolean).join(" · ") || "实时同步求解进度",
			62,
		),
		status: shortText(state || "进行中", 16),
	};
}

function ensureDock(timeline: HTMLElement) {
	let dock = timeline.querySelector<HTMLElement>(
		`:scope > [${GENERATED_ATTR}="dock"]`,
	);
	if (dock) return dock;
	dock = document.createElement("div");
	dock.setAttribute(GENERATED_ATTR, "dock");
	dock.setAttribute(DOCK_ATTR, "true");
	dock.setAttribute("role", "status");
	dock.setAttribute("aria-live", "polite");
	dock.innerHTML = `
		<div class="action-dock-label">当前动作</div>
		<div class="action-mini-chat">
			<span class="action-mini-avatar" aria-hidden="true"></span>
			<div class="action-mini-bubble">
				<div class="action-mini-meta">
					<span class="action-mini-actor"></span>
					<span class="action-mini-status"></span>
				</div>
				<div class="action-mini-title"></div>
				<div class="action-mini-detail"></div>
			</div>
		</div>
	`;
	timeline.appendChild(dock);
	return dock;
}

function setText(root: HTMLElement, selector: string, value: string) {
	const node = root.querySelector<HTMLElement>(selector);
	if (node && node.textContent !== value) node.textContent = value;
}

function renderDock(timeline: HTMLElement, action: CurrentAction | null) {
	const current = timeline.querySelector<HTMLElement>(
		`:scope > [${GENERATED_ATTR}="dock"]`,
	);
	if (!action) {
		current?.remove();
		timeline.style.setProperty("--current-action-dock-space", ".75rem");
		return;
	}
	const dock = current || ensureDock(timeline);
	setText(dock, ".action-mini-avatar", action.actor.slice(0, 1).toUpperCase());
	setText(dock, ".action-mini-actor", action.actor);
	setText(dock, ".action-mini-status", action.status);
	setText(dock, ".action-mini-title", action.title);
	setText(dock, ".action-mini-detail", action.detail);
	positionDock(timeline, dock);
}

function positionDock(timeline: HTMLElement, dock: HTMLElement) {
	const rect = timeline.getBoundingClientRect();
	if (rect.width < 80 || rect.height < 80) {
		dock.style.visibility = "hidden";
		return;
	}
	const inset = 7;
	dock.style.visibility = "visible";
	dock.style.left = `${Math.round(rect.left + inset)}px`;
	dock.style.right = "auto";
	dock.style.bottom = `${Math.max(4, Math.round(window.innerHeight - rect.bottom + inset))}px`;
	dock.style.width = `${Math.max(120, Math.round(rect.width - inset * 2))}px`;
	requestAnimationFrame(() => {
		if (!dock.isConnected || !timeline.isConnected) return;
		const reserved = Math.ceil(dock.getBoundingClientRect().height) + 16;
		timeline.style.setProperty(
			"--current-action-dock-space",
			`${Math.min(Math.max(reserved, 72), 132)}px`,
		);
	});
}

function sync() {
	if (syncing) return;
	const timeline = getTimeline();
	if (!timeline) return;
	syncing = true;
	try {
		const rows = getRows(timeline);
		restoreLegacyRows(timeline, rows);
		const selected = selectRunningRow(rows);
		renderDock(timeline, selected ? currentAction(selected) : null);
	} finally {
		syncing = false;
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

export function installCurrentActionDockDomPatch() {
	if (
		installed ||
		typeof window === "undefined" ||
		typeof document === "undefined"
	)
		return;
	installed = true;
	addStyle();
	const observer = new MutationObserver(scheduleSync);
	observer.observe(document.body, {
		childList: true,
		characterData: true,
		subtree: true,
	});
	window.addEventListener("resize", scheduleSync, { passive: true });
	window.addEventListener("scroll", scheduleSync, {
		passive: true,
		capture: true,
	});
	window.setInterval(scheduleSync, 420);
	scheduleSync();
}
