/** 对应后端 response.py 的消息结构定义 */

import type { AgentType } from "./enum";

/** 系统消息类型 */
export type SystemMessageType = "info" | "warning" | "success" | "error";

/** 消息基础接口 */
export interface MessageFlow {
	from: string;
	to: string;
	label?: string;
}

export interface MessageAction {
	verb: string;
	object: string;
	detail?: string;
	flow?: MessageFlow;
}

export interface BaseMessage {
	id: string;
	created_at?: string;
	msg_type: "system" | "agent" | "user" | "tool" | "progress";
	content?: string | null;
	action?: MessageAction;
	local_action?: boolean;
}

/** 工具调用消息 */
export interface ToolMessage extends BaseMessage {
	msg_type: "tool";
	tool_name: "execute_code" | "search_scholar";
	input: Record<string, unknown> | null;
	output: string[] | OutputItem[] | null;
}

/** 系统通知消息 */
export interface SystemMessage extends BaseMessage {
	msg_type: "system";
	type: SystemMessageType;
}

/** 用户消息 */
export interface UserMessage extends BaseMessage {
	msg_type: "user";
}

/** Agent 消息基类 */
export interface AgentMessage extends BaseMessage {
	msg_type: "agent";
	agent_type: AgentType;
	agent_index?: number | null; // 并行组编号（1-based），null 表示全局单例
	stream_state?: "streaming" | "complete" | null;
	// 结构化身份字段（多 Agent 协同用）
	agent_instance_id?: string | null; // 全局唯一实例 ID，如 "q1.coder.r2"
	question_index?: number | null; // 所属问题编号（1-based）
	race_index?: number | null; // 竞速编号（1-based）
	phase?: string | null; // 当前阶段
	group_id?: string | null; // 前端分组用
	feedback_kind?: string | null; // user_checkpoint|auto_quality_check|rework|handoff|final_review
}

/** 建模手消息 */
export interface ModelerMessage extends AgentMessage {
	agent_type: AgentType.MODELER;
}

/** 协调者消息 */
export interface CoordinatorMessage extends AgentMessage {
	agent_type: AgentType.COORDINATOR;
}

/** 子问题组协调者消息（携带组编号） */
export interface SubCoordinatorMessage extends AgentMessage {
	agent_type: AgentType.SUB_COORDINATOR;
}

/** 代码执行结果格式类型 */
export type ExecutionFormat =
	| "text"
	| "html"
	| "markdown"
	| "png"
	| "jpeg"
	| "svg"
	| "pdf"
	| "latex"
	| "json"
	| "javascript";

/** 代码执行结果基类 */
export interface BaseCodeExecution {
	res_type: "stdout" | "stderr" | "result" | "error";
	msg?: string;
}

/** 标准输出执行结果 */
export interface StdOutExecution extends BaseCodeExecution {
	res_type: "stdout";
}

/** 标准错误执行结果 */
export interface StdErrExecution extends BaseCodeExecution {
	res_type: "stderr";
}

/** 执行结果 */
export interface ResultExecution extends BaseCodeExecution {
	res_type: "result";
	format: ExecutionFormat;
}

/** 执行错误 */
export interface ErrorExecution extends BaseCodeExecution {
	res_type: "error";
	name: string;
	value: string;
	traceback: string;
}

/** 代码执行输出项 */
export type OutputItem =
	| StdOutExecution
	| StdErrExecution
	| ResultExecution
	| ErrorExecution;

/** 文献搜索工具消息 */
export interface ScholarMessage extends ToolMessage {
	tool_name: "search_scholar";
	input: Record<string, never>;
	output: string[];
}

/** 代码执行工具消息 */
export interface InterpreterMessage extends ToolMessage {
	tool_name: "execute_code";
	input: {
		code: string;
	} | null;
	output: OutputItem[] | null;
	/** 代码介绍：阶段、功能、预期结果 */
	description?: string | null;
}

/** 代码手消息 */
export interface CoderMessage extends AgentMessage {
	agent_type: AgentType.CODER;
}

/** 论文手消息 */
export interface WriterMessage extends AgentMessage {
	agent_type: AgentType.WRITER;
	sub_title?: string;
}

/** 工作流进度消息 */
export interface ProgressMessage extends BaseMessage {
	msg_type: "progress";
	current: number;
	total: number;
	percentage: number;
	description: string;
}

/** 所有消息类型的联合类型 */
export type Message =
	| SystemMessage
	| UserMessage
	| CoderMessage
	| WriterMessage
	| ModelerMessage
	| CoordinatorMessage
	| SubCoordinatorMessage
	| ToolMessage
	| ProgressMessage;
