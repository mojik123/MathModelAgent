import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TaskModelControls from "./TaskModelControls.vue";
import type { ModelRegistryEntry, TaskModelConfig } from "@/apis/workflowApi";

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

const models: ModelRegistryEntry[] = [
	{ id: "gpt-6-luna", label: "gpt-6-luna", provider: "codex-cli", reasoning_options: ["low", "medium", "max"] },
	{ id: "gpt-6-sol", label: "gpt-6-sol", provider: "codex-cli", reasoning_options: ["low", "high"] },
];

const notFound = () => ({ response: { status: 404 } });

describe("TaskModelControls", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		getModelRegistryMock.mockResolvedValue({ data: models });
		getTaskModelConfigMock.mockResolvedValue({
			data: { task_id: "task-1", task_key: "00-intake", model: "gpt-6-luna", reasoning: "max" },
		});
		saveTaskModelConfigMock.mockImplementation(async (config: TaskModelConfig) => ({ data: config }));
	});

	it("loads and saves compact controls for one task stage", async () => {
		const wrapper = mount(TaskModelControls, { props: { taskId: "task-1", taskKey: "00-intake" } });
		await flushPromises();

		expect(getTaskModelConfigMock).toHaveBeenCalledWith("task-1", "00-intake");
		expect(wrapper.get('[aria-label="任务模型"]').element).toHaveProperty("value", "gpt-6-luna");
		expect(wrapper.get('[aria-label="任务思考强度"]').element).toHaveProperty("value", "max");

		await wrapper.get('[aria-label="任务模型"]').setValue("gpt-6-sol");
		await wrapper.get('[aria-label="任务思考强度"]').setValue("high");
		await flushPromises();

		expect(saveTaskModelConfigMock).toHaveBeenCalledWith({
			task_id: "task-1",
			task_key: "00-intake",
			model: "gpt-6-sol",
			reasoning: "high",
		});
		expect(wrapper.text()).toContain("已保存");
	});

	it("shows Luna max without saving when task config is missing", async () => {
		getTaskModelConfigMock.mockRejectedValue(notFound());
		const wrapper = mount(TaskModelControls, { props: { taskId: "task-2", taskKey: "01-analysis" } });
		await flushPromises();

		expect(wrapper.get('[aria-label="任务模型"]').element).toHaveProperty("value", "gpt-6-luna");
		expect(wrapper.get('[aria-label="任务思考强度"]').element).toHaveProperty("value", "max");
		expect(saveTaskModelConfigMock).not.toHaveBeenCalled();
		expect(wrapper.text()).toContain("未保存");
	});
});
