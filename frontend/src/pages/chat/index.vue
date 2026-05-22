<script setup lang="ts">
import { getHelloWorld } from "@/apis/commonApi";
import AppSidebar from "@/components/AppSidebar.vue";
import ModelingExamples from "@/components/ModelingExamples.vue";
import ServiceStatus from "@/components/ServiceStatus.vue";
import UserStepper from "@/components/UserStepper.vue";
import Button from "@/components/ui/button/Button.vue";
import {
	SidebarInset,
	SidebarProvider,
	SidebarTrigger,
} from "@/components/ui/sidebar";
import MoreDetail from "@/pages/chat/components/MoreDetail.vue";
import { useApiKeyStore } from "@/stores/apiKeys";
import { CircleEllipsis } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";

// ---- Reactive State ----

const isMoreDetailOpen = ref(false);
const apiKeyStore = useApiKeyStore();
const modelSummary = computed(() => {
	const config = apiKeyStore.coordinatorConfig;
	return `${config.apiType} / ${config.modelId}`;
});

// ---- Lifecycle Hooks ----

onMounted(() => {
	getHelloWorld().then((res) => {
		console.log(res.data);
	});
});
</script>

<template>

  <SidebarProvider>
    <MoreDetail v-model="isMoreDetailOpen" />
    <AppSidebar />
    <SidebarInset>
      <header class="flex h-16 shrink-0 items-center gap-2 px-4">
        <SidebarTrigger class="-ml-1" />
        <div class="flex justify-between w-full gap-2">
          <ServiceStatus />
          <div class="flex gap-2">
            <Button variant="outline" @click="isMoreDetailOpen = true">
              <CircleEllipsis />
              更多
            </Button>
          </div>
        </div>
      </header>

      <div class="py-5 px-4">
        <div class="space-y-6">
          <div class="text-center space-y-2 mb-10">
            <h1 class="text-2xl font-semibold">MathModelAgent</h1>
            <p class="text-muted-foreground">
              让 Agent 数学建模，代码编写，论文写作
            </p>
          </div>

          <UserStepper>
          </UserStepper>
          <div class="text-center text-xs text-muted-foreground mt-8">
            当前模型：{{ modelSummary }}
          </div>
          <ModelingExamples />
        </div>
      </div>
    </SidebarInset>
  </SidebarProvider>
</template>
