<script setup lang="ts">
import {
  getModelRegistry,
  getTaskModelConfig,
  NO_REASONING_OPTION,
  saveTaskModelConfig,
} from "@/apis/workflowApi";
import type { ModelRegistryEntry, TaskModelConfig } from "@/apis/workflowApi";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RefreshCw } from "lucide-vue-next";
import { computed, ref, watch } from "vue";

const props = defineProps<{
  taskId: string;
  taskKey: string;
}>();

const models = ref<ModelRegistryEntry[]>([]);
const selectedModel = ref("");
const selectedReasoning = ref("");
const configExists = ref(false);
const savedConfig = ref<Pick<TaskModelConfig, "model" | "reasoning"> | null>(null);
const lastSavedAt = ref<string | null>(null);
const loadState = ref<"loading" | "ready" | "error">("loading");
const loadError = ref("");
const saveError = ref("");
const isSaving = ref(false);
const saveSucceeded = ref(false);
let loadSequence = 0;
const DEFAULT_MODEL_ID = "gpt-6-luna";
const DEFAULT_REASONING = "max";

const selectedModelEntry = computed(
  () => models.value.find((model) => model.id === selectedModel.value) ?? null,
);
const availableReasoningOptions = computed(() => {
  const options = selectedModelEntry.value?.reasoning_options ?? [];
  return options.length > 0 ? options : [NO_REASONING_OPTION];
});
const hasUnsavedChanges = computed(() => {
  if (!savedConfig.value) return !configExists.value;
  return (
    savedConfig.value.model !== selectedModel.value ||
    savedConfig.value.reasoning !== selectedReasoning.value
  );
});
const canSave = computed(
  () =>
    loadState.value === "ready" &&
    !isSaving.value &&
    Boolean(selectedModel.value) &&
    Boolean(selectedReasoning.value) &&
    (hasUnsavedChanges.value || !configExists.value),
);
const saveStatusText = computed(() => {
  if (loadState.value === "loading") return "正在读取本任务配置…";
  if (loadState.value === "error") return "配置读取失败";
  if (isSaving.value) return "正在保存…";
  if (saveError.value) return "保存失败";
  if (hasUnsavedChanges.value) return configExists.value ? "有未保存更改" : "默认值，尚未保存";
  return configExists.value ? "已保存" : "尚未保存";
});
const lastSavedText = computed(() => {
  if (lastSavedAt.value) {
    const formatted = new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(lastSavedAt.value));
    return `本机上次成功保存：${formatted}`;
  }
  if (configExists.value) return "服务器已有配置，本机未记录保存时间";
  return "本任务尚未保存模型设置";
});

function defaultReasoning(model: ModelRegistryEntry) {
  if (model.reasoning_options.includes(DEFAULT_REASONING)) return DEFAULT_REASONING;
  if (model.reasoning_options.includes("medium")) return "medium";
  return model.reasoning_options[0] ?? NO_REASONING_OPTION;
}

function defaultModel() {
  return models.value.find((model) => model.id === DEFAULT_MODEL_ID) ?? models.value[0];
}

function storageKey() {
  return `workflow-model-config-saved-at:${encodeURIComponent(props.taskId)}:${encodeURIComponent(props.taskKey)}`;
}

function readSavedTime() {
  if (typeof window === "undefined") return null;
  try {
    const value = window.localStorage.getItem(storageKey());
    return value && !Number.isNaN(Date.parse(value)) ? new Date(value).toISOString() : null;
  } catch {
    return null;
  }
}

function storeSavedTime(value: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey(), value);
  } catch {
    // The server config remains authoritative if browser storage is unavailable.
  }
}

async function loadSettings() {
  const sequence = ++loadSequence;
  models.value = [];
  selectedModel.value = "";
  selectedReasoning.value = "";
  savedConfig.value = null;
  configExists.value = false;
  lastSavedAt.value = null;
  saveError.value = "";
  saveSucceeded.value = false;
  loadError.value = "";
  loadState.value = "loading";

  try {
    const registryResponse = await getModelRegistry();
    if (sequence !== loadSequence) return;
    if (!Array.isArray(registryResponse.data)) throw new Error("模型列表格式无效");
    models.value = registryResponse.data;

    let persistedConfig: TaskModelConfig | null = null;
    try {
      const configResponse = await getTaskModelConfig(props.taskId, props.taskKey);
      if (sequence !== loadSequence) return;
      persistedConfig = configResponse.data;
    } catch (error) {
      if ((error as { response?: { status?: number } })?.response?.status !== 404) {
        throw error;
      }
    }

    if (persistedConfig) {
      configExists.value = true;
      savedConfig.value = {
        model: persistedConfig.model,
        reasoning: persistedConfig.reasoning,
      };
      const configuredModel = models.value.find((model) => model.id === persistedConfig?.model);
      if (configuredModel) {
        selectedModel.value = configuredModel.id;
        selectedReasoning.value = configuredModel.reasoning_options.includes(
          persistedConfig.reasoning,
        ) || (configuredModel.reasoning_options.length === 0 && persistedConfig.reasoning === "none")
          ? persistedConfig.reasoning
          : defaultReasoning(configuredModel);
      }
      lastSavedAt.value = readSavedTime();
    } else if (models.value.length > 0) {
      const configuredDefault = defaultModel();
      selectedModel.value = configuredDefault.id;
      selectedReasoning.value = defaultReasoning(configuredDefault);
    }

    loadState.value = "ready";
  } catch {
    if (sequence !== loadSequence) return;
    loadError.value = "无法读取模型列表或本任务配置，请重试。";
    loadState.value = "error";
  }
}

async function saveSettings() {
  if (!canSave.value) return;
  isSaving.value = true;
  saveError.value = "";
  saveSucceeded.value = false;
  const payload: TaskModelConfig = {
    task_id: props.taskId,
    task_key: props.taskKey,
    model: selectedModel.value,
    reasoning: selectedReasoning.value,
  };

  try {
    const response = await saveTaskModelConfig(payload);
    const saved = response.data ?? payload;
    configExists.value = true;
    savedConfig.value = { model: saved.model, reasoning: saved.reasoning };
    lastSavedAt.value = new Date().toISOString();
    storeSavedTime(lastSavedAt.value);
    saveSucceeded.value = true;
  } catch {
    saveError.value = "保存失败，请检查连接后重试。当前选择尚未确认已保存。";
  } finally {
    isSaving.value = false;
  }
}

watch(selectedModel, (modelId) => {
  const model = models.value.find((entry) => entry.id === modelId);
  if (!model) {
    selectedReasoning.value = "";
    return;
  }
  if (!model.reasoning_options.includes(selectedReasoning.value)) {
    selectedReasoning.value = defaultReasoning(model);
  }
});

watch(
  () => [props.taskId, props.taskKey],
  () => void loadSettings(),
  { immediate: true },
);
</script>

<template>
  <aside aria-labelledby="model-selector-title" class="flex min-h-0 min-w-0 flex-col bg-white">
    <header class="border-b border-slate-200 px-4 py-4">
      <h3 id="model-selector-title" class="text-sm font-semibold text-slate-900">当前阶段模型</h3>
      <p class="mt-1 text-xs leading-5 text-slate-500">设置只应用于当前阶段，执行使用本机 Codex 登录</p>
    </header>

    <div class="min-h-0 flex-1 overflow-y-auto px-4 py-4">
      <div v-if="loadState === 'loading'" role="status" class="flex items-center gap-2 text-sm text-slate-500">
        <RefreshCw class="h-4 w-4 animate-spin" aria-hidden="true" />
        正在读取模型配置…
      </div>

      <div v-else-if="loadState === 'error'" class="space-y-3">
        <p role="alert" class="text-sm leading-5 text-red-700">{{ loadError }}</p>
        <Button variant="outline" size="sm" @click="loadSettings">重试</Button>
      </div>

      <div v-else-if="models.length === 0" class="rounded-lg border border-dashed border-slate-300 px-3 py-4">
        <p class="text-sm font-medium text-slate-700">没有可用模型</p>
        <p class="mt-1 text-xs leading-5 text-slate-500">请先安装并登录本机 Codex CLI。</p>
      </div>

      <div v-else class="space-y-5">
        <div class="space-y-2">
          <label class="text-xs font-medium text-slate-700" for="task-model-select">模型</label>
          <Select v-model="selectedModel">
            <SelectTrigger id="task-model-select" aria-label="模型" class="w-full">
              <SelectValue placeholder="选择已配置模型" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>已配置模型</SelectLabel>
                <SelectItem v-for="model in models" :key="model.id" :value="model.id">
                  {{ model.label }} <span class="text-xs text-slate-400">({{ model.provider }})</span>
                </SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <p v-if="configExists && savedConfig && !models.some((model) => model.id === savedConfig?.model)" class="text-xs leading-5 text-amber-700">
            已保存的模型当前不可用；选择可用模型后再手动保存。
          </p>
        </div>

        <div class="space-y-2">
          <label class="text-xs font-medium text-slate-700" for="task-reasoning-select">推理强度</label>
          <Select v-model="selectedReasoning" :disabled="!selectedModelEntry">
            <SelectTrigger id="task-reasoning-select" aria-label="推理强度" class="w-full">
              <SelectValue placeholder="选择推理强度" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>推理强度</SelectLabel>
                <SelectItem
                  v-for="option in availableReasoningOptions"
                  :key="option"
                  :value="option"
                >
                  {{ option === NO_REASONING_OPTION ? "不指定" : option }}
                </SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>

        <section class="border-t border-slate-200 pt-4" aria-label="保存状态">
          <div class="flex items-center justify-between gap-3">
            <span class="text-xs font-medium text-slate-600">保存状态</span>
            <span
              role="status"
              class="text-xs font-medium"
              :class="saveError ? 'text-red-700' : saveSucceeded ? 'text-emerald-700' : 'text-slate-600'"
            >
              {{ saveStatusText }}
            </span>
          </div>
          <p class="mt-2 text-xs leading-5 text-slate-500">{{ lastSavedText }}</p>
          <p v-if="saveError" role="alert" class="mt-2 text-xs leading-5 text-red-700">
            {{ saveError }}
          </p>
          <Button
            class="mt-4 w-full"
            size="sm"
            :disabled="!canSave"
            @click="saveSettings"
          >
            {{ isSaving ? "正在保存…" : "保存本任务设置" }}
          </Button>
        </section>
      </div>
    </div>
  </aside>
</template>
