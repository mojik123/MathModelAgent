<script setup lang="ts">
import {
	type TaskHistoryItem,
	deleteTaskHistory,
	getTaskHistory,
} from "@/apis/commonApi";
import { Button } from "@/components/ui/button";
import {
	Sidebar,
	SidebarContent,
	SidebarGroup,
	SidebarGroupContent,
	SidebarGroupLabel,
	SidebarHeader,
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
	type SidebarProps,
	SidebarRail,
} from "@/components/ui/sidebar";
import {
	CheckCircle2,
	Clock3,
	PlayCircle,
	RefreshCw,
	Trash2,
	XCircle,
} from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";

const props = defineProps<SidebarProps>();

const route = useRoute();
const router = useRouter();
const historyTasks = ref<TaskHistoryItem[]>([]);
const loadingHistory = ref(false);
const deletingTaskId = ref<string | null>(null);

const currentTaskId = computed(() =>
	typeof route.params.task_id === "string" ? route.params.task_id : "",
);

const statusLabel: Record<TaskHistoryItem["status"], string> = {
	ready: "待启动",
	running: "运行中",
	completed: "已完成",
	failed: "失败",
	stopped: "已停止",
	interrupted: "未完成",
};

const statusClass: Record<TaskHistoryItem["status"], string> = {
	ready: "text-slate-500",
	running: "text-blue-600",
	completed: "text-green-600",
	failed: "text-red-600",
	stopped: "text-amber-600",
	interrupted: "text-slate-500",
};

const statusIcon = (status: TaskHistoryItem["status"]) => {
	if (status === "running") return PlayCircle;
	if (status === "completed") return CheckCircle2;
	if (status === "failed") return XCircle;
	return Clock3;
};

const formatTime = (value?: string | null) => {
	if (!value) return "";
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return "";
	return date.toLocaleString("zh-CN", {
		month: "2-digit",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
	});
};

async function loadHistory() {
	loadingHistory.value = true;
	try {
		const res = await getTaskHistory();
		historyTasks.value = res.data;
	} catch (error) {
		console.error("读取历史任务失败:", error);
	} finally {
		loadingHistory.value = false;
	}
}

async function deleteHistoryTask(task: TaskHistoryItem) {
	const confirmed = window.confirm(
		`确定删除历史任务“${task.title}”吗？生成文件也会一起删除。`,
	);
	if (!confirmed) return;

	deletingTaskId.value = task.task_id;
	try {
		await deleteTaskHistory(task.task_id);
		historyTasks.value = historyTasks.value.filter(
			(item) => item.task_id !== task.task_id,
		);
		if (currentTaskId.value === task.task_id) {
			void router.push("/chat");
		}
	} catch (error) {
		console.error("删除历史任务失败:", error);
	} finally {
		deletingTaskId.value = null;
	}
}

onMounted(() => {
	void loadHistory();
});
</script>

<template>
  <Sidebar v-bind="props">
    <SidebarHeader>
      <div class="flex items-center gap-2 h-15">
        <router-link to="/chat" class="flex items-center gap-2">
          <img src="@/assets/icon.png" alt="logo" class="w-10 h-10">
          <div class="text-lg font-bold">MathModelAgent</div>
        </router-link>
      </div>
    </SidebarHeader>

    <SidebarContent>
      <SidebarGroup>
        <SidebarGroupLabel>开始</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton as-child :is-active="route.path === '/chat'">
                <RouterLink to="/chat">开始新任务</RouterLink>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>

      <SidebarGroup>
        <div class="flex items-center justify-between pr-2">
          <SidebarGroupLabel>历史建模</SidebarGroupLabel>
          <Button variant="ghost" size="icon" class="h-7 w-7" :disabled="loadingHistory" @click="loadHistory">
            <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': loadingHistory }" />
          </Button>
        </div>
        <SidebarGroupContent>
          <SidebarMenu>
            <SidebarMenuItem v-if="!loadingHistory && historyTasks.length === 0">
              <div class="px-2 py-2 text-xs text-slate-500">暂无历史建模</div>
            </SidebarMenuItem>

            <SidebarMenuItem v-for="task in historyTasks" :key="task.task_id">
              <div class="group/history relative rounded-md">
                <SidebarMenuButton as-child :is-active="currentTaskId === task.task_id" class="h-auto py-2 pr-9">
                  <RouterLink :to="`/task/${task.task_id}`" class="min-w-0">
                    <div class="min-w-0 space-y-1">
                      <div class="truncate text-sm font-medium">{{ task.title }}</div>
                      <div class="flex min-w-0 items-center gap-2 text-[11px]">
                        <component :is="statusIcon(task.status)" class="h-3 w-3 shrink-0" :class="statusClass[task.status]" />
                        <span :class="statusClass[task.status]">{{ statusLabel[task.status] }}</span>
                        <span class="truncate text-slate-400">{{ formatTime(task.updated_at || task.created_at) }}</span>
                      </div>
                    </div>
                  </RouterLink>
                </SidebarMenuButton>

                <button
                  type="button"
                  class="absolute right-1 top-2 hidden rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600 group-hover/history:block"
                  :disabled="deletingTaskId === task.task_id"
                  @click.stop.prevent="deleteHistoryTask(task)"
                  title="删除历史任务"
                >
                  <RefreshCw v-if="deletingTaskId === task.task_id" class="h-3.5 w-3.5 animate-spin" />
                  <Trash2 v-else class="h-3.5 w-3.5" />
                </button>
              </div>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>

    <SidebarRail />
  </Sidebar>
</template>
