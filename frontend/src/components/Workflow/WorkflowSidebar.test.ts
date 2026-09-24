import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import WorkflowSidebar from "./WorkflowSidebar.vue";
import { WORKFLOW_STAGES } from "@/workflow/stages";

const { getModelRegistryMock, getTaskModelConfigMock, saveTaskModelConfigMock } = vi.hoisted(() => ({
	getModelRegistryMock: vi.fn(),
	getTaskModelConfigMock: vi.fn(),
	saveTaskModelConfigMock: vi.fn(),
}));

vi.mock("@/apis/workflowApi", () => ({
	NO_REASONING_OPTION: "none",
	getModelRegistry: getModelRegistryMock,
	getTaskModelConfig: getTaskModelConfigMock,
	saveTaskModelConfig: saveTaskModelConfigMock,
}));

describe("WorkflowSidebar", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		getModelRegistryMock.mockResolvedValue({ data: [{ id: "gpt-6-luna", label: "gpt-6-luna", provider: "codex-cli", reasoning_options: ["max"] }] });
		getTaskModelConfigMock.mockRejectedValue({ response: { status: 404 } });
	});

	it("renders the nine stages in order with visible status text", async () => {
    const wrapper = mount(WorkflowSidebar, {
      props: {
        stages: WORKFLOW_STAGES,
        activeStageId: "00-intake",
		taskId: "task-1",
      },
    });
		await flushPromises();

    const stageButtons = wrapper.findAll("button[data-stage-id]");
    expect(stageButtons).toHaveLength(9);
    expect(stageButtons.map((button) => button.attributes("data-stage-id"))).toEqual(
      WORKFLOW_STAGES.map((stage) => stage.id),
    );
    expect(stageButtons[0].text()).toContain("题目与附件盘点");
    expect(stageButtons[0].text()).toContain("就绪");
    expect(stageButtons[1].text()).toContain("未解锁");
    expect(stageButtons[0].attributes("aria-current")).toBe("step");
		expect(wrapper.findAll('[aria-label="任务模型"]')).toHaveLength(9);
		expect(wrapper.findAll('[aria-label="任务思考强度"]')).toHaveLength(9);
  });

  it("emits select with the clicked stage ID", async () => {
    const wrapper = mount(WorkflowSidebar, {
      props: {
        stages: WORKFLOW_STAGES,
        activeStageId: "00-intake",
		taskId: "task-1",
      },
    });

    await wrapper.get('button[data-stage-id="01-analysis"]').trigger("click");

    expect(wrapper.emitted("select")).toEqual([["01-analysis"]]);
  });
});
