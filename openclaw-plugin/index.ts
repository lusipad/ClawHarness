import { Type } from "@sinclair/typebox";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

export default definePluginEntry({
  id: "clawharness",
  name: "ClawHarness",
  description: "Adds ClawHarness skills and bridge health tools for Azure DevOps task automation.",
  register(api) {
    api.registerTool(
      {
        name: "harness_ping",
        description: "Return a static readiness note for the ClawHarness plugin.",
        parameters: Type.Object({}),
        async execute() {
          return {
            content: [
              {
                type: "text",
                text: "ClawHarness plugin loaded. Use the bridge service for Azure DevOps webhook intake.",
              },
            ],
          };
        },
      },
      { optional: true },
    );

    api.registerTool(
      {
        name: "harness_bridge_health",
        description: "Check the local harness bridge /readyz endpoint.",
        parameters: Type.Object({
          baseUrl: Type.String(),
          token: Type.Optional(Type.String()),
        }),
        async execute(_id, params) {
          const headers: Record<string, string> = { Accept: "application/json" };
          if (params.token) {
            headers.Authorization = `Bearer ${params.token}`;
          }
          const response = await fetch(`${params.baseUrl.replace(/\/$/, "")}/readyz`, { headers });
          const text = await response.text();
          return {
            content: [
              {
                type: "text",
                text: `status=${response.status} body=${text}`,
              },
            ],
          };
        },
      },
      { optional: true },
    );
  },
});
