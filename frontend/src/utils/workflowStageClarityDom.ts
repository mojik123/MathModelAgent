import { useTaskStore } from "@/stores/task";

let installed = false;
let scheduled = false;

function messageText(message: { content?: string | null }) {
	return message.content ?? "";
}

function questionWriterStarted(
	messages: Array<{ content?: string | null }>,
	index: number,
) {
	return messages.some((message) => {
		const text = messageText(message);
		return (
			new RegExp(
				`(?:\\[组#${index}\\]|子问题组#${index}).*论文手开始写`,
				"i",
			).test(text) ||
			new RegExp(`论文手开始写\\s*ques${index}\\b`, "i").test(text)
		);
	});
}

function globalWritingStarted(messages: Array<{ content?: string | null }>) {
	return messages.some((message) =>
		/各问模型、代码求解与灵敏度检验均已完成|并行写作启动|开始终稿整体检查/.test(
			messageText(message),
		),
	);
}

function setPendingStepStyle(element: HTMLElement) {
	const hasActiveStyle =
		element.classList.contains("border-emerald-200") ||
		element.classList.contains("bg-emerald-50") ||
		element.classList.contains("text-emerald-700");
	const hasPendingStyle =
		element.classList.contains("border-slate-200") &&
		element.classList.contains("bg-slate-50") &&
		element.classList.contains("text-slate-400");
	if (hasActiveStyle) {
		element.classList.remove(
			"border-emerald-200",
			"bg-emerald-50",
			"text-emerald-700",
			"shadow-[0_0_0_2px_rgba(16,185,129,0.08)]",
		);
	}
	if (!hasPendingStyle) {
		element.classList.add(
			"border-slate-200",
			"bg-slate-50",
			"text-slate-400",
		);
	}
	const spinner = element.querySelector<SVGElement>("svg.animate-spin");
	if (spinner) {
		const dot = document.createElement("span");
		dot.className = "h-1.5 w-1.5 rounded-full bg-current opacity-50";
		spinner.replaceWith(dot);
	}
}

function updateWritingStep() {
	const taskStore = useTaskStore();
	const messages = taskStore.messages as Array<{ content?: string | null }>;
	const globalStarted = globalWritingStarted(messages);
	const activeQuestionWriters = Array.from(
		{ length: 12 },
		(_, i) => i + 1,
	).filter((index) => questionWriterStarted(messages, index));
	const anyQuestionWriter = activeQuestionWriters.length > 0;

	for (const node of document.querySelectorAll<HTMLElement>(
		".glass-left-panel div[title]",
	)) {
		const text = (node.textContent || "").replace(/\s+/g, "").trim();
		if (text !== "论文写作" && text !== "分问章节写作") continue;
		const desiredLabel = globalStarted ? "论文写作" : "分问章节写作";
		const desiredTitle = globalStarted
			? "所有小问与灵敏度分析完成后的统一论文写作"
			: anyQuestionWriter
				? `${activeQuestionWriters.length} 个问题章节写作中`
				: "等待对应问题代码求解完成后开始章节写作";
		const textNode = Array.from(node.childNodes).find(
			(child) => child.nodeType === Node.TEXT_NODE && child.textContent?.trim(),
		);
		if (textNode && textNode.textContent?.trim() !== desiredLabel) {
			textNode.textContent = ` ${desiredLabel}`;
		}
		if (node.title !== desiredTitle) node.title = desiredTitle;
		if (!globalStarted && !anyQuestionWriter) setPendingStepStyle(node);
	}

	for (const node of document.querySelectorAll<HTMLElement>(
		".glass-left-panel [class*='rounded-full']",
	)) {
		const match = (node.textContent || "").trim().match(/^Q(\d+)\s*·\s*写作中$/);
		if (!match) continue;
		const index = Number(match[1]);
		if (questionWriterStarted(messages, index)) continue;
		node.textContent = `Q${index} · 求解完成，等待写作`;
		node.classList.remove(
			"border-violet-200",
			"bg-violet-50",
			"text-violet-700",
		);
		node.classList.add("border-blue-200", "bg-blue-50", "text-blue-700");
	}
}

function scheduleUpdate() {
	if (scheduled) return;
	scheduled = true;
	requestAnimationFrame(() => {
		scheduled = false;
		updateWritingStep();
	});
}

export function installWorkflowStageClarityDomPatch() {
	if (
		installed ||
		typeof window === "undefined" ||
		typeof document === "undefined"
	) {
		return;
	}
	installed = true;
	const observer = new MutationObserver(scheduleUpdate);
	observer.observe(document.body, {
		childList: true,
		subtree: true,
		characterData: true,
	});
	window.setInterval(scheduleUpdate, 800);
	scheduleUpdate();
}
