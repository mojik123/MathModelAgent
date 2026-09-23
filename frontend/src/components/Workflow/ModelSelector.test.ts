import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ModelSelector from "./ModelSelector.vue";
import type { ModelRegistryEntry, TaskModelConfig } from "@/apis/workflowApi";

const {
  getModelRegistryMock,
  noReasoningOption,
  getTaskModelConfigMock,
  saveTaskModelConfigMock,
} = vi.hoisted(() => ({
  getModelRegistryMock: vi.fn(),
  noReasoningOption: "none",
  getTaskModelConfigMock: vi.fn(),
  saveTaskModelConfigMock: vi.fn(),
}));

vi.mock("@/apis/workflowApi", () => ({
  NO_REASONING_OPTION: noReasoningOption,
  getModelRegistry: getModelRegistryMock,
  getTaskModelConfig: getTaskModelConfigMock,
  saveTaskModelConfig: saveTaskModelConfigMock,
}));

const models: ModelRegistryEntry[] = [
  {
    id: "gpt-6-sol",
    label: "gpt-6-sol",
    provider: "openai-responses",
    reasoning_options: ["low", "medium", "high"],
  },
  {
    id: "gpt-6-luna",
    label: "gpt-6-luna",
    provider: "codex-cli",
    reasoning_options: ["low", "medium", "high", "xhigh", "max"],
  },
  {
    id: "gpt-6-astra",
    label: "gpt-6-astra",
    provider: "openai-responses",
    reasoning_options: ["low", "medium", "high"],
  },
];

const savedConfig: TaskModelConfig = {
  task_id: "task-9",
  task_key: "task-9",
  model: "gpt-6-sol",
  reasoning: "medium",
};

function mountSelector() {
  return mount(ModelSelector, {
    props: { taskId: "task-9", taskKey: "task-9" },
  });
}

function notFoundError() {
  return { response: { status: 404 } };
}

describe("ModelSelector", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    window.localStorage.clear();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    HTMLElement.prototype.hasPointerCapture ??= () => false;
    HTMLElement.prototype.releasePointerCapture ??= () => {};
    getModelRegistryMock.mockResolvedValue({ data: models });
    getTaskModelConfigMock.mockResolvedValue({ data: savedConfig });
    saveTaskModelConfigMock.mockImplementation(async (config: TaskModelConfig) => ({ data: config }));
  });

  it("loads available models and the saved values for this task", async () => {
    const wrapper = mountSelector();
    await flushPromises();

    expect(getModelRegistryMock).toHaveBeenCalledOnce();
    expect(getTaskModelConfigMock).toHaveBeenCalledWith("task-9", "task-9");
    expect(wrapper.text()).toContain("gpt-6-sol");
    expect(wrapper.text()).toContain("已保存");
  });

  it("shows a visible default when no config exists and does not save automatically", async () => {
    getTaskModelConfigMock.mockRejectedValue(notFoundError());
    const wrapper = mountSelector();
    await flushPromises();

    expect(wrapper.text()).toContain("gpt-6-luna");
    expect(wrapper.text()).toContain("max");
    expect(wrapper.text()).toContain("尚未保存");
    expect(saveTaskModelConfigMock).not.toHaveBeenCalled();
  });

  it("saves a changed model and reasoning value for this task", async () => {
    const wrapper = mountSelector();
    await flushPromises();

    await wrapper.get('[aria-label="模型"]').trigger("pointerdown", {
      button: 0,
      ctrlKey: false,
      pointerType: "mouse",
    });
    await flushPromises();
    const modelOption = Array.from(document.body.querySelectorAll('[role="option"]')).find(
      (option) => option.textContent?.includes("gpt-6-astra"),
    );
    expect(modelOption).toBeTruthy();
    modelOption?.dispatchEvent(new Event("pointerup", { bubbles: true }));
    await flushPromises();

    await wrapper.get('[aria-label="推理强度"]').trigger("pointerdown", {
      button: 0,
      ctrlKey: false,
      pointerType: "mouse",
    });
    await flushPromises();
    const reasoningOption = Array.from(document.body.querySelectorAll('[role="option"]')).find(
      (option) => option.textContent?.trim() === "high",
    );
    expect(reasoningOption).toBeTruthy();
    reasoningOption?.dispatchEvent(new Event("pointerup", { bubbles: true }));
    await flushPromises();

    const saveButton = wrapper.findAll("button").find((button) => button.text().includes("保存"));
    expect(saveButton).toBeTruthy();
    await saveButton?.trigger("click");
    await flushPromises();

    const changedConfig = {
      task_id: "task-9",
      task_key: "task-9",
      model: "gpt-6-astra",
      reasoning: "high",
    };
    expect(saveTaskModelConfigMock).toHaveBeenCalledWith(changedConfig);
    expect(wrapper.text()).toContain("已保存");
    expect(window.localStorage.getItem("workflow-model-config-saved-at:task-9:task-9")).toBeTruthy();

    getTaskModelConfigMock.mockResolvedValue({ data: changedConfig });
    const reloadedWrapper = mountSelector();
    await flushPromises();
    expect(reloadedWrapper.text()).toContain("gpt-6-astra");
    expect(reloadedWrapper.text()).toContain("high");
    expect(reloadedWrapper.text()).toContain("本机上次成功保存");
  });

  it("keeps the selection visible and reports a failed save", async () => {
    getTaskModelConfigMock.mockRejectedValue(notFoundError());
    saveTaskModelConfigMock.mockRejectedValue(new Error("network failure"));
    const wrapper = mountSelector();
    await flushPromises();

    const saveButton = wrapper.findAll("button").find((button) => button.text().includes("保存"));
    expect(saveButton).toBeTruthy();
    await saveButton?.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("保存失败");
    expect(wrapper.text()).toContain("gpt-6-luna");
  });

  it("saves the no-reasoning sentinel when the selected model has no reasoning options", async () => {
    getModelRegistryMock.mockResolvedValue({
      data: [{
        id: "claude-test",
        label: "claude-test",
        provider: "anthropic",
        reasoning_options: [],
      }],
    });
    getTaskModelConfigMock.mockRejectedValue(notFoundError());
    const wrapper = mountSelector();
    await flushPromises();

    expect(wrapper.text()).toContain("不指定");
    const saveButton = wrapper.findAll("button").find((button) => button.text().includes("保存"));
    await saveButton?.trigger("click");
    await flushPromises();

    expect(saveTaskModelConfigMock).toHaveBeenCalledWith({
      task_id: "task-9",
      task_key: "task-9",
      model: "claude-test",
      reasoning: "none",
    });
  });
});
