const CONFIRMATION_ROW_ATTR = "data-question-confirmation-flow-row";
const NORMALIZED_ATTR = "data-user-confirmation-card-normalized";

let installed = false;
let scheduled = false;

function confirmationMarkup() {
	return `
		<div class="flex max-w-[98%] gap-1.5 flex-row-reverse">
			<div class="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white shadow-sm" aria-hidden="true">
				<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-3.5 w-3.5">
					<circle cx="12" cy="8" r="5"></circle>
					<path d="M20 21a8 8 0 0 0-16 0"></path>
				</svg>
			</div>
			<div class="min-w-0 rounded-2xl rounded-tr-md border border-slate-800 bg-slate-900 px-3 py-2.5 text-white shadow-sm">
				<div class="flex items-start justify-between gap-3">
					<div class="min-w-0">
						<div class="flex flex-wrap items-center gap-1.5">
							<span class="text-[11px] font-semibold opacity-70">User</span>
							<span class="text-[10px] opacity-45">用户确认</span>
						</div>
						<div class="mt-1 flex items-center gap-1.5 text-sm font-semibold">
							<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-3.5 w-3.5">
								<circle cx="12" cy="12" r="10"></circle>
								<path d="m9 12 2 2 4-4"></path>
							</svg>
							<span>已确认问题划分</span>
						</div>
					</div>
				</div>
				<p class="message-detail mt-1.5 whitespace-pre-wrap break-words text-xs leading-relaxed opacity-80">确认当前问题结构，继续进入建模方案选择阶段。</p>
			</div>
		</div>
	`;
}

function normalizeConfirmationCards() {
	for (const row of document.querySelectorAll<HTMLElement>(
		`[${CONFIRMATION_ROW_ATTR}="true"]`,
	)) {
		if (row.getAttribute(NORMALIZED_ATTR) === "true") continue;
		row.className = "flex w-full justify-end";
		row.innerHTML = confirmationMarkup();
		row.setAttribute(NORMALIZED_ATTR, "true");
	}
}

function scheduleNormalize() {
	if (scheduled) return;
	scheduled = true;
	requestAnimationFrame(() => {
		scheduled = false;
		normalizeConfirmationCards();
	});
}

export function installUserConfirmationCardDomPatch() {
	if (
		installed ||
		typeof window === "undefined" ||
		typeof document === "undefined"
	) {
		return;
	}
	installed = true;
	const observer = new MutationObserver(scheduleNormalize);
	observer.observe(document.body, {
		childList: true,
		subtree: true,
	});
	window.setInterval(scheduleNormalize, 800);
	scheduleNormalize();
}
