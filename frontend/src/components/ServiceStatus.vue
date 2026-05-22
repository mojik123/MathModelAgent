<template>
  <div class="flex items-center gap-2">
    <div
      v-for="entry in serviceEntries"
      :key="entry.key"
      class="flex items-center gap-1 px-2 py-1 rounded-md text-xs"
      :class="getStatusClass(entry.service.status)"
      :title="entry.service.message"
    >
      <div
        class="w-2 h-2 rounded-full"
        :class="getStatusDotClass(entry.service.status)"
      ></div>
      <span>{{ formatServiceName(entry.key) }}</span>
      <span v-if="typeof entry.service.count === 'number'">
        {{ entry.service.count }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { getServiceStatus } from "@/apis/commonApi";
import { useToast } from "@/components/ui/toast/use-toast";
import { computed, onMounted, onUnmounted, ref } from "vue";

type ServiceState = "running" | "busy" | "idle" | "error" | "unknown";

interface ServiceStatus {
	status: ServiceState;
	message: string;
	count?: number;
	ids?: string[];
}

interface Services {
	backend: ServiceStatus;
	redis: ServiceStatus;
	active_tasks?: ServiceStatus;
	[key: string]: ServiceStatus | undefined;
}

const { toast } = useToast();

const services = ref<Services>({
	backend: { status: "unknown", message: "Checking..." },
	redis: { status: "unknown", message: "Checking..." },
	active_tasks: { status: "unknown", message: "Checking..." },
});

const serviceEntries = computed(() =>
	Object.entries(services.value)
		.filter((entry): entry is [string, ServiceStatus] => Boolean(entry[1]))
		.map(([key, service]) => ({ key, service })),
);

let statusInterval: number | null = null;
let lastStatusCheckFailed = false;

const getStatusClass = (status: ServiceState) => {
	switch (status) {
		case "busy":
			return "bg-fuchsia-100 text-fuchsia-800";
		case "running":
			return "bg-green-100 text-green-800";
		case "idle":
			return "bg-slate-100 text-slate-700";
		case "error":
			return "bg-red-100 text-red-800";
		default:
			return "bg-gray-100 text-gray-800";
	}
};

const getStatusDotClass = (status: ServiceState) => {
	switch (status) {
		case "busy":
			return "bg-fuchsia-500 animate-pulse";
		case "running":
			return "bg-green-500";
		case "idle":
			return "bg-slate-400";
		case "error":
			return "bg-red-500";
		default:
			return "bg-gray-400";
	}
};

const formatServiceName = (key: string) => {
	if (key === "active_tasks") return "active tasks";
	return key;
};

const checkStatus = async () => {
	try {
		const response = await getServiceStatus();
		const oldStatus = { ...services.value };
		const nextServices = response.data as Services;
		services.value = nextServices;
		lastStatusCheckFailed = false;

		for (const [key, service] of Object.entries(nextServices)) {
			if (!service) continue;
			const oldStatusValue = oldStatus[key]?.status ?? "unknown";
			if (service.status === "error" && oldStatusValue !== "error") {
				toast({
					title: "Service warning",
					description: `${formatServiceName(key)}: ${service.message}`,
					variant: "destructive",
				});
			}
		}
	} catch (error) {
		console.error("Failed to check service status:", error);
		services.value = {
			backend: { status: "error", message: "Backend status request timed out" },
			redis: { status: "unknown", message: "Redis status unknown" },
			active_tasks: {
				status: "unknown",
				message: "Active task status unknown",
			},
		};
		if (!lastStatusCheckFailed) {
			toast({
				title: "Service warning",
				description: "Cannot reach backend status endpoint.",
				variant: "destructive",
			});
		}
		lastStatusCheckFailed = true;
	}
};

onMounted(() => {
	void checkStatus();
	statusInterval = window.setInterval(checkStatus, 30000);
});

onUnmounted(() => {
	if (statusInterval) {
		clearInterval(statusInterval);
	}
});
</script>
