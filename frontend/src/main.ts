import { createPinia } from "pinia";
import { createApp } from "vue";
import "@/assets/style.css";
import App from "@/App.vue";
import router from "@/router";
import piniaPluginPersistedstate from "pinia-plugin-persistedstate";
import { installQuestionRepairStatusDomPatch } from "@/utils/questionRepairStatusDom";
import { installAgentFlowDisplayCleanerDomPatch } from "@/utils/agentFlowDisplayCleanerDom";

const pinia = createPinia();
pinia.use(piniaPluginPersistedstate);
const app = createApp(App);

app.use(router);
app.use(pinia);
app.mount("#app");

installQuestionRepairStatusDomPatch();
installAgentFlowDisplayCleanerDomPatch();
