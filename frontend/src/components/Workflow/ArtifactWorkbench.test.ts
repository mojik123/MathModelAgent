import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ArtifactWorkbench from "./ArtifactWorkbench.vue";
import type { WorkflowArtifact } from "@/apis/workflowApi";

const {
  getArtifactsMock,
  getImageCodeMock,
  openPreviewMock,
  buildFileUrlMock,
  routerPushMock,
} = vi.hoisted(() => ({
  getArtifactsMock: vi.fn(),
  getImageCodeMock: vi.fn(),
  openPreviewMock: vi.fn(),
  buildFileUrlMock: vi.fn((path: string, taskId: string) => `/static/${taskId}/${encodeURI(path)}`),
  routerPushMock: vi.fn(),
}));

vi.mock("@/apis/workflowApi", () => ({
  getArtifacts: getArtifactsMock,
}));

vi.mock("@/apis/filesApi", () => ({
  getImageCode: getImageCodeMock,
}));

vi.mock("@/composables/useFilePreview", () => ({
  useFilePreview: () => ({
    openPreview: openPreviewMock,
    buildFileUrl: buildFileUrlMock,
  }),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: routerPushMock }),
}));

const imageArtifact: WorkflowArtifact = {
  filename: "拟合结果.png",
  path: "图表/拟合结果.png",
  kind: "image",
  stage_id: "05-figures",
  preview_url: "/static/task-1/%E5%9B%BE%E8%A1%A8/%E6%8B%9F%E5%90%88%E7%BB%93%E6%9E%9C.png",
};

function mountWorkbench(
  artifacts: WorkflowArtifact[],
  stageId = "05-figures",
) {
  getArtifactsMock.mockResolvedValue({ data: artifacts });
  return mount(ArtifactWorkbench, {
    props: { taskId: "task-1", stageId },
  });
}

describe("ArtifactWorkbench", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    getArtifactsMock.mockResolvedValue({ data: [] });
    getImageCodeMock.mockResolvedValue({ data: { found: false, filename: "" } });
  });

  it("shows an image beside code returned by the image-code API", async () => {
    getImageCodeMock.mockResolvedValue({
      data: { found: true, filename: imageArtifact.path, code: "plt.plot(x, y)" },
    });
    const wrapper = mountWorkbench([imageArtifact]);
    await flushPromises();

    await wrapper.get('button[data-artifact-path="图表/拟合结果.png"]').trigger("click");
    await flushPromises();

    expect(wrapper.get("img").attributes("alt")).toBe("拟合结果.png");
    expect(wrapper.text()).toContain("plt.plot(x, y)");
    expect(buildFileUrlMock).toHaveBeenCalledWith("图表/拟合结果.png", "task-1");
    expect(getImageCodeMock).toHaveBeenCalledWith("task-1", "图表/拟合结果.png");
  });

  it("shows a clear empty source-code state when no code is found", async () => {
    const wrapper = mountWorkbench([imageArtifact]);
    await flushPromises();

    await wrapper.get('button[data-artifact-path="图表/拟合结果.png"]').trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("未找到源代码");
  });

  it("loads an explicitly linked source file when the image-code API has no code", async () => {
    const imageWithSource = {
      ...imageArtifact,
      source_path: "代码/拟合结果.py",
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => "plt.savefig('图表/拟合结果.png')",
    });
    vi.stubGlobal("fetch", fetchMock);

    const wrapper = mountWorkbench([imageWithSource]);
    await flushPromises();
    await wrapper.get('button[data-artifact-path="图表/拟合结果.png"]').trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("plt.savefig('图表/拟合结果.png')");
    expect(buildFileUrlMock).toHaveBeenCalledWith("代码/拟合结果.py", "task-1");
    expect(fetchMock).toHaveBeenCalledWith(
      `/static/task-1/${encodeURI("代码/拟合结果.py")}`,
    );
  });

  it("routes the paper Markdown artifact to the existing writer view", async () => {
    const paper: WorkflowArtifact = {
      filename: "res.md",
      path: "res.md",
      kind: "markdown",
      stage_id: "06-paper",
      preview_url: "/static/task-1/res.md",
    };
    const wrapper = mountWorkbench([paper], "06-paper");
    await flushPromises();

    await wrapper.get('button[data-artifact-path="res.md"]').trigger("click");

    expect(wrapper.emitted("open-paper")).toEqual([[{ view: "markdown", artifact: paper }]]);
    expect(openPreviewMock).not.toHaveBeenCalled();
  });

  it("routes the compiled PDF artifact to the existing PDF view", async () => {
    const pdf: WorkflowArtifact = {
      filename: "res.pdf",
      path: "res.pdf",
      kind: "pdf",
      stage_id: "07-compile",
      preview_url: "/static/task-1/res.pdf",
    };
    const wrapper = mountWorkbench([pdf], "07-compile");
    await flushPromises();

    await wrapper.get('button[data-artifact-path="res.pdf"]').trigger("click");

    expect(wrapper.emitted("open-paper")).toEqual([[{ view: "pdf", artifact: pdf }]]);
    expect(openPreviewMock).not.toHaveBeenCalled();
  });

  it("uses the shared file preview for ordinary files", async () => {
    const code: WorkflowArtifact = {
      filename: "solve.py",
      path: "code/solve.py",
      kind: "code",
      stage_id: "03-code",
      preview_url: "/static/task-1/code/solve.py",
    };
    const wrapper = mountWorkbench([code], "03-code");
    await flushPromises();

    await wrapper.get('button[data-artifact-path="code/solve.py"]').trigger("click");

    expect(buildFileUrlMock).toHaveBeenCalledWith("code/solve.py", "task-1");
    expect(openPreviewMock).toHaveBeenCalledWith("/static/task-1/code/solve.py", "solve.py");
  });

  it("explains when a stage has no artifacts", async () => {
    const wrapper = mountWorkbench([]);
    await flushPromises();

    expect(wrapper.text()).toContain("此阶段还没有成果文件");
  });
});
