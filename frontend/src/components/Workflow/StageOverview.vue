<script setup lang="ts">
import type { StageStatus, WorkflowStage } from "@/workflow/types";

const props = defineProps<{
  stage: WorkflowStage;
  runState?: "idle" | "running" | "stopping" | "completed" | "failed" | "cancelled";
  runMessage?: string;
}>();

const emit = defineEmits<{ run: [] }>();

const statusLabels: Record<StageStatus, string> = {
  LOCKED: "未解锁",
  READY: "就绪",
  RUNNING: "进行中",
  PASS: "已完成",
  FAIL: "失败",
  BLOCKED: "受阻",
};

const statusClasses: Record<StageStatus, string> = {
  LOCKED: "bg-slate-100 text-slate-600",
  READY: "bg-blue-50 text-blue-700",
  RUNNING: "bg-amber-50 text-amber-700",
  PASS: "bg-emerald-50 text-emerald-700",
  FAIL: "bg-red-50 text-red-700",
  BLOCKED: "bg-violet-50 text-violet-700",
};
</script>

<template>
  <section aria-labelledby="stage-overview-title" class="shrink-0 border-b border-slate-200 bg-white">
    <header class="flex items-start justify-between gap-4 px-5 py-4">
      <div class="min-w-0">
        <p class="font-mono text-xs tabular-nums text-slate-400">
          阶段 {{ String(stage.index).padStart(2, "0") }}
        </p>
        <h2 id="stage-overview-title" class="mt-1 truncate text-lg font-semibold text-slate-900">
          {{ stage.title }}
        </h2>
        <p class="mt-1 text-sm leading-5 text-slate-600">{{ stage.summary }}</p>
      </div>
      <span
        role="status"
        class="shrink-0 rounded-full px-2.5 py-1 text-xs font-medium"
        :class="statusClasses[stage.status]"
      >
        {{ statusLabels[stage.status] }}
      </span>
    </header>

    <div class="flex items-center gap-3 border-t border-slate-100 px-5 py-3">
      <button
        type="button"
        class="inline-flex h-8 items-center rounded-md bg-blue-600 px-3 text-xs font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="stage.status === 'LOCKED' || stage.status === 'RUNNING' || props.runState === 'running' || props.runState === 'stopping'"
        @click="emit('run')"
      >
        {{ props.runState === "running" || props.runState === "stopping" ? "执行中…" : "运行当前阶段" }}
      </button>
      <span v-if="props.runMessage" role="status" class="min-w-0 truncate text-xs" :class="props.runState === 'failed' ? 'text-red-700' : 'text-slate-500'">
        {{ props.runMessage }}
      </span>
    </div>

    <div class="grid gap-x-6 gap-y-4 border-t border-slate-100 px-5 py-4 sm:grid-cols-2">
      <section aria-labelledby="stage-inputs-title">
        <h3 id="stage-inputs-title" class="text-xs font-semibold text-slate-700">输入</h3>
        <ul class="mt-2 space-y-1.5 text-xs leading-5 text-slate-600">
          <li v-for="input in stage.inputs" :key="input">{{ input }}</li>
        </ul>
      </section>

      <section aria-labelledby="stage-outputs-title">
        <h3 id="stage-outputs-title" class="text-xs font-semibold text-slate-700">预期产物</h3>
        <ul class="mt-2 space-y-1.5 text-xs leading-5 text-slate-600">
          <li v-for="output in stage.outputs" :key="output" class="break-words">{{ output }}</li>
        </ul>
      </section>

      <section aria-labelledby="stage-acceptance-title" class="sm:col-span-2">
        <h3 id="stage-acceptance-title" class="text-xs font-semibold text-slate-700">验收条件</h3>
        <ul class="mt-2 grid gap-x-6 gap-y-1.5 text-xs leading-5 text-slate-600 sm:grid-cols-2">
          <li v-for="criterion in stage.acceptance" :key="criterion" class="flex gap-2">
            <span class="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-slate-400" aria-hidden="true" />
            <span>{{ criterion }}</span>
          </li>
        </ul>
      </section>
    </div>
  </section>
</template>
