/** 图片相关常量 — 与后端 image_constants.py 保持同步。 */

/** 支持的图片扩展名（含点号前缀） */
export const IMAGE_EXTENSIONS = [
	".png",
	".jpg",
	".jpeg",
	".gif",
	".bmp",
	".webp",
	".svg",
] as const;

/** 用于构建正则的扩展名片段 */
export const IMAGE_EXTENSION_RE_FRAGMENT = "png|jpg|jpeg|gif|bmp|webp|svg";

/** 匹配图片扩展名的正则 */
export const IMAGE_EXTENSION_RE = new RegExp(
	`\\.(?:${IMAGE_EXTENSION_RE_FRAGMENT})$`,
	"i",
);

/** 判断文件名是否为支持的图片格式 */
export function isImageFile(filename: string): boolean {
	return IMAGE_EXTENSION_RE.test(filename);
}

/** 规范化图片文件名：去除路径，仅保留基本名 */
export function normalizeImageFilename(filename: string): string {
	return filename.replace(/\\/g, "/").split("/").pop() || filename;
}
