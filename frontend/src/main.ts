import { createPinia } from "pinia";
import { createApp } from "vue";
import "@/assets/style.css";
import App from "@/App.vue";
import router from "@/router";
import piniaPluginPersistedstate from "pinia-plugin-persistedstate";
import { installArtifactEditChatDomPatch } from "@/utils/artifactEditChatDom";
import { installCompactTimelineDomPatch } from "@/utils/compactTimelineDom";
import { installChatArtifactLinkDomPatch } from "@/utils/chatArtifactLinkDom";
import { installImageGalleryTitleDomPatch } from "@/utils/imageGalleryTitleDom";
import { installModelingDiscussionSync } from "@/utils/modelingDiscussionSync";
import { installChatPhaseDividerDomPatch } from "@/utils/chatPhaseDividerDom";
import { installChatAgentDuplicateDomPatch } from "@/utils/chatAgentDuplicateDom";
import { installChatChoiceCardDomPatch } from "@/utils/chatChoiceCardDom";

const pinia = createPinia();
pinia.use(piniaPluginPersistedstate);
const app = createApp(App);

app.use(router);
app.use(pinia);
app.mount("#app");

installArtifactEditChatDomPatch();
installCompactTimelineDomPatch();
installChatArtifactLinkDomPatch();
installImageGalleryTitleDomPatch();
installModelingDiscussionSync();
installChatPhaseDividerDomPatch();
installChatAgentDuplicateDomPatch();
installChatChoiceCardDomPatch();
