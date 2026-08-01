import { useArtifactEditStore } from "@/stores/artifactEdit";
import { useTaskStore } from "@/stores/task";
import type { Message } from "@/utils/response";
import { storeToRefs } from "pinia";
import { watch } from "vue";

const TARGET_LABEL = "当前修改对象";
const EDIT_ROOT_ID = "artifact-edit-chat-root";
const ACTIVATION_GRACE_MS = 500;

let installed = false;
let activeChangedAt = 0;
let selectionModeAtActivation: "writer" | "fallback" = "fallback";
let cleanupTimer: ReturnType<typeof setInterval> | null = null;

function isTransientTargetMessage(message: Message) {
	if (!message.local_action) return false;
	const action = "action" in message ? message.action : undefined;
	if (action?.flow?.label === TARGET_LABEL) return true;
	return (
		message.msg_type === "user" &&
		(message.content || "").trim().startsWith(`${TARGET_LABEL}：`)
	);
}

function transientMessages() {
	const taskStore = useTaskStore();
	return taskStore.messages as Message[];
}

function removeTransientTargetMessages() {
	const messages = transientMessages();
	for (let index = messages.length - 1; index >= 0; index -= 1) {
		if (isTransientTargetMessage(messages[index])) messages.splice(index, 1);
	}
}

function keepOnlyLatestTransientTargetMessage() {
	const messages = transientMessages();
	let keptLatest = false;
	for (let index = messages.length - 1; index >= 0; index -= 1) {
		if (!isTransientTargetMessage(messages[index])) continue;
		if (!keptLatest) {
			keptLatest = true;
			continue;
		}
		messages.splice(index, 1);
	}
}

function hideEditInputImmediately() {
	const root = document.getElementById(EDIT_ROOT_ID);
	if (!root) return;
	root.innerHTML = "";
	root.style.display = "none";
	delete root.dataset.renderKey;
}

function removeFallbackSelectionMarkers() {
	for (const element of document.querySelectorAll<HTMLElement>(
		".paper-preview [data-artifact-edit-selected='true']",
	)) {
		element.removeAttribute("data-artifact-edit-selected");
	}
}

function selectionNodeInsidePaper(node: Node | null) {
	const element =
		node instanceof HTMLElement ? node : node?.parentElement || null;
	return Boolean(element?.closest(".paper-preview"));
}

function hasNativePaperTextSelection() {
	const selection = window.getSelection();
	return Boolean(
		selection &&
		!selection.isCollapsed &&
		selection.toString().trim().length >= 2 &&
		(selectionNodeInsidePaper(selection.anchorNode) ||
			selectionNodeInsidePaper(selection.focusNode)),
	);
}

function hasVisiblePaperTextSelection() {
	if (selectionModeAtActivation === "writer") {
		return Boolean(document.querySelector(".paper-preview .sentence-selected"));
	}
	return Boolean(
		document.querySelector(
			".paper-preview [data-artifact-edit-selected='true']",
		) || hasNativePaperTextSelection(),
	);
}

function clearCancelledTextTarget() {
	keepOnlyLatestTransientTargetMessage();
	const editStore = useArtifactEditStore();
	const context = editStore.activeContext;
	if (!context || context.targetType !== "text") return;
	if (context.status === "running") return;
	if (Date.now() - activeChangedAt < ACTIVATION_GRACE_MS) return;
	if (hasVisiblePaperTextSelection()) return;

	editStore.clearActive();
	removeTransientTargetMessages();
	removeFallbackSelectionMarkers();
	hideEditInputImmediately();
}

function installClearButtonFallback() {
	document.addEventListener(
		"click",
		(event) => {
			const target = event.target as HTMLElement | null;
			if (!target?.closest(".artifact-edit-chat-clear")) return;
			queueMicrotask(() => {
				removeTransientTargetMessages();
				removeFallbackSelectionMarkers();
				hideEditInputImmediately();
			});
		},
		true,
	);
}

export function installArtifactEditSelectionCleanupDomPatch() {
	if (
		installed ||
		typeof window === "undefined" ||
		typeof document === "undefined"
	) {
		return;
	}
	installed = true;

	const editStore = useArtifactEditStore();
	const { activeContext } = storeToRefs(editStore);

	watch(
		() => activeContext.value?.sessionId || "",
		(nextSessionId, previousSessionId) => {
			activeChangedAt = Date.now();
			selectionModeAtActivation = document.querySelector(
				".paper-preview .sentence-selected",
			)
				? "writer"
				: "fallback";
			if (nextSessionId !== previousSessionId) {
				removeTransientTargetMessages();
			}
			if (!nextSessionId) hideEditInputImmediately();
		},
		{ flush: "sync" },
	);

	installClearButtonFallback();
	cleanupTimer = setInterval(clearCancelledTextTarget, 250);
	window.addEventListener("beforeunload", () => {
		if (cleanupTimer) clearInterval(cleanupTimer);
		cleanupTimer = null;
	});
}
