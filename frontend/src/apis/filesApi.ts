import request from "@/utils/request";

/**
 * 获取任务工作区文件列表
 * @param task_id 任务ID
 */
export function getFiles(task_id: string) {
	return request.get<
		{
			filename: string;
			file_type: string;
			name?: string;
			type?: string;
			size?: number;
			modified_time?: string | number | Date;
		}[]
	>("/files", {
		params: { task_id },
	});
}

/**
 * 获取单个文件下载链接
 * @param task_id 任务ID
 * @param filename 文件名
 */
export async function getFileDownloadUrl(task_id: string, filename: string) {
	return await request.get<{ download_url: string }>("/download_url", {
		params: {
			task_id,
			filename,
		},
	});
}

/**
 * 获取所有文件压缩包下载链接
 * @param task_id 任务ID
 */
export async function getAllFilesDownloadUrl(task_id: string) {
	return await request.get<{ download_url: string }>("/download_all_url", {
		params: {
			task_id,
		},
	});
}

/** 获取任务论文 Markdown */
export function getPaper(task_id: string) {
	return request.get<{ content: string }>("/paper", {
		params: { task_id },
	});
}

/** 保存任务论文 Markdown */
export function savePaper(task_id: string, content: string) {
	return request.post<{ success: boolean }>("/paper", {
		task_id,
		content,
	});
}

/** 按需编译 PDF */
export function compilePdf(task_id: string) {
	return request.post<{ pdf_url: string }>("/compile_pdf", null, {
		params: { task_id },
		timeout: 600000,
	});
}

/** 修改图片并同步论文 Markdown（旧版 PIL 方式，保留兼容） */
export function reviseImage(
	task_id: string,
	filename: string,
	instruction: string,
) {
	return request.post<{
		success: boolean;
		filename: string;
		image_url: string;
		content: string;
	}>("/revise_image", { task_id, filename, instruction }, { timeout: 600000 });
}

/** AI 对话式图片修订（新端点） */
export function getImageCode(task_id: string, filename: string) {
	return request.get<{
		found: boolean;
		filename: string;
		cell_index?: number | null;
		code?: string | null;
		section?: string | null;
		description?: string | null;
		alt_text?: string | null;
		caption?: string | null;
	}>("/image_code", {
		params: { task_id, filename },
	});
}

export function reviseImageChat(
	task_id: string,
	filename: string,
	instruction: string,
	title?: string,
	description?: string,
	conversation_history?: { role: "user" | "assistant"; content: string }[],
) {
	return request.post<{
		success: boolean;
		status: "success" | "failed" | "partial_success";
		message: string;
		analysis_text: string;
		revised_code?: string | null;
		updated_alt_text?: string | null;
		updated_caption?: string | null;
		paper_updated?: boolean;
		caption_updated?: boolean;
		render_success?: boolean;
		render_message?: string | null;
		image_url?: string | null;
		code_found?: boolean;
	}>(
		"/revise_image_chat",
		{
			task_id,
			filename,
			instruction,
			title,
			description,
			conversation_history,
		},
		{ timeout: 600000 },
	);
}

/** AI 对话修改论文文本 */
export function reviseTextChat(
	task_id: string,
	instruction: string,
	selected_text: string,
	context?: string,
	conversation_history?: { role: "user" | "assistant"; content: string }[],
) {
	return request.post<{
		success: boolean;
		status?: "success" | "partial_success" | "failed";
		message: string;
		revised_text?: string;
		updated_paper?: string;
		paper_updated?: boolean;
		revision_scope?: "selection" | "paper";
		applied?: boolean;
		validation_issues?: string[];
	}>(
		"/revise_text_chat",
		{
			task_id,
			instruction,
			selected_text,
			context,
			conversation_history,
		},
		{ timeout: 120000 },
	);
}
