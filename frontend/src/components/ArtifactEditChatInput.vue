<script setup lang="ts">
import { sendArtifactEditMessage } from "@/apis/filesApi";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useArtifactEditStore } from "@/stores/artifactEdit";
import { useTaskStore } from "@/stores/task";
import { AgentType } from "@/utils/enum";
import { FileText, ImageIcon, RefreshCw, Send, X } from "lucide-vue-next";
import { computed, ref } from "vue";

const emit = defineEmits<{
	updated: [type: "image" | "text"];
}>();

const artifactEditStore = useArtifactEditStore();
const taskStore = useTaskStore();
const input = ref("");
const sending = ref(false);

const active = computed(() => artifactEditStore.activeContext);

function targetTypeLabel() {
	return active.value?.targetType === "image" ? "图片" : "文字";
}

function targetIcon() {
	return active.value?.targetType === "image" ? ImageIcon : FileText;
}

async function send() {
	const ctx = active.value;
	const instruction = input.value.trim();
	if (!ctx || !instruction || sending.value) return;

	input.value = "";
	sending.value = true;
	artifactEditStore.updateSession(ctx.sessionId, { status: "running" });
	artifactEditStore.appendSessionMessage(ctx.sessionId, "user", instruction);
	taskStore.addUserAction(
		"修改",
		`${targetTypeLabel()} ${ctx.targetLabel}`,
		`用户请求修改${targetTypeLabel()} ${ctx.targetLabel}：${instruction}`,
		{
			from: "User",
			to: ctx.targetType === "image" ? "CoderAgent" : "WriterAgent",
			label: ctx.targetType === "image" ? "请求图片修改" : "请求文字修改",
		},
	);
	taskStore.addSystemAction(
		"接收",
		`${targetTypeLabel()}修改请求`,
		`已接收${targetTypeLabel()}修改请求：${ctx.targetLabel}`,
		{
			from: "User",
			to: ctx.targetType === "image" ? "CoderAgent" : "WriterAgent",
			label: "进入修改流程",
		},
		"info",
	);

	try {
		const response = await sendArtifactEditMessage({
			task_id: ctx.taskId,
			target_type: ctx.targetType,
			target_path: ctx.targetPath,
			target_label: ctx.targetLabel,
			instruction,
			description: ctx.description,
			selected_text: ctx.excerpt || ctx.targetLabel,
			context: ctx.description || ctx.excerpt,
			conversation_history: ctx.messages,
		});
		const data = response.data as any;
		const ok = Boolean(data?.success) && data?.status !== "failed";
		const resultText =
			ctx.targetType === "image"
				? [
						data?.analysis_text,
						data?.message,
						data?.updated_alt_text ? `新标题：${data.updated_alt_text}` : "",
						data?.updated_caption ? `新说明：${data.updated_caption}` : "",
					]
						.filter(Boolean)
						.join("\n")
				: [data?.message, data?.revised_text ? `修改后：${data.revised_text}` : ""]
						.filter(Boolean)
						.join("\n");

		artifactEditStore.appendSessionMessage(
			ctx.sessionId,
			"assistant",
			resultText || (ok ? "修改完成" : "修改失败"),
		);
		artifactEditStore.updateSession(ctx.sessionId, {
			status: ok ? "done" : "failed",
		});

		if (ok) {
			taskStore.addAgentAction(
				ctx.targetType === "image" ? AgentType.CODER : AgentType.WRITER,
				ctx.targetType === "image" ? "返回" : "返回",
				`${targetTypeLabel()}修改结果`,
				resultText || `${targetTypeLabel()}修改完成：${ctx.targetLabel}`,
				{
					from: ctx.targetType === "image" ? "CoderAgent" : "WriterAgent",
					to: "User",
					label: ctx.targetType === "image" ? "返回图片修改结果" : "返回文字修改结果",
				},
			);
			emit("updated", ctx.targetType);
		} else {
			taskStore.addSystemAction(
				"失败",
				`${targetTypeLabel()}修改`,
				resultText || `${targetTypeLabel()}修改失败：${ctx.targetLabel}`,
				{
					from: ctx.targetType === "image" ? "CoderAgent" : "WriterAgent",
					to: "User",
					label: "返回失败原因",
				},
				"error",
			);
		}
	} catch (error) {
		const message = error instanceof Error ? error.message : "网络错误";
		artifactEditStore.appendSessionMessage(ctx.sessionId, "assistant", `修改失败：${message}`);
		artifactEditStore.updateSession(ctx.sessionId, { status: "failed" });
		taskStore.addSystemAction(
			"失败",
			`${targetTypeLabel()}修改`,
			`修改失败：${message}`,
			{
				from: ctx.targetType === "image" ? "CoderAgent" : "WriterAgent",
				to: "User",
				label: "返回失败原因",
			},
			"error",
		);
	} finally {
		sending.value = false;
	}
}
</script>

<template>
	<div v-if="active" class="border-t border-slate-200 bg-white/85 p-3 backdrop-blur">
		<div class="mb-2 flex items-start justify-between gap-3 rounded-2xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">
			<div class="flex min-w-0 items-start gap-2">
				<component :is="targetIcon()" class="mt-0.5 h-4 w-4 shrink-0" />
				<div class="min-w-0">
					<div class="font-semibold">当前修改对象：{{ active.targetLabel }}</div>
					<div class="mt-0.5 truncate opacity-80">{{ targetTypeLabel() }} · {{ active.targetPath }}</div>
					<div v-if="active.excerpt" class="mt-1 line-clamp-2 text-blue-700/75">{{ active.excerpt }}</div>
				</div>
			</div>
			<Button variant="ghost" size="icon" class="h-7 w-7 shrink-0 text-blue-700" @click="artifactEditStore.clearActive()">
				<X class="h-4 w-4" />
			</Button>
		</div>
		<div class="flex gap-2">
			<Textarea
				v-model="input"
				rows="2"
				class="min-h-[58px] flex-1 resize-none text-sm"
				:disabled="sending"
				:placeholder="active.targetType === 'image' ? '直接输入修图要求，例如：把标题改短、调大坐标轴字体、改配色...' : '直接输入文字修改要求，例如：压缩成两句话、改得更学术、去掉口语化...'"
				@keydown.enter.exact.prevent="send"
			/>
			<Button class="self-end" :disabled="sending || !input.trim()" @click="send">
				<RefreshCw v-if="sending" class="mr-1 h-4 w-4 animate-spin" />
				<Send v-else class="mr-1 h-4 w-4" />
				{{ sending ? "修改中" : "发送" }}
			</Button>
		</div>
	</div>
</template>
