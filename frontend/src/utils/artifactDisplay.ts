export interface ArtifactDisplayInfo {
	rawPath: string;
	normalizedPath: string;
	sectionDir: string;
	sectionTitle: string;
	fileName: string;
	shortName: string;
	fullName: string;
}

function stripUrlSuffix(value: string): { path: string; suffix: string } {
	const match = value.match(/[?#].*$/);
	return {
		path: match ? value.slice(0, -match[0].length) : value,
		suffix: match?.[0] ?? "",
	};
}

function cleanArtifactPath(value: string, taskId?: string): string {
	const raw = (value || "").trim().replace(/^['"]|['"]$/g, "");
	const { path } = stripUrlSuffix(raw);

	let clean = decodeURIComponent(path)
		.replace(/\\/g, "/")
		.replace(/^\.?\//, "")
		.replace(/^\/+/, "");

	const staticMatch = clean.match(/(?:^|\/)static\/([^/]+)\/(.+)$/);
	if (staticMatch) {
		clean = staticMatch[2] || clean;
	}

	const workDirMatch = clean.match(/(?:^|\/)work_dir\/([^/]+)\/(.+)$/);
	if (workDirMatch) {
		clean = workDirMatch[2] || clean;
	}

	const segments = clean.split("/").filter(Boolean);
	if (taskId && segments[0] === taskId) {
		segments.shift();
	}

	return segments.join("/");
}

function sectionTitleFromDir(sectionDir: string): string {
	if (!sectionDir) return "";

	const match = sectionDir.match(/^(\d+\.\d+)_(.+)$/);
	if (!match) return sectionDir;

	const [, num, title] = match;
	return `${num} ${title}`;
}

export function getArtifactDisplayInfo(
	value: string,
	taskId?: string,
): ArtifactDisplayInfo {
	const normalizedPath = cleanArtifactPath(value, taskId);
	const segments = normalizedPath.split("/").filter(Boolean);

	const fileName = segments.at(-1) || normalizedPath || "文件";
	const sectionDir =
		segments.length >= 2 && /^\d+\.\d+_/.test(segments[0])
			? segments[0]
			: "";

	const sectionTitle = sectionTitleFromDir(sectionDir);
	const shortName = fileName;
	const fullName = sectionTitle ? `${sectionTitle} / ${fileName}` : fileName;

	return {
		rawPath: value,
		normalizedPath,
		sectionDir,
		sectionTitle,
		fileName,
		shortName,
		fullName,
	};
}
