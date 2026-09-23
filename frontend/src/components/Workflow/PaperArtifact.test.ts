import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkflowArtifact } from "@/apis/workflowApi";
import ArtifactWorkbench from "./ArtifactWorkbench.vue";

const {
	getArtifactsMock,
	getFileDownloadUrlMock,
	getPaperMock,
	savePaperMock,
	compilePdfMock,
	openPreviewMock,
	buildFileUrlMock,
	routerPushMock,
	fetchMock,
} = vi.hoisted(() => ({
	getArtifactsMock: vi.fn(),
	getFileDownloadUrlMock: vi.fn(),
	getPaperMock: vi.fn(),
	savePaperMock: vi.fn(),
	compilePdfMock: vi.fn(),
	openPreviewMock: vi.fn(),
	buildFileUrlMock: vi.fn((path: string, taskId: string) => `/static/${taskId}/${path}`),
	routerPushMock: vi.fn(),
	fetchMock: vi.fn(),
}));

vi.mock("@/apis/workflowApi", () => ({
	getArtifacts: getArtifactsMock,
}));

vi.mock("@/apis/filesApi", () => ({
	compilePdf: compilePdfMock,
	getFileDownloadUrl: getFileDownloadUrlMock,
	getPaper: getPaperMock,
	savePaper: savePaperMock,
}));

vi.mock("@/composables/useFilePreview", () => ({
	useFilePreview: () => ({ openPreview: openPreviewMock, buildFileUrl: buildFileUrlMock }),
}));

vi.mock("vue-router", () => ({
	useRouter: () => ({ push: routerPushMock }),
}));

const taskId = "paper-task";
const paper: WorkflowArtifact = {
	filename: "res.md",
	path: "res.md",
	kind: "markdown",
	stage_id: "06-paper",
	preview_url: "/static/paper-task/res.md",
};
const pdf: WorkflowArtifact = {
	filename: "res.pdf",
	path: "res.pdf",
	kind: "pdf",
	stage_id: "07-compile",
	preview_url: "/static/paper-task/res.pdf",
};

let fileTimes: Record<string, string | null>;

function mountWorkbench(stageId: string) {
	return mount(ArtifactWorkbench, {
		props: { taskId, stageId },
		global: {
			stubs: {
				ArtifactSplitPreview: true,
			},
		},
	});
}

function mockArtifactLists(lists: Record<string, WorkflowArtifact[]>) {
	getArtifactsMock.mockImplementation(async (_taskId: string, stageId: string) => ({
		data: lists[stageId] ?? [],
	}));
}

describe("paper and final-audit artifacts", () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		window.localStorage.clear();
	});

	beforeEach(() => {
		vi.clearAllMocks();
		fileTimes = {
			"res.md": "2026-09-23T12:00:00Z",
			"res.pdf": "2026-09-23T12:01:00Z",
		};
		fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
			const filename = String(input).includes("res.pdf") ? "res.pdf" : "res.md";
			return {
				ok: true,
				headers: { get: (name: string) => name.toLowerCase() === "last-modified" ? fileTimes[filename] : null },
			};
		});
		vi.stubGlobal("fetch", fetchMock);
		getPaperMock.mockResolvedValue({ data: { content: "# 论文正文\n" } });
		savePaperMock.mockResolvedValue({ data: { success: true } });
		compilePdfMock.mockResolvedValue({ data: { pdf_url: "http://localhost:8000/static/paper-task/res.pdf" } });
		getFileDownloadUrlMock.mockResolvedValue({ data: { download_url: "http://localhost:8000/static/paper-task/report.pdf" } });
	});

	it("offers Markdown preview and a direct compile action when the paper is the only artifact", async () => {
		mockArtifactLists({ "06-paper": [paper], "07-compile": [] });
		const wrapper = mountWorkbench("06-paper");
		await flushPromises();

		expect(wrapper.text()).toContain("PDF 尚未生成");
		expect(wrapper.get('[data-testid="compile-pdf"]').text()).toContain("编译 PDF");
		await wrapper.get('[data-artifact-path="res.md"]').trigger("click");
		expect(wrapper.emitted("open-paper")?.[0]?.[0]).toMatchObject({ view: "markdown", artifact: paper });
	});

	it("treats a PDF newer than its Markdown source as current and opens it through the existing view", async () => {
		fileTimes["res.md"] = "2026-09-23T12:00:00Z";
		fileTimes["res.pdf"] = "2026-09-23T12:02:00Z";
		mockArtifactLists({ "06-paper": [paper], "07-compile": [pdf] });
		const wrapper = mountWorkbench("07-compile");
		await flushPromises();

		expect(wrapper.text()).toContain("PDF 与论文同步");
		expect(wrapper.find('[data-testid="compile-pdf"]').exists()).toBe(false);
		await wrapper.get('[data-artifact-path="res.pdf"]').trigger("click");
		expect(wrapper.emitted("open-paper")?.[0]?.[0]).toMatchObject({ view: "pdf", artifact: pdf });
	});

	it("offers recompilation for a stale PDF and saves the existing paper before compiling", async () => {
		fileTimes["res.md"] = "2026-09-23T12:02:00Z";
		fileTimes["res.pdf"] = "2026-09-23T12:00:00Z";
		mockArtifactLists({ "06-paper": [paper], "07-compile": [pdf] });
		const wrapper = mountWorkbench("06-paper");
		await flushPromises();

		expect(wrapper.text()).toContain("PDF 落后于论文");
		await wrapper.get('[data-testid="compile-pdf"]').trigger("click");
		await flushPromises();

		expect(getPaperMock).toHaveBeenCalledWith(taskId);
		expect(savePaperMock).toHaveBeenCalledWith(taskId, "# 论文正文\n");
		expect(compilePdfMock).toHaveBeenCalledWith(taskId);
		expect(routerPushMock).toHaveBeenCalledWith({
			path: `/task/${taskId}/pdf`,
			query: { compiled: "true" },
		});
	});

	it("provides a download action for final-audit outputs", async () => {
		const report: WorkflowArtifact = {
			filename: "校核报告.pdf",
			path: "08-final-audit/校核报告.pdf",
			kind: "pdf",
			stage_id: "08-final-audit",
			preview_url: "/static/paper-task/08-final-audit/%E6%A0%A1%E6%A0%B8%E6%8A%A5%E5%91%8A.pdf",
		};
		mockArtifactLists({ "08-final-audit": [report] });
		const clickMock = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
		const wrapper = mountWorkbench("08-final-audit");
		await flushPromises();

		await wrapper.get('[aria-label="下载 校核报告.pdf"]').trigger("click");
		expect(getFileDownloadUrlMock).toHaveBeenCalledWith(taskId, report.path);
		expect(clickMock).toHaveBeenCalledOnce();
	});
});
