import { flushPromises, shallowMount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StageOverview from "@/components/Workflow/StageOverview.vue";
import WorkflowSidebar from "@/components/Workflow/WorkflowSidebar.vue";
import { WORKFLOW_STAGES } from "@/workflow/stages";
import TaskPage from "./index.vue";

const { taskStoreMock, getWorkflowStateMock, getWorkflowAcceptanceMock, getWriterSequeMock, startWorkflowStageMock, getWorkflowRunMock, stopWorkflowRunMock, routerPushMock } = vi.hoisted(() => ({
	taskStoreMock: {
		messages: [] as Array<Record<string, unknown>>,
		currentProgress: null as null | Record<string, unknown>,
		taskRuntimeState: null as null | Record<string, unknown>,
		taskStatus: "ready",
		isRunning: false,
		writerMessages: [] as unknown[],
		coderMessages: [] as unknown[],
		interpreterMessage: null as unknown,
		wsStatus: "disconnected",
		coordinatorMessages: [] as unknown[],
		closeWebSocket: vi.fn(),
		loadTaskMessages: vi.fn().mockResolvedValue(false),
		connectWebSocket: vi.fn(),
		addUserAction: vi.fn(),
		stopTask: vi.fn(),
		startTask: vi.fn(),
		downloadMessages: vi.fn(),
	},
	getWorkflowStateMock: vi.fn(),
	getWorkflowAcceptanceMock: vi.fn(),
	getWriterSequeMock: vi.fn(),
	startWorkflowStageMock: vi.fn(),
	getWorkflowRunMock: vi.fn(),
	stopWorkflowRunMock: vi.fn(),
	routerPushMock: vi.fn(),
}));

vi.mock("@/stores/task", () => ({
	useTaskStore: () => taskStoreMock,
}));

vi.mock("@/apis/workflowApi", () => ({
	getWorkflowState: getWorkflowStateMock,
	getWorkflowAcceptance: getWorkflowAcceptanceMock,
	startWorkflowStage: startWorkflowStageMock,
	getWorkflowRun: getWorkflowRunMock,
	stopWorkflowRun: stopWorkflowRunMock,
}));

vi.mock("@/apis/commonApi", () => ({
	getWriterSeque: getWriterSequeMock,
}));

vi.mock("vue-router", () => ({
	useRouter: () => ({ push: routerPushMock }),
}));

const stubs = {
	WorkflowSidebar,
	StageOverview,
	ArtifactWorkbench: {
		props: ["taskId", "stageId"],
		template: '<section data-testid="stage-artifacts" :data-stage-id="stageId" />',
	},
	ModelSelector: {
		props: ["taskId", "taskKey"],
		template: '<aside data-testid="task-model-selector" :data-task-id="taskId" :data-task-key="taskKey" />',
	},
	Tabs: { template: "<div><slot /></div>" },
	TabsContent: {
		props: ["value"],
		template: '<div v-if="value === \'workbench\'"><slot /></div>',
	},
	TabsList: { template: "<div><slot /></div>" },
	TabsTrigger: { template: "<button><slot /></button>" },
};

function mountTaskPage() {
	return shallowMount(TaskPage, {
		props: { task_id: "layout-task" },
		global: { stubs },
	});
}

describe("task workbench layout", () => {
	let wrapper: ReturnType<typeof mountTaskPage> | null = null;

	beforeEach(() => {
		vi.clearAllMocks();
		taskStoreMock.messages = [];
		taskStoreMock.currentProgress = null;
		taskStoreMock.taskRuntimeState = null;
		taskStoreMock.taskStatus = "ready";
		taskStoreMock.isRunning = false;
		taskStoreMock.writerMessages = [];
		taskStoreMock.coderMessages = [];
		taskStoreMock.interpreterMessage = null;
		taskStoreMock.wsStatus = "disconnected";
		taskStoreMock.coordinatorMessages = [];
		getWorkflowStateMock.mockResolvedValue({ data: { stages: WORKFLOW_STAGES, checklist: null } });
		getWorkflowAcceptanceMock.mockResolvedValue({
			data: {
				stage_id: "00-intake",
				verdict: "BLOCKED",
				checked_at: "",
				state_status: "READY",
				missing: [],
				invalid: [],
				evidence: [],
				reasons: [],
			},
		});
		getWriterSequeMock.mockResolvedValue({ data: { writer_seque: [] } });
		startWorkflowStageMock.mockResolvedValue({ data: { run_id: "run-1", status: "completed", output: "stage done", log_path: "logs/codex/run-1.json" } });
	});

	afterEach(() => {
		wrapper?.unmount();
		wrapper = null;
		window.localStorage.clear();
	});

	it("keeps stage navigation primary and lets the selected stage drive center content", async () => {
		wrapper = mountTaskPage();
		await flushPromises();

		const layout = wrapper.get('[data-testid="task-workbench-layout"]');
		expect(layout.attributes("data-layout")).toBe("responsive-three-column");
		expect(layout.get('[data-testid="task-primary-stage-navigation"]').exists()).toBe(true);
		expect(layout.get('[data-testid="task-model-selector-column"]').exists()).toBe(true);
		expect(wrapper.get('[data-testid="task-model-selector"]').attributes("data-task-key")).toBe("00-intake");
		const mainGridClasses = layout.get("main").classes();
		expect(mainGridClasses).toContain("md:grid-cols-[clamp(10rem,19vw,14rem)_minmax(15rem,1fr)_clamp(12rem,20vw,16rem)]");
		expect(mainGridClasses).toContain("xl:grid-cols-[15rem_minmax(0,1fr)_18rem]");
		expect(wrapper.get('button[data-stage-id="00-intake"]').classes().join(" ")).toContain("focus-visible:ring-2");
		expect(wrapper.get('a[href="#task-model-selector-column"]').exists()).toBe(true);

		await wrapper.get('[data-stage-id="01-analysis"]').trigger("click");
		await flushPromises();

		expect(wrapper.get("#stage-overview-title").text()).toBe("赛题分析");
		expect(wrapper.get('[data-testid="stage-artifacts"]').attributes("data-stage-id")).toBe("01-analysis");
		expect(wrapper.get('[data-testid="task-model-selector"]').attributes("data-task-key")).toBe("01-analysis");
	});

	it("keeps WebSocket messages in a compact, keyboard-expandable run log", async () => {
		taskStoreMock.messages = [
			{
				id: "message-1",
				created_at: "2026-09-23T12:00:00Z",
				msg_type: "system",
				type: "info",
				content: "任务已连接",
			},
		];
		wrapper = mountTaskPage();
		await flushPromises();

		const log = wrapper.get('[data-testid="task-run-log"]');
		expect((log.element as HTMLDetailsElement).open).toBe(false);
		await log.get("summary").trigger("click");
		expect((log.element as HTMLDetailsElement).open).toBe(true);
		expect(log.get('[role="log"]').text()).toContain("任务已连接");
	});
});
