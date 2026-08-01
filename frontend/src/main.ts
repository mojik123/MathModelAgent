import { createPinia } from "pinia";
import { createApp } from "vue";
import "@/assets/style.css";
import App from "@/App.vue";
import router from "@/router";
import { installArtifactEditChatDomPatch } from "@/utils/artifactEditChatDom";
import { installArtifactEditSelectionCleanupDomPatch } from "@/utils/artifactEditSelectionCleanupDom";
import { installImageGalleryTitleDomPatch } from "@/utils/imageGalleryTitleDom";
import { installModelingDiscussionSync } from "@/utils/modelingDiscussionSync";
import { installPaperPreviewDomPatch } from "@/utils/paperPreviewDom";
import { installPaperPreviewLayoutDomPatch } from "@/utils/paperPreviewLayoutDom";
import { installPaperPreviewMathCleanupDomPatch } from "@/utils/paperPreviewMathCleanupDom";
import { installTimelineArtifactScope } from "@/utils/timelineArtifactScope";
import piniaPluginPersistedstate from "pinia-plugin-persistedstate";

const pinia = createPinia();
pinia.use(piniaPluginPersistedstate);
const app = createApp(App);

app.use(router);
app.use(pinia);
app.mount("#app");

installTimelineArtifactScope();
installArtifactEditChatDomPatch();
installArtifactEditSelectionCleanupDomPatch();
installImageGalleryTitleDomPatch();
installModelingDiscussionSync();
installPaperPreviewDomPatch();
installPaperPreviewLayoutDomPatch();
installPaperPreviewMathCleanupDomPatch();
