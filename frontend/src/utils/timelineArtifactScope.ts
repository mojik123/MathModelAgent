import { useTaskStore } from "@/stores/task";
import { AgentType } from "@/utils/enum";
import type { Message } from "@/utils/response";
import { watch } from "vue";

let installed = false;
let scheduled = false;

function messageCorpus(message: Message) {
	return [
		message.content ?? "",
		message.action?.object ?? "",
		message.action?.detail ?? "",
		message.action?.flow?.label ?? "",
		message.group_id ?? "",
		message.agent_instance_id ?? "",
	]
		.join("\n")
		.replace(/\\/g, "/");
}

function collectMatches(text: string, pattern: RegExp, result: Set<number>) {
	for (const match of text.matchAll(pattern)) {
		const value = Number(match[1]);
		if (Number.isInteger(value) && value > 0 && value <= 99) result.add(value);
	}
}

function inferQuestionIndex(message: Message) {
	if (typeof message.question_index === "number" && message.question_index > 0) {
		return message.question_index;
	}
	if (
		message.msg_type === "agent" &&
		[AgentType.COORDINATOR, AgentType.MODELER].includes(message.agent_type)
	) {
		return null;
	}

	const text = messageCorpus(message);
	const strongMatches = new Set<number>();
	collectMatches(text, /(?:^|[\s./_-])q(?:ues)?(\d+)(?=$|[\s./_-])/gi, strongMatches);
	collectMatches(text, /(?:\[组#|子问题组#|Group#)(\d+)/gi, strongMatches);
	collectMatches(text, /(?:^|[/\s])5\.(\d+)(?=$|[/_\s.-])/g, strongMatches);
	collectMatches(text, /问题\s*(\d+)\s*(?:的|模型|求解|代码|图片|章节|组)/g, strongMatches);

	return strongMatches.size === 1 ? [...strongMatches][0] : null;
}

function inferArtifactPhase(message: Message) {
	const text = messageCorpus(message);
	if (/(?:^|[/\s])4(?:\.2)?(?:_|[/\s.-]|$)|\bEDA\b|探索性数据分析|描述性统计|数据预处理|数据清洗/i.test(text)) {
		return "eda";
	}
	if (/(?:^|[/\s])6(?:_|[/\s.-]|$)|灵敏度分析|敏感性分析/i.test(text)) {
		return "sensitivity_analysis";
	}
	return null;
}

function scopedIdentity(message: Message, questionIndex: number) {
	if (message.msg_type === "agent") {
		if (message.agent_type === AgentType.WRITER) return `q${questionIndex}.writer`;
		if (message.agent_type === AgentType.SUB_COORDINATOR) {
			return `q${questionIndex}.sub_coordinator`;
		}
		if (message.agent_type === AgentType.CODER) return `q${questionIndex}.coder.artifact`;
	}
	if (message.msg_type === "tool") return `q${questionIndex}.coder.tool`;
	return `q${questionIndex}.process`;
}

function enrichMessageScope(message: Message) {
	const questionIndex = inferQuestionIndex(message);
	let changed = false;
	if (questionIndex != null && message.question_index !== questionIndex) {
		message.question_index = questionIndex;
		changed = true;
	}

	if (questionIndex != null) {
		const identity = scopedIdentity(message, questionIndex);
		if (!message.group_id || !/q(?:ues)?\d+/i.test(message.group_id)) {
			message.group_id = identity;
			changed = true;
		}
		if (!message.agent_instance_id || !/q(?:ues)?\d+/i.test(message.agent_instance_id)) {
			message.agent_instance_id = identity;
			changed = true;
		}
		if (!message.phase && message.msg_type !== "user") {
			message.phase = message.msg_type === "agent" && message.agent_type === AgentType.WRITER
				? "writing"
				: "coding";
			changed = true;
		}
		return changed;
	}

	const artifactPhase = inferArtifactPhase(message);
	if (artifactPhase && !message.phase) {
		message.phase = artifactPhase;
		changed = true;
	}
	if (artifactPhase && !message.group_id) {
		message.group_id = `${artifactPhase}.coder`;
		changed = true;
	}
	return changed;
}

function enrichAllMessages() {
	const taskStore = useTaskStore();
	for (const message of taskStore.messages as Message[]) enrichMessageScope(message);
}

function scheduleEnrich() {
	if (scheduled) return;
	scheduled = true;
	requestAnimationFrame(() => {
		scheduled = false;
		enrichAllMessages();
	});
}

export function installTimelineArtifactScope() {
	if (installed || typeof window === "undefined") return;
	installed = true;
	const taskStore = useTaskStore();
	watch(
		() =>
			taskStore.messages
				.map(
					(message) =>
						`${message.id}:${message.content?.length ?? 0}:${message.question_index ?? ""}:${message.group_id ?? ""}`,
				)
				.join("|"),
		scheduleEnrich,
		{ immediate: true, flush: "post" },
	);
}
