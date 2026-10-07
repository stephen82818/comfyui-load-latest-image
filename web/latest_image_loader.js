import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// After a successful run, refresh each Load Latest Image node's preview with the
// newest edit, so the node shows the image the next run will start from.

const ranByPrompt = new Map(); // prompt_id -> [{ node, display_node }]

app.registerExtension({
    name: "LatestImageLoader.RefreshAfterRun",
    setup() {
        api.addEventListener("executed", ({ detail }) => {
            if (!detail?.output?.latest_image_loader) return;
            const ran = ranByPrompt.get(detail.prompt_id) ?? [];
            ran.push({ node: detail.node, display_node: detail.display_node ?? detail.node });
            ranByPrompt.set(detail.prompt_id, ran);
        });

        const forget = ({ detail }) => ranByPrompt.delete(detail?.prompt_id);
        api.addEventListener("execution_error", forget);
        api.addEventListener("execution_interrupted", forget);

        api.addEventListener("execution_success", async ({ detail }) => {
            const ran = ranByPrompt.get(detail?.prompt_id);
            ranByPrompt.delete(detail?.prompt_id);
            for (const { node, display_node } of ran ?? []) {
                try {
                    const res = await api.fetchApi("/latest_image_loader/refresh", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ node_id: node }),
                    });
                    const { images } = await res.json();
                    if (!images?.length) continue;
                    // Reuse the normal "executed" path so the preview updates like any node output.
                    api.dispatchCustomEvent("executed", {
                        node,
                        display_node,
                        output: { images },
                        prompt_id: detail.prompt_id,
                    });
                } catch (e) {
                    console.warn("[LatestImageLoader] Preview refresh failed:", e);
                }
            }
        });
    },
});
