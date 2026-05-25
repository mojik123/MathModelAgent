import { useTaskStore } from "@/stores/task";

let installed = false;
let lastSignature = "";

interface StoredModelOption {
	id: string;
	label: string;
	description: string;
	pros?: string;
	cons?: string;
	reason?: string;
	score?: number | null;
	isRecommended?: boolean;
	sources?: string[];
}

interface StoredQuestionCard {
	questionIndex: number;
	questionTitle: string;
	questionText: string;
	selectedOptionId?: string;
	researchSummary?: string;
	presetOptions?: StoredModelOption[];
}

function currentTaskId() {
	return (
		window.location.pathname.match(/\/task\/([^/]+)/)?.[1] ||
		window.localStorage.getItem("currentTaskId") ||
		""
	);
}

function normalizeOptions(options: unknown): StoredModelOption[] {
	if (!Array.isArray(options)) return [];
	return options
		.map((option) => {
			if (!option || typeof option !== "object") return null;
			const raw = option as Record<string, unknown>;
			const id = String(raw.id ?? "").trim();
			const label = String(raw.label ?? "").trim();
			if (!id || !label) return null;
			return {
				id,
				label,
				description: String(raw.description ?? "").trim(),
				pros: raw.pros ? String(raw.pros) : undefined,
				cons: raw.cons ? String(raw.cons) : undefined,
				reason: raw.reason ? String(raw.reason) : undefined,
				score: typeof raw.score === "number" ? raw.score : raw.score == null ? null : Number(raw.score),
				isRecommended: Boolean(raw.isRecommended),
				sources: Array.isArray(raw.sources) ? raw.sources.map((s) => String(s)).filter(Boolean) : [],
			};
		})
		.filter((item): item is StoredModelOption => Boolean(item));
}

function readStoredQuestions(taskId: string) {
	try {
		const raw = window.localStorage.getItem(`modeling-discussion:${taskId}`);
		if (!raw) return [];
		const parsed = JSON.parse(raw);
		if (!Array.isArray(parsed)) return [];
		return parsed
			.map((item) => {
				if (!item || typeof item !== "object") return null;
				const rawItem = item as Record<string, unknown>;
				const questionIndex = Number(rawItem.questionIndex);
				const questionText = String(rawItem.questionText ?? "").trim();
				if (!Number.isFinite(questionIndex) || !questionText) return null;
				return {
					questionIndex,
					questionTitle: String(rawItem.questionTitle ?? `第 ${questionIndex} 问`),
					questionText,
					selectedOptionId: String(rawItem.selectedOptionId ?? ""),
					researchSummary: rawItem.researchSummary ? String(rawItem.researchSummary) : undefined,
					presetOptions: normalizeOptions(rawItem.presetOptions),
				};
			})
			.filter((item): item is StoredQuestionCard => Boolean(item));
	} catch {
		return [];
	}
}

function signatureOf(items: StoredQuestionCard[]) {
	return JSON.stringify(
		items.map((q) => ({
			questionIndex: q.questionIndex,
			questionText: q.questionText,
			selectedOptionId: q.selectedOptionId,
			researchSummary: q.researchSummary,
			presetOptions: q.presetOptions?.map((option) => ({
				id: option.id,
				label: option.label,
				description: option.description,
				reason: option.reason,
				isRecommended: option.isRecommended,
				score: option.score,
			})),
		})),
	);
}

function syncDiscussionQuestions() {
	const taskId = currentTaskId();
	if (!taskId) return;
	const stored = readStoredQuestions(taskId);
	if (!stored.length) return;
	const signature = `${taskId}:${signatureOf(stored)}`;
	if (signature === lastSignature) return;
	lastSignature = signature;

	const taskStore = useTaskStore();
	taskStore.discussionQuestions = stored.map((q) => ({
		questionIndex: q.questionIndex,
		questionTitle: q.questionTitle,
		questionText: q.questionText,
		selectedOptionId: q.selectedOptionId ?? "",
		presetOptions: q.presetOptions ?? [],
		researchSummary: q.researchSummary,
	}));

	if (
		taskStore.discussionQuestions.length > 0 &&
		(taskStore.activeDiscussionIndex < 0 || taskStore.activeDiscussionIndex >= taskStore.discussionQuestions.length)
	) {
		taskStore.activeDiscussionIndex = 0;
	}
}

export function installModelingDiscussionSync() {
	if (installed || typeof window === "undefined") return;
	installed = true;
	syncDiscussionQuestions();
	window.addEventListener("storage", (event) => {
		if (event.key?.startsWith("modeling-discussion:")) syncDiscussionQuestions();
	});
	setInterval(syncDiscussionQuestions, 1000);
}
