import { defineStore } from "pinia";
import { computed, ref } from "vue";

export type ArtifactEditTargetType = "image" | "text";
export type ArtifactEditStatus = "active" | "running" | "done" | "failed";

export interface ArtifactEditContext {
	sessionId: string;
	taskId: string;
	targetType: ArtifactEditTargetType;
	targetPath: string;
	targetLabel: string;
	sectionTitle?: string;
	excerpt?: string;
	previewUrl?: string;
	description?: string;
	status: ArtifactEditStatus;
	messages: Array<{ role: "user" | "assistant"; content: string }>;
	createdAt: number;
	updatedAt: number;
}

function storageKey(taskId: string) {
	return `artifact-edit-sessions:${taskId}`;
}

function makeSessionId(prefix: ArtifactEditTargetType) {
	return `edit-${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export const useArtifactEditStore = defineStore("artifactEdit", () => {
	const activeContext = ref<ArtifactEditContext | null>(null);
	const sessions = ref<ArtifactEditContext[]>([]);

	const hasActive = computed(() => Boolean(activeContext.value));

	function restore(taskId: string) {
		if (typeof window === "undefined" || !taskId) return;
		try {
			const raw = window.localStorage.getItem(storageKey(taskId));
			const parsed = raw ? JSON.parse(raw) : [];
			sessions.value = Array.isArray(parsed) ? parsed : [];
			if (activeContext.value?.taskId !== taskId) activeContext.value = null;
		} catch {
			sessions.value = [];
			activeContext.value = null;
		}
	}

	function persist(taskId?: string) {
		if (typeof window === "undefined") return;
		const id = taskId || activeContext.value?.taskId || sessions.value[0]?.taskId;
		if (!id) return;
		window.localStorage.setItem(storageKey(id), JSON.stringify(sessions.value));
	}

	function setActive(ctx: Omit<ArtifactEditContext, "sessionId" | "status" | "messages" | "createdAt" | "updatedAt"> & Partial<Pick<ArtifactEditContext, "sessionId" | "status" | "messages" | "createdAt" | "updatedAt">>) {
		const now = Date.now();
		const next: ArtifactEditContext = {
			sessionId: ctx.sessionId || makeSessionId(ctx.targetType),
			taskId: ctx.taskId,
			targetType: ctx.targetType,
			targetPath: ctx.targetPath,
			targetLabel: ctx.targetLabel,
			sectionTitle: ctx.sectionTitle,
			excerpt: ctx.excerpt,
			previewUrl: ctx.previewUrl,
			description: ctx.description,
			status: ctx.status || "active",
			messages: ctx.messages || [],
			createdAt: ctx.createdAt || now,
			updatedAt: now,
		};
		const idx = sessions.value.findIndex((s) => s.sessionId === next.sessionId);
		if (idx >= 0) sessions.value[idx] = next;
		else sessions.value.unshift(next);
		activeContext.value = next;
		persist(next.taskId);
		return next;
	}

	function reactivate(sessionId: string) {
		const session = sessions.value.find((s) => s.sessionId === sessionId);
		if (!session) return null;
		activeContext.value = session;
		return session;
	}

	function updateSession(sessionId: string, patch: Partial<ArtifactEditContext>) {
		const idx = sessions.value.findIndex((s) => s.sessionId === sessionId);
		if (idx < 0) return;
		const next = { ...sessions.value[idx], ...patch, updatedAt: Date.now() };
		sessions.value[idx] = next;
		if (activeContext.value?.sessionId === sessionId) activeContext.value = next;
		persist(next.taskId);
	}

	function appendSessionMessage(sessionId: string, role: "user" | "assistant", content: string) {
		const session = sessions.value.find((s) => s.sessionId === sessionId);
		if (!session) return;
		updateSession(sessionId, {
			messages: [...session.messages, { role, content }],
		});
	}

	function clearActive() {
		activeContext.value = null;
	}

	return {
		activeContext,
		sessions,
		hasActive,
		restore,
		persist,
		setActive,
		reactivate,
		updateSession,
		appendSessionMessage,
		clearActive,
	};
});
