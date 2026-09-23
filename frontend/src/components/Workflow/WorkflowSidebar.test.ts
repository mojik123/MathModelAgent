import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import WorkflowSidebar from "./WorkflowSidebar.vue";
import { WORKFLOW_STAGES } from "@/workflow/stages";

describe("WorkflowSidebar", () => {
  it("renders the nine stages in order with visible status text", () => {
    const wrapper = mount(WorkflowSidebar, {
      props: {
        stages: WORKFLOW_STAGES,
        activeStageId: "00-intake",
      },
    });

    const stageButtons = wrapper.findAll("button[data-stage-id]");
    expect(stageButtons).toHaveLength(9);
    expect(stageButtons.map((button) => button.attributes("data-stage-id"))).toEqual(
      WORKFLOW_STAGES.map((stage) => stage.id),
    );
    expect(stageButtons[0].text()).toContain("题目与附件盘点");
    expect(stageButtons[0].text()).toContain("就绪");
    expect(stageButtons[1].text()).toContain("未解锁");
    expect(stageButtons[0].attributes("aria-current")).toBe("step");
  });

  it("emits select with the clicked stage ID", async () => {
    const wrapper = mount(WorkflowSidebar, {
      props: {
        stages: WORKFLOW_STAGES,
        activeStageId: "00-intake",
      },
    });

    await wrapper.get('button[data-stage-id="01-analysis"]').trigger("click");

    expect(wrapper.emitted("select")).toEqual([["01-analysis"]]);
  });
});
