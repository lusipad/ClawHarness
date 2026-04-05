import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const outputPath = process.argv[2] || process.env.CODEX_CONFIG_PATH || "/home/node/.codex/config.toml";
const model = process.env.CODEX_MODEL || "gpt-5.4";
const reviewModel = process.env.CODEX_REVIEW_MODEL || "";
const reasoningEffort = process.env.CODEX_REASONING_EFFORT || "";
const openaiBaseUrl = process.env.OPENAI_BASE_URL || "";

const lines = [
  `model_provider = "openai"`,
  `model = ${JSON.stringify(model)}`,
];

if (reviewModel) {
  lines.push(`review_model = ${JSON.stringify(reviewModel)}`);
}

if (reasoningEffort) {
  lines.push(`model_reasoning_effort = ${JSON.stringify(reasoningEffort)}`);
}

if (openaiBaseUrl) {
  lines.push(`openai_base_url = ${JSON.stringify(openaiBaseUrl)}`);
}

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, `${lines.join("\n")}\n`, "utf8");
