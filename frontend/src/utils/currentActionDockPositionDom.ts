const STYLE_ID = "current-action-dock-position-style";
const TIMELINE_SELECTOR = "[data-agent-timeline-scroll='true']";
const DOCK_SELECTOR =
	"[data-current-action-dock='true'], [data-current-action-generated='idle']";

let installed = false;
let frameId: number | null = null;

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
${TIMELINE_SELECTOR} {
	padding-bottom: var(--current-action-dock-space, .75rem) !important;
}

${DOCK_SELECTOR} {
	position: fixed !important;
	margin: 0 !important;
	box-sizing: border-box !important;
}
`;
	document.head.appendChild(style);
}

function isVisibleRect(rect: DOMRect) {
	return (
		rect.width > 80 &&
		rect.height > 80 &&
		rect.right > 0 &&
		rect.left < window.innerWidth &&
		rect.bottom > 0 &&
		rect.top < window.innerHeight
	);
}

function positionDock() {
	frameId = null;
	const timeline = document.querySelector<HTMLElement>(TIMELINE_SELECTOR);
	if (!timeline) return;
	const dock = timeline.querySelector<HTMLElement>(DOCK_SELECTOR);
	if (!dock) {
		timeline.style.removeProperty("--current-action-dock-space");
		return;
	}

	const rect = timeline.getBoundingClientRect();
	if (!isVisibleRect(rect)) {
		dock.style.visibility = "hidden";
		return;
	}

	const horizontalInset = 7;
	const bottomInset = 7;
	const left = Math.max(4, rect.left + horizontalInset);
	const width = Math.max(120, rect.width - horizontalInset * 2);
	const bottom = Math.max(4, window.innerHeight - rect.bottom + bottomInset);
	const availableHeight = Math.max(120, rect.height * 0.54);
	const maxHeight = Math.min(window.innerHeight * 0.48, availableHeight, 480);

	dock.style.visibility = "visible";
	dock.style.left = `${Math.round(left)}px`;
	dock.style.width = `${Math.round(width)}px`;
	dock.style.right = "auto";
	dock.style.bottom = `${Math.round(bottom)}px`;
	dock.style.maxHeight = `${Math.round(maxHeight)}px`;

	requestAnimationFrame(() => {
		if (!dock.isConnected || !timeline.isConnected) return;
		const dockHeight = Math.ceil(dock.getBoundingClientRect().height);
		const reserved = Math.min(
			Math.max(46, dockHeight + 16),
			Math.max(80, rect.height * 0.62),
		);
		timeline.style.setProperty("--current-action-dock-space", `${reserved}px`);
	});
}

function schedulePosition() {
	if (frameId != null) return;
	frameId = requestAnimationFrame(positionDock);
}

export function installCurrentActionDockPositionDomPatch() {
	if (installed || typeof window === "undefined" || typeof document === "undefined")
		return;
	installed = true;
	addStyle();
	const observer = new MutationObserver(schedulePosition);
	observer.observe(document.body, {
		childList: true,
		characterData: true,
		subtree: true,
	});
	window.addEventListener("resize", schedulePosition, { passive: true });
	window.addEventListener("scroll", schedulePosition, {
		passive: true,
		capture: true,
	});
	setInterval(schedulePosition, 520);
	schedulePosition();
}
