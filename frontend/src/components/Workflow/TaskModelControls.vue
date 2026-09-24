<script setup lang="ts">
import {
	NO_REASONING_OPTION,
	getModelRegistry,
	getTaskModelConfig,
	saveTaskModelConfig,
} from "@/apis/workflowApi";
import type { ModelRegistryEntry } from "@/apis/workflowApi";
import { computed, ref, watch } from "vue";

const props = defineProps<{ taskId: string; taskKey: string }>();

let registryPromise: ReturnType<typeof getModelRegistry> | null = null;
function loadRegistry() {
	if (!registryPromise) {
		registryPromise = getModelRegistry().catch((error) => {
			registryPromise = null;
			throw error;
		});
	}
	return registryPromise;
}

const models = ref<ModelRegistryEntry[]>([]);
const selectedModel = ref("");
const selectedReasoning = ref("");
const loading = ref(false);
const saving = ref(false);
const readyForSave = ref(false);
const saveStatus = ref<"idle" | "saved" | "unsaved" | "error" | "unavailable">("idle");
let saveQueued = false;

const currentModel = computed(() => models.value.find((model) => model.id === selectedModel.value));
const reasoningOptions = computed(() => currentModel.value?.reasoning_options ?? []);

function defaultReasoning(model: ModelRegistryEntry | undefined) {
	if (!model || model.reasoning_options.length === 0) return NO_REASONING_OPTION;
	return model.reasoning_options.includes("max") ? "max" : model.reasoning_options[0];
}

function setFallbackSelection() {
	const fallback = models.value.find((model) => model.id === "gpt-6-luna") ?? models.value[0];
	selectedModel.value = fallback?.id ?? "";
	selectedReasoning.value = defaultReasoning(fallback);
}

async function loadTaskConfig(taskId: string) {
	loading.value = true;
	readyForSave.value = false;
	saveStatus.value = "idle";
	try {
		const [registryResponse, configResponse] = await Promise.all([
			loadRegistry(),
			getTaskModelConfig(taskId, props.taskKey),
		]);
		models.value = registryResponse.data ?? [];
		setFallbackSelection();
		const saved = configResponse.data;
		const savedModel = models.value.find((model) => model.id === saved.model);
		if (savedModel) {
			selectedModel.value = savedModel.id;
			selectedReasoning.value = savedModel.reasoning_options.includes(saved.reasoning)
				|| (savedModel.reasoning_options.length === 0 && saved.reasoning === NO_REASONING_OPTION)
				? saved.reasoning
				: defaultReasoning(savedModel);
		}
		saveStatus.value = "saved";
	} catch (error: unknown) {
		const status = (error as { response?: { status?: number } })?.response?.status;
		try {
			if (!models.value.length) models.value = (await loadRegistry()).data ?? [];
		} catch {
			saveStatus.value = "unavailable";
			return;
		}
		setFallbackSelection();
		saveStatus.value = status === 404 ? "unsaved" : "error";
	} finally {
		loading.value = false;
		readyForSave.value = true;
	}
}

async function persistSelection() {
	if (!readyForSave.value || !selectedModel.value) return;
	if (saving.value) {
		saveQueued = true;
		return;
	}
	saving.value = true;
	saveStatus.value = "idle";
	const payload = {
		task_id: props.taskId,
		task_key: props.taskKey,
		model: selectedModel.value,
		reasoning: selectedReasoning.value || NO_REASONING_OPTION,
	};
	try {
		await saveTaskModelConfig(payload);
		saveStatus.value = "saved";
	} catch {
		saveStatus.value = "error";
	} finally {
		saving.value = false;
		if (saveQueued) {
			saveQueued = false;
			void persistSelection();
		}
	}
}

function handleModelChange() {
	const model = currentModel.value;
	if (model && !model.reasoning_options.includes(selectedReasoning.value)) {
		selectedReasoning.value = defaultReasoning(model);
	}
	void persistSelection();
}

function handleReasoningChange() {
	void persistSelection();
}

watch(() => [props.taskId, props.taskKey], ([taskId, taskKey]) => {
	if (taskId && taskKey) void loadTaskConfig(taskId);
}, { immediate: true });
</script>

<template>
  <div class="px-2 pb-2" @click.stop>
    <div v-if="loading" class="h-7 rounded-md bg-slate-100 px-2 py-1.5 text-[10px] text-slate-400">读取模型设置…</div>
    <div v-else-if="saveStatus === 'unavailable'" class="rounded-md bg-amber-50 px-2 py-1.5 text-[10px] leading-4 text-amber-700">Codex CLI 不可用</div>
    <div v-else class="grid grid-cols-2 gap-1.5">
      <select
        v-model="selectedModel"
        aria-label="任务模型"
        class="min-w-0 h-7 rounded-md border border-slate-200 bg-white px-1.5 text-[10px] text-slate-700 outline-none transition focus:border-blue-400 focus:ring-1 focus:ring-blue-200"
        :disabled="!models.length || saving"
        @change="handleModelChange"
      >
        <option v-for="model in models" :key="model.id" :value="model.id">{{ model.label }}</option>
      </select>
      <select
        v-model="selectedReasoning"
        aria-label="任务思考强度"
        class="min-w-0 h-7 rounded-md border border-slate-200 bg-white px-1.5 text-[10px] text-slate-700 outline-none transition focus:border-blue-400 focus:ring-1 focus:ring-blue-200"
        :disabled="!models.length || saving"
        @change="handleReasoningChange"
      >
        <option v-if="reasoningOptions.length === 0" :value="NO_REASONING_OPTION">不指定</option>
        <option v-for="reasoning in reasoningOptions" :key="reasoning" :value="reasoning">{{ reasoning }}</option>
      </select>
    </div>
    <div class="mt-1 flex items-center justify-between gap-1 text-[9px] leading-3 text-slate-400">
      <span>模型 · 思考</span>
      <span v-if="saving">保存中…</span>
      <span v-else-if="saveStatus === 'saved'">已保存</span>
      <span v-else-if="saveStatus === 'unsaved'">未保存</span>
      <span v-else-if="saveStatus === 'error'" class="text-red-500">保存失败</span>
    </div>
  </div>
</template>
