const STYLE_ID = "smooth-streaming-text-style";
const STREAM_SELECTOR = "[data-streaming-detail='true']";
const TIMELINE_SELECTOR = "[data-agent-timeline-scroll='true']";
const MAX_INITIAL_DELAY_MS = 24;
const ROLLING_PREFIXES = ["…", "..."] as const;

interface StreamAnimationState {
	displayed: string;
	target: string;
	textRafId: number | null;
	scrollRafId: number | null;
	lastFrameAt: number;
	stableScrollTop: number;
}

let installed = false;
let scanning = false;
let rescanRequested = false;
const states = new WeakMap<HTMLElement, StreamAnimationState>();
const followTimeline = new WeakMap<HTMLElement, boolean>();
const followDetail = new WeakMap<HTMLElement, boolean>();
const timelineScrollRafs = new WeakMap<HTMLElement, number>();
const timelineStableTops = new WeakMap<HTMLElement, number>();
const userScrollIntentAt = new WeakMap<HTMLElement, number>();

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
${STREAM_SELECTOR}[data-smooth-streaming="true"] {
	min-height: 1.25em;
	max-height: 8.5rem !important;
	overflow-x: hidden !important;
	overflow-y: auto !important;
	overscroll-behavior: contain;
	overflow-anchor: none;
	scrollbar-width: thin;
	scrollbar-gutter: stable;
	contain: layout paint;
	will-change: scroll-position;
}

${STREAM_SELECTOR}[data-smooth-streaming="true"][data-stream-height-locked="true"] {
	height: var(--stream-locked-height) !important;
	min-height: var(--stream-locked-height) !important;
	max-height: var(--stream-locked-height) !important;
}

${TIMELINE_SELECTOR}:has(${STREAM_SELECTOR}[data-stream-height-locked="true"]) {
	overflow-anchor: none;
}

${STREAM_SELECTOR}[data-smooth-streaming="true"]::after {
	content: "";
	display: inline-block;
	width: 0.42em;
	height: 1em;
	margin-left: 0.14em;
	vertical-align: -0.12em;
	border-radius: 999px;
	background: currentColor;
	opacity: 0.5;
	animation: smoothStreamingCaret 0.92s steps(1, end) infinite;
}

@keyframes smoothStreamingCaret {
	0%, 46% { opacity: 0.58; }
	47%, 100% { opacity: 0.08; }
}

@media (prefers-reduced-motion: reduce) {
	${STREAM_SELECTOR}[data-smooth-streaming="true"]::after {
		animation: none;
		opacity: 0.35;
	}
}
`;
	document.head.appendChild(style);
}

function timelineFor(node: HTMLElement) {
	return node.closest<HTMLElement>(TIMELINE_SELECTOR);
}

function isNearBottom(node: HTMLElement, threshold = 32) {
	return node.scrollHeight - node.scrollTop - node.clientHeight <= threshold;
}

function rollingParts(value: string) {
	for (const prefix of ROLLING_PREFIXES) {
		if (value.startsWith(prefix)) {
			return { prefix, body: value.slice(prefix.length) };
		}
	}
	return { prefix: "", body: value };
}

function commonPrefixLength(left: string, right: string) {
	const limit = Math.min(left.length, right.length);
	let index = 0;
	while (index < limit && left.charCodeAt(index) === right.charCodeAt(index)) {
		index += 1;
	}
	return index;
}

function suffixPrefixOverlapLength(left: string, right: string) {
	const limit = Math.min(left.length, right.length, 8192);
	for (let length = limit; length >= 6; length -= 1) {
		if (left.slice(-length) === right.slice(0, length)) return length;
	}
	return 0;
}

function rememberTimelinePosition(node: HTMLElement) {
	const timeline = timelineFor(node);
	if (timeline && !timelineStableTops.has(timeline)) {
		timelineStableTops.set(timeline, timeline.scrollTop);
	}
}

function lockHeightIfNeeded(node: HTMLElement) {
	if (node.dataset.streamHeightLocked === "true") return;
	const computed = window.getComputedStyle(node);
	const maxHeight = Number.parseFloat(computed.maxHeight);
	if (!Number.isFinite(maxHeight) || maxHeight <= 0) return;
	const height = node.getBoundingClientRect().height;
	if (height < maxHeight - 1 && node.scrollHeight <= node.clientHeight + 1) return;
	const lockedHeight = Math.max(1, Math.round(Math.min(height, maxHeight)));
	node.style.setProperty("--stream-locked-height", `${lockedHeight}px`);
	node.dataset.streamHeightLocked = "true";
	rememberTimelinePosition(node);
}

function restoreLockedScrollPositions(
	node: HTMLElement,
	state: StreamAnimationState,
) {
	if (node.dataset.streamHeightLocked !== "true") return;
	const maxNodeTop = Math.max(0, node.scrollHeight - node.clientHeight);
	node.scrollTop = Math.min(state.stableScrollTop, maxNodeTop);
	const timeline = timelineFor(node);
	const timelineTop = timeline ? timelineStableTops.get(timeline) : undefined;
	if (timeline && timelineTop != null) timeline.scrollTop = timelineTop;
}

function scheduleTimelineFollow(node: HTMLElement) {
	if (node.dataset.streamHeightLocked === "true") return;
	const timeline = timelineFor(node);
	if (!timeline || followTimeline.get(timeline) === false) return;
	if (timelineScrollRafs.has(timeline)) return;

	const tick = () => {
		const remaining = timeline.scrollHeight - timeline.clientHeight - timeline.scrollTop;
		if (remaining <= 0.75 || followTimeline.get(timeline) === false) {
			timeline.scrollTop = Math.max(0, timeline.scrollHeight - timeline.clientHeight);
			timelineStableTops.set(timeline, timeline.scrollTop);
			timelineScrollRafs.delete(timeline);
			return;
		}
		timeline.scrollTop += Math.max(1, remaining * 0.24);
		timelineStableTops.set(timeline, timeline.scrollTop);
		const rafId = requestAnimationFrame(tick);
		timelineScrollRafs.set(timeline, rafId);
	};

	const rafId = requestAnimationFrame(tick);
	timelineScrollRafs.set(timeline, rafId);
}

function scheduleDetailFollow(node: HTMLElement, state: StreamAnimationState) {
	if (followDetail.get(node) === false || state.scrollRafId != null) return;

	const tick = () => {
		if (!node.isConnected || followDetail.get(node) === false) {
			state.scrollRafId = null;
			return;
		}
		const remaining = node.scrollHeight - node.clientHeight - node.scrollTop;
		if (remaining <= 0.5) {
			node.scrollTop = Math.max(0, node.scrollHeight - node.clientHeight);
			state.stableScrollTop = node.scrollTop;
			state.scrollRafId = null;
			return;
		}
		node.scrollTop += Math.max(0.75, remaining * 0.3);
		state.stableScrollTop = node.scrollTop;
		state.scrollRafId = requestAnimationFrame(tick);
	};

	state.scrollRafId = requestAnimationFrame(tick);
}

function writeDisplayed(
	node: HTMLElement,
	state: StreamAnimationState,
	text: string,
) {
	const locked = node.dataset.streamHeightLocked === "true";
	state.displayed = text;
	if (node.textContent !== text) node.textContent = text;
	lockHeightIfNeeded(node);
	if (locked || node.dataset.streamHeightLocked === "true") {
		restoreLockedScrollPositions(node, state);
	}
	scheduleDetailFollow(node, state);
	scheduleTimelineFollow(node);
}

function nextSliceLength(backlog: number, elapsedMs: number) {
	const charactersPerSecond =
		backlog > 2400 ? 720 : backlog > 1000 ? 560 : backlog > 420 ? 360 : 180;
	return Math.max(
		1,
		Math.min(12, Math.round((charactersPerSecond * Math.max(8, elapsedMs)) / 1000)),
	);
}

function reconcileRollingWindow(
	node: HTMLElement,
	state: StreamAnimationState,
) {
	if (state.target.startsWith(state.displayed)) return;

	const displayedParts = rollingParts(state.displayed);
	const targetParts = rollingParts(state.target);
	const overlapLength = suffixPrefixOverlapLength(
		displayedParts.body,
		targetParts.body,
	);
	if (overlapLength > 0) {
		const retained = targetParts.body.slice(0, overlapLength);
		writeDisplayed(node, state, `${targetParts.prefix}${retained}`);
		return;
	}

	const commonLength = commonPrefixLength(state.displayed, state.target);
	const sharedRatio =
		commonLength /
		Math.max(1, Math.min(state.displayed.length, state.target.length));
	if (commonLength >= 12 || sharedRatio >= 0.35) {
		writeDisplayed(node, state, state.target.slice(0, commonLength));
		return;
	}

	// A genuine rewrite is rare. Soften the replacement instead of exposing a large jump.
	node.animate(
		[
			{ opacity: 0.72, transform: "translateY(2px)" },
			{ opacity: 1, transform: "translateY(0)" },
		],
		{ duration: 180, easing: "ease-out" },
	);
	const seedLength = Math.min(12, state.target.length);
	writeDisplayed(node, state, state.target.slice(0, seedLength));
}

function animateNode(
	node: HTMLElement,
	state: StreamAnimationState,
	now: number,
) {
	if (!node.isConnected || node.dataset.streamingDetail !== "true") {
		state.textRafId = null;
		return;
	}

	if (document.visibilityState === "hidden") {
		state.textRafId = null;
		return;
	}

	if (state.displayed === state.target) {
		state.textRafId = null;
		return;
	}

	reconcileRollingWindow(node, state);
	if (state.displayed === state.target) {
		state.textRafId = null;
		return;
	}

	const elapsedMs = Math.max(8, now - state.lastFrameAt);
	state.lastFrameAt = now;
	const backlog = Math.max(0, state.target.length - state.displayed.length);
	const take = nextSliceLength(backlog, elapsedMs);
	writeDisplayed(
		node,
		state,
		state.target.slice(0, state.displayed.length + take),
	);

	if (state.displayed !== state.target) {
		state.textRafId = requestAnimationFrame((timestamp) =>
			animateNode(node, state, timestamp),
		);
	} else {
		state.textRafId = null;
	}
}

function startAnimation(node: HTMLElement, state: StreamAnimationState) {
	if (state.textRafId != null || document.visibilityState === "hidden") return;
	state.lastFrameAt = performance.now();
	state.textRafId = requestAnimationFrame((timestamp) =>
		animateNode(node, state, timestamp),
	);
}

function syncNode(node: HTMLElement) {
	const incoming = node.textContent ?? "";
	const reducedMotion = window.matchMedia(
		"(prefers-reduced-motion: reduce)",
	).matches;
	let state = states.get(node);

	if (!state) {
		state = {
			displayed: reducedMotion ? incoming : "",
			target: incoming,
			textRafId: null,
			scrollRafId: null,
			lastFrameAt: performance.now(),
			stableScrollTop: node.scrollTop,
		};
		states.set(node, state);
		followDetail.set(node, true);
		node.dataset.smoothStreaming = "true";
		rememberTimelinePosition(node);
		if (!reducedMotion && incoming) {
			node.textContent = "";
			setTimeout(() => {
				if (node.isConnected && state?.target) startAnimation(node, state);
			}, MAX_INITIAL_DELAY_MS);
		} else {
			lockHeightIfNeeded(node);
		}
		return;
	}

	if (incoming !== state.displayed && incoming !== state.target) {
		if (node.dataset.streamHeightLocked === "true") {
			restoreLockedScrollPositions(node, state);
		}
		state.target = incoming;
		if (!reducedMotion) node.textContent = state.displayed;
	}
	if (reducedMotion) {
		writeDisplayed(node, state, state.target);
		return;
	}
	if (state.target !== state.displayed) startAnimation(node, state);
	else {
		lockHeightIfNeeded(node);
		scheduleDetailFollow(node, state);
	}
}

function cleanupInactiveNodes() {
	for (const node of Array.from(
		document.querySelectorAll<HTMLElement>("[data-smooth-streaming='true']"),
	)) {
		if (node.matches(STREAM_SELECTOR)) continue;
		const state = states.get(node);
		if (state?.textRafId != null) cancelAnimationFrame(state.textRafId);
		if (state?.scrollRafId != null) cancelAnimationFrame(state.scrollRafId);
		states.delete(node);
		followDetail.delete(node);
		node.removeAttribute("data-smooth-streaming");
		node.removeAttribute("data-stream-height-locked");
		node.style.removeProperty("--stream-locked-height");
	}
}

function scanStreamingNodes() {
	if (scanning) {
		rescanRequested = true;
		return;
	}
	scanning = true;
	try {
		cleanupInactiveNodes();
		for (const node of Array.from(
			document.querySelectorAll<HTMLElement>(STREAM_SELECTOR),
		)) {
			syncNode(node);
		}
	} finally {
		scanning = false;
		if (rescanRequested) {
			rescanRequested = false;
			queueMicrotask(scanStreamingNodes);
		}
	}
}

function markUserScrollIntent(event: Event) {
	const target = event.target as Element | null;
	if (!target) return;
	const detail = target.closest<HTMLElement>(STREAM_SELECTOR);
	const timeline = target.closest<HTMLElement>(TIMELINE_SELECTOR);
	const now = performance.now();
	if (detail) userScrollIntentAt.set(detail, now);
	if (timeline) userScrollIntentAt.set(timeline, now);
}

function hasRecentUserIntent(node: HTMLElement) {
	return performance.now() - (userScrollIntentAt.get(node) ?? -10_000) < 240;
}

function handleScroll(event: Event) {
	const target = event.target as HTMLElement | null;
	if (!target) return;

	if (target.matches?.(TIMELINE_SELECTOR)) {
		const hasLockedStream = Boolean(
			target.querySelector(
				`${STREAM_SELECTOR}[data-stream-height-locked="true"]`,
			),
		);
		const stableTop = timelineStableTops.get(target);
		if (
			hasLockedStream &&
			stableTop != null &&
			!hasRecentUserIntent(target) &&
			Math.abs(target.scrollTop - stableTop) > 1.5
		) {
			target.scrollTop = stableTop;
			return;
		}
		followTimeline.set(target, isNearBottom(target, 120));
		timelineStableTops.set(target, target.scrollTop);
		return;
	}

	if (target.matches?.(STREAM_SELECTOR)) {
		const state = states.get(target);
		if (!state) return;
		if (
			target.dataset.streamHeightLocked === "true" &&
			!hasRecentUserIntent(target) &&
			Math.abs(target.scrollTop - state.stableScrollTop) > 1.5
		) {
			target.scrollTop = Math.min(
				state.stableScrollTop,
				Math.max(0, target.scrollHeight - target.clientHeight),
			);
			scheduleDetailFollow(target, state);
			return;
		}
		followDetail.set(target, isNearBottom(target, 24));
		state.stableScrollTop = target.scrollTop;
	}
}

export function installSmoothStreamingTextDomPatch() {
	if (
		installed ||
		typeof window === "undefined" ||
		typeof document === "undefined"
	) {
		return;
	}
	installed = true;
	addStyle();

	document.addEventListener("wheel", markUserScrollIntent, true);
	document.addEventListener("touchstart", markUserScrollIntent, true);
	document.addEventListener("pointerdown", markUserScrollIntent, true);
	document.addEventListener("scroll", handleScroll, true);
	document.addEventListener("visibilitychange", scanStreamingNodes);
	const observer = new MutationObserver(scanStreamingNodes);
	observer.observe(document.body, {
		childList: true,
		characterData: true,
		subtree: true,
	});
	scanStreamingNodes();
}
