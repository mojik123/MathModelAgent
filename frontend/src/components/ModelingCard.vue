<script setup lang="ts">
import { ChevronDown, MessageCircle, Send, Sparkles } from "lucide-vue-next";
import { computed, nextTick, ref, watch } from "vue";

// ---- Props ----

interface ModelOption {
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

interface ChatMessage {
	role: "user" | "assistant";
	content: string;
}

interface Props {
	questionIndex: number;
	questionTitle: string;
	questionText: string;
	presetOptions: ModelOption[];
	isExpanded: boolean;
	disabled?: boolean;
	selectedOptionId?: string;
	customInput?: string;
	chatHistory?: ChatMessage[];
	genStatus?: { status: string; text: string };
}

const props = withDefaults(defineProps<Props>(), {
	selectedOptionId: "",
	customInput: "",
	chatHistory: () => [],
	genStatus: () => ({ status: "waiting", text: "等待生成..." }),
});

const emit = defineEmits<{
	"select-option": [optionId: string];
	"update:custom-input": [value: string];
	"send-message": [message: string];
	"toggle-expand": [];
}>();

// ---- State ----

const chatInput = ref("");
const chatScrollRef = ref<HTMLDivElement | null>(null);
const userScrolledUp = ref(false);

// ---- Computed ----

const isCustomSelected = computed(
	() => props.selectedOptionId === "__custom__",
);

// ---- Methods ----

function handleSend() {
	const msg = chatInput.value.trim();
	if (!msg) return;
	chatInput.value = "";
	emit("send-message", msg);
}

function isNearBottom(el: HTMLDivElement): boolean {
	return el.scrollHeight - el.scrollTop - el.clientHeight < 50;
}

function scrollChatToBottom(force = false) {
	nextTick(() => {
		const el = chatScrollRef.value;
		if (!el) return;
		if (force || !userScrolledUp.value || isNearBottom(el)) {
			el.scrollTop = el.scrollHeight;
		}
	});
}

function onChatScroll() {
	const el = chatScrollRef.value;
	if (!el) return;
	userScrolledUp.value = !isNearBottom(el);
}

watch(
	() => props.chatHistory.length,
	() => {
		if (props.isExpanded) {
			scrollChatToBottom();
		}
	},
);

watch(
	() => props.isExpanded,
	(expanded) => {
		if (expanded) scrollChatToBottom(true);
	},
);
</script>

<template>
	<div
		class="modeling-card rounded-2xl border transition-all duration-400"
		:class="{
			'card-expanded glass-card shadow-[0_8px_32px_rgba(59,130,246,0.12)] border-blue-300/50 bg-white/60 backdrop-blur-md':
				isExpanded && !disabled,
			'card-expanded-disabled border-slate-200/30 bg-slate-50/60 opacity-60 cursor-default':
				isExpanded && disabled,
			'card-stacked border-white/20 bg-white/30 backdrop-blur-sm cursor-pointer hover:-translate-y-0.5 hover:shadow-lg hover:border-blue-200/40':
				!isExpanded && !disabled,
			'card-stacked-disabled border-slate-200/30 bg-slate-100/30 cursor-not-allowed opacity-50':
				!isExpanded && disabled,
		}"
			@click="!isExpanded && !disabled && emit('toggle-expand')"
	>
		<!-- ====== 折叠态：仅标题 ====== -->
		<div v-if="!isExpanded" class="flex items-center gap-2 px-4 py-2.5">
			<span
				class="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[10px] font-semibold text-white shadow-sm"
			>
				{{ questionIndex }}
			</span>
			<div class="min-w-0 flex-1 truncate text-sm font-semibold text-slate-800">
				{{ questionTitle }}
			</div>
			<ChevronDown class="h-3.5 w-3.5 shrink-0 text-slate-400" />
		</div>

		<!-- ====== 展开态 ====== -->
		<div v-else class="flex flex-col">
			<!-- 标题栏 -->
			<div
				class="flex items-center gap-3 border-b border-white/10 px-4 py-3"
				@click="emit('toggle-expand')"
			>
				<span
					class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-semibold text-white"
				>
					{{ questionIndex }}
				</span>
				<div class="min-w-0 flex-1">
					<div class="text-sm font-semibold text-slate-900">
						第 {{ questionIndex }} 问 · {{ questionTitle }}
						<span v-if="disabled" class="text-[10px] text-slate-400 ml-1">（已锁定）</span>
					</div>
					<div class="mt-0.5 text-xs leading-relaxed text-slate-600">
						{{ questionText }}
					</div>
				</div>
				<ChevronDown class="h-4 w-4 shrink-0 rotate-180 text-slate-400" />
			</div>

			<!-- 预设选项 -->
			<div class="space-y-1.5 px-4 pt-3 max-h-64 overflow-y-auto">
				<div class="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-slate-500">
					<Sparkles class="h-3 w-3" />
					选择建模方案
				</div>
				<div
					v-if="presetOptions.length === 0"
					class="rounded-xl border px-3 py-2 text-xs leading-relaxed"
					:class="{
						'border-blue-200 bg-blue-50/50 text-blue-700': props.genStatus?.status === 'waiting' || props.genStatus?.status === 'searching',
						'border-purple-200 bg-purple-50/50 text-purple-700': props.genStatus?.status === 'generating',
						'border-amber-200 bg-amber-50/50 text-amber-700': props.genStatus?.status === 'retrying',
						'border-green-200 bg-green-50/50 text-green-700': props.genStatus?.status === 'done',
					}"
				>
					{{ props.genStatus?.text || "等待生成..." }}
				</div>
				<label
					v-for="option in presetOptions"
					:key="option.id"
					class="flex items-start gap-3 rounded-xl border px-3 py-2.5 transition-all duration-200 hover:border-blue-300 hover:bg-blue-50/40"
					:class="[
						disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
						selectedOptionId === option.id
							? 'border-blue-400 bg-blue-50/60 shadow-[0_0_0_1px_rgba(59,130,246,0.3)]'
							: 'border-slate-200 bg-white/50',
					]"
				>
					<input
						type="radio"
						:value="option.id"
						:checked="selectedOptionId === option.id"
						class="mt-0.5 h-3.5 w-3.5 accent-blue-600"
						:disabled="disabled"
						@change="!disabled && emit('select-option', option.id)"
					/>
					<div class="min-w-0">
						<div class="flex flex-wrap items-center gap-1.5 text-sm font-medium text-slate-800">
							<span>{{ option.label }}</span>
							<span
								v-if="option.isRecommended"
								class="rounded-full bg-amber-500 px-1.5 py-0.5 text-[9px] font-semibold text-white"
							>
								推荐
							</span>
							<span
								v-if="option.score != null"
								class="rounded-full bg-slate-100 px-1.5 py-0.5 text-[9px] font-medium text-slate-500"
							>
								{{ option.score }}分
							</span>
						</div>
						<div class="text-xs leading-relaxed text-slate-500">
							{{ option.description }}
						</div>
						<div
							v-if="option.reason"
							class="mt-1 text-[11px] leading-relaxed text-slate-600"
						>
							{{ option.reason }}
						</div>
					</div>
				</label>

				<!-- 自定义输入 -->
				<label
					class="flex items-start gap-3 rounded-xl border px-3 py-2.5 transition-all duration-200 hover:border-purple-300 hover:bg-purple-50/30"
					:class="[
						disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
						isCustomSelected
							? 'border-purple-400 bg-purple-50/50 shadow-[0_0_0_1px_rgba(168,85,247,0.3)]'
							: 'border-slate-200 bg-white/50',
					]"
				>
					<input
						type="radio"
						value="__custom__"
						:checked="isCustomSelected"
						class="mt-0.5 h-3.5 w-3.5 accent-purple-600"
						:disabled="disabled"
						@change="!disabled && emit('select-option', '__custom__')"
					/>
					<div class="min-w-0 flex-1">
						<div class="text-sm font-medium text-slate-800">自定义方案</div>
						<textarea
							:value="customInput"
							class="mt-1.5 w-full resize-none rounded-lg border border-slate-200 bg-white/80 px-2.5 py-2 text-xs text-slate-700 placeholder:text-slate-400 focus:border-purple-400 focus:outline-none focus:ring-1 focus:ring-purple-200"
							rows="2"
							placeholder="输入你的建模思路、偏好模型、特殊要求..."
							:disabled="disabled"
							@input="
								!disabled &&
									emit(
										'update:custom-input',
										($event.target as HTMLTextAreaElement).value,
									)
							"
							@click.stop
						/>
					</div>
				</label>
			</div>

			<!-- 对话区 -->
			<div class="mx-4 my-3 rounded-xl border border-white/20 bg-white/40 backdrop-blur">
				<div class="flex items-center gap-1.5 border-b border-white/10 px-3 py-2">
					<MessageCircle class="h-3.5 w-3.5 text-blue-600" />
					<span class="text-[11px] font-medium text-slate-600">讨论区</span>
					<span class="text-[10px] text-slate-400">与 ModelerAgent 讨论本问建模方案</span>
				</div>

				<div
					v-if="chatHistory.length > 0"
					ref="chatScrollRef"
					class="chat-window max-h-48 overflow-y-auto px-3 py-2 space-y-2"
					@scroll="onChatScroll"
				>
					<div
						v-for="(msg, idx) in chatHistory"
						:key="idx"
						class="flex gap-2"
						:class="msg.role === 'user' ? 'flex-row-reverse' : ''"
					>
						<span class="shrink-0 text-xs">{{ msg.role === "user" ? "👤" : "🤖" }}</span>
						<div
							class="rounded-xl px-3 py-1.5 text-xs leading-relaxed max-w-[85%]"
							:class="
								msg.role === 'user'
									? 'bg-blue-600 text-white'
									: 'bg-slate-100 text-slate-700'
							"
						>
							{{ msg.content }}
						</div>
					</div>
				</div>
				<div v-else class="px-3 py-4 text-center text-[11px] text-slate-400">
					发送消息与 ModelerAgent 讨论本问的建模方案
				</div>

				<div class="flex items-center gap-2 border-t border-white/10 px-3 py-2">
					<input
						v-model="chatInput"
						type="text"
						class="flex-1 rounded-lg border border-slate-200 bg-white/80 px-2.5 py-1.5 text-xs text-slate-700 placeholder:text-slate-400 focus:border-blue-400 focus:outline-none"
						placeholder="输入消息讨论建模思路..."
						:disabled="disabled"
						@keydown.enter="handleSend"
						@click.stop
					/>
					<button
						class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
						:disabled="!chatInput.trim() || disabled"
						@click.stop="handleSend"
					>
						<Send class="h-3.5 w-3.5" />
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.modeling-card {
	position: relative;
	overflow: hidden;
	will-change: transform, max-height;
}

.card-stacked {
	max-height: 40px;
}

.card-expanded {
	max-height: 900px;
	animation: card-expand-spring 0.38s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.card-stacked-disabled {
	max-height: 40px;
}

@keyframes card-expand-spring {
	0% {
		transform: scale(0.96);
		opacity: 0.7;
	}
	100% {
		transform: scale(1);
		opacity: 1;
	}
}

.chat-window {
	mask-image: linear-gradient(to bottom, #000 0, #000 calc(100% - 0.5rem), transparent 100%);
	-webkit-mask-image: linear-gradient(to bottom, #000 0, #000 calc(100% - 0.5rem), transparent 100%);
}

.chat-window::-webkit-scrollbar {
	width: 3px;
}

.chat-window::-webkit-scrollbar-thumb {
	border-radius: 999px;
	background: rgba(148, 163, 184, 0.3);
}
</style>
