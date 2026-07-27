const STYLE_ID = "smooth-streaming-text-style";
const STREAM_SELECTOR = "[data-streaming-detail='true']";
const TIMELINE_SELECTOR = "[data-agent-timeline-scroll='true']";
const MAX_INITIAL_DELAY_MS = 48;

interface StreamAnimationState {
	displayed: string;
	target: string;
	rafId: number | null;
	lastFrameAt: number;
}

let installed = false;
let scanRaf: number | null = null;
const states = new WeakMap<HTMLElement, StreamAnimationState>();
const followTimeline = new WeakMap<HTMLElement, boolean>();

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
${STREAM_SELECTOR}[data-smooth-streaming="true"] {
	min-height: 1.25em;
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

function isNearBottom(node: HTMLElement, threshold = 140) {
	return node.scrollHeight - node.scrollTop - node.clientHeight <= threshold;
}

function keepScrollFollowing(node: HTMLElement) {
	node.scrollTop = node.scrollHeight;
	const timeline = timelineFor(node);
	if (!timeline || followTimeline.get(timeline) === false) return;
	timeline.scrollTop = timeline.scrollHeight;
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
	const limit = Math.min(left.length, right.length, 640);
	for (let length = limit; length >= 24; length -= 1) {
		if (left.slice(-length) === right.slice(0, length)) return length;
	}
	return 0;
}

function writeDisplayed(
	node: HTMLElement,
	state: StreamAnimationState,
	text: string,
) {
	state.displayed = text;
	if (node.textContent !== text) node.textContent = text;
	keepScrollFollowing(node);
}

function nextSliceLength(backlog: number, elapsedMs: number) {
	const timeFactor = Math.max(1, Math.round(elapsedMs / 16));
	const backlogFactor = Math.max(1, Math.ceil(backlog / 70));
	return Math.min(16, timeFactor * backlogFactor);
}

function animateNode(
	node: HTMLElement,
	state: StreamAnimationState,
	now: number,
) {
	if (!node.isConnected || node.dataset.streamingDetail !== "true") {
		if (state.rafId != null) cancelAnimationFrame(state.rafId);
		state.rafId = null;
		return;
	}

	if (document.visibilityState === "hidden") {
		writeDisplayed(node, state, state.target);
		state.rafId = null;
		return;
	}

	if (state.displayed === state.target) {
		state.rafId = null;
		return;
	}

	if (!state.target.startsWith(state.displayed)) {
		const overlapLength = suffixPrefixOverlapLength(state.displayed, state.target);
		if (overlapLength > 0) {
			writeDisplayed(node, state, state.target.slice(0, overlapLength));
		} else {
			const commonLength = commonPrefixLength(state.displayed, state.target);
			const sharedRatio =
				commonLength /
				Math.max(1, Math.min(state.displayed.length, state.target.length));
			if (sharedRatio >= 0.55) {
				writeDisplayed(node, state, state.target.slice(0, commonLength));
			} else {
				writeDisplayed(node, state, state.target);
				state.rafId = null;
				return;
			}
		}
	}

	const elapsedMs = Math.max(16, now - state.lastFrameAt);
	state.lastFrameAt = now;
	const backlog = state.target.length - state.displayed.length;
	const take = nextSliceLength(backlog, elapsedMs);
	writeDisplayed(
		node,
		state,
		state.target.slice(0, state.displayed.length + take),
	);

	if (state.displayed !== state.target) {
		state.rafId = requestAnimationFrame((timestamp) =>
			animateNode(node, state, timestamp),
		);
	} else {
		state.rafId = null;
	}
}

function startAnimation(node: HTMLElement, state: StreamAnimationState) {
	if (state.rafId != null) return;
	state.lastFrameAt = performance.now();
	state.rafId = requestAnimationFrame((timestamp) =>
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
			rafId: null,
			lastFrameAt: performance.now(),
		};
		states.set(node, state);
		node.dataset.smoothStreaming = "true";
		if (!reducedMotion && incoming) {
			node.textContent = "";
			setTimeout(() => {
				if (node.isConnected && state?.target) startAnimation(node, state);
			}, MAX_INITIAL_DELAY_MS);
		}
		return;
	}

	if (incoming !== state.displayed && incoming !== state.target) {
		state.target = incoming;
		if (!reducedMotion) node.textContent = state.displayed;
	}
	if (reducedMotion) {
		writeDisplayed(node, state, state.target);
		return;
	}
	if (state.target !== state.displayed) startAnimation(node, state);
}

function scanStreamingNodes() {
	scanRaf = null;
	for (const node of Array.from(
		document.querySelectorAll<HTMLElement>(STREAM_SELECTOR),
	)) {
		syncNode(node);
	}
}

function scheduleScan() {
	if (scanRaf != null) return;
	scanRaf = requestAnimationFrame(scanStreamingNodes);
}

function handleTimelineScroll(event: Event) {
	const timeline = event.target as HTMLElement | null;
	if (!timeline?.matches?.(TIMELINE_SELECTOR)) return;
	followTimeline.set(timeline, isNearBottom(timeline));
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

	document.addEventListener("scroll", handleTimelineScroll, true);
	const observer = new MutationObserver(scheduleScan);
	observer.observe(document.body, {
		childList: true,
		characterData: true,
		subtree: true,
	});
	scheduleScan();
}
