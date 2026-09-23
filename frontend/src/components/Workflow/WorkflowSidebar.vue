<script setup lang="ts">
import type { StageStatus, WorkflowStage } from "@/workflow/types";

defineProps<{
  stages: WorkflowStage[];
  activeStageId: string;
}>();

const emit = defineEmits<{
  (event: "select", stageId: string): void;
}>();

const statusLabels: Record<StageStatus, string> = {
  LOCKED: "未解锁",
  READY: "就绪",
  RUNNING: "进行中",
  PASS: "已完成",
  FAIL: "失败",
  BLOCKED: "受阻",
};

const statusDotClasses: Record<StageStatus, string> = {
  LOCKED: "bg-slate-300",
  READY: "bg-blue-600",
  RUNNING: "bg-amber-500 motion-safe:animate-pulse",
  PASS: "bg-emerald-500",
  FAIL: "bg-red-500",
  BLOCKED: "bg-violet-500",
};

const statusTextClasses: Record<StageStatus, string> = {
  LOCKED: "text-slate-400",
  READY: "text-blue-700",
  RUNNING: "text-amber-700",
  PASS: "text-emerald-700",
  FAIL: "text-red-700",
  BLOCKED: "text-violet-700",
};
</script>

<template>
  <aside class="flex h-full min-h-0 flex-col bg-white/65">
    <header class="border-b border-slate-200/80 px-5 py-4">
      <h2 class="text-sm font-semibold text-slate-900">工作阶段</h2>
      <p class="mt-1 text-xs text-slate-500">按顺序推进，每步都有验收标准</p>
    </header>

    <nav aria-label="工作阶段列表" class="min-h-0 flex-1 overflow-y-auto px-3 py-3">
      <ol class="space-y-1.5">
        <li v-for="stage in stages" :key="stage.id">
          <button
            type="button"
            :data-stage-id="stage.id"
            :aria-current="stage.id === activeStageId ? 'step' : undefined"
            :aria-label="`${stage.title}，${statusLabels[stage.status]}`"
            class="grid w-full grid-cols-[2.25rem_minmax(0,1fr)] items-start gap-2 rounded-lg border border-transparent px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2"
            :class="stage.id === activeStageId ? 'border-blue-200 bg-blue-50' : 'hover:border-slate-200 hover:bg-slate-50'"
            @click="emit('select', stage.id)"
          >
            <span
              class="pt-0.5 font-mono text-xs font-medium tabular-nums"
              :class="stage.id === activeStageId ? 'text-blue-700' : 'text-slate-400'"
              aria-hidden="true"
            >
              {{ String(stage.index).padStart(2, "0") }}
            </span>
            <span class="min-w-0">
              <span class="block truncate text-sm font-medium text-slate-800">
                {{ stage.title }}
              </span>
              <span class="mt-1 flex min-w-0 items-center gap-1.5 text-[11px] leading-4">
                <span
                  class="h-1.5 w-1.5 shrink-0 rounded-full"
                  :class="statusDotClasses[stage.status]"
                  aria-hidden="true"
                />
                <span class="shrink-0" :class="statusTextClasses[stage.status]">
                  {{ statusLabels[stage.status] }}
                </span>
                <span class="truncate text-slate-500">{{ stage.summary }}</span>
              </span>
            </span>
          </button>
        </li>
      </ol>
    </nav>
  </aside>
</template>
