import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const templatePath = process.env.OPENCLAW_TEMPLATE_PATH || "/opt/clawharness/openclaw.json.template";
const outputPath = process.env.OPENCLAW_CONFIG_PATH || "/home/node/.openclaw/openclaw.json";
const placeholderPattern = /\$\{([A-Z0-9_]+)\}/g;

const template = readFileSync(templatePath, "utf8");
const missing = new Set();
const rendered = template.replace(placeholderPattern, (placeholder, name) => {
  const value = process.env[name];
  if (!value) {
    missing.add(name);
    return placeholder;
  }
  return value;
});

if (missing.size > 0) {
  const message = Array.from(missing).sort().join(", ");
  console.error(`Missing required environment variables for OpenClaw config: ${message}`);
  process.exit(1);
}

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, rendered, "utf8");
