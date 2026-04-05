import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const outputPath = process.argv[2] || process.env.CODEX_AUTH_PATH || "/home/node/.codex/auth.json";
const apiKey = process.env.OPENAI_API_KEY;

if (!apiKey) {
  console.error("Missing OPENAI_API_KEY for Codex auth");
  process.exit(1);
}

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(
  outputPath,
  JSON.stringify(
    {
      auth_mode: "apikey",
      OPENAI_API_KEY: apiKey,
    },
    null,
    2,
  ),
  "utf8",
);
