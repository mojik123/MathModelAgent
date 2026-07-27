import { createPinia } from "pinia";
import { createApp } from "vue";
import "@/assets/style.css";
import App from "@/App.vue";
import router from "@/router";
import { installArtifactEditChatDomPatch } from "@/utils/artifactEditChatDom";
import { installChatAgentDuplicateDomPatch } from "@/utils/chatAgentDuplicateDom";
import { installChatArtifactLinkDomPatch } from "@/utils/chatArtifactLinkDom";
import { installChatChoiceCardDomPatch } from "@/utils/chatChoiceCardDom";
import { installChatPhaseDividerDomPatch } from "@/utils/chatPhaseDividerDom";
import { installCompactTimelineDomPatch } from "@/utils/compactTimelineDom";
import { installImageGalleryTitleDomPatch } from "@/utils/imageGalleryTitleDom";
import { installModelingDiscussionSync } from "@/utils/modelingDiscussionSync";
import { installPaperPreviewDomPatch } from "@/utils/paperPreviewDom";
import { installPaperPreviewLayoutDomPatch } from "@/utils/paperPreviewLayoutDom";
import { installSmoothStreamingTextDomPatch } from "@/utils/smoothStreamingTextDom";
import piniaPluginPersistedstate from "pinia-plugin-persistedstate";

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
installPaperPreviewDomPatch();
installPaperPreviewLayoutDomPatch();
installSmoothStreamingTextDomPatch();
