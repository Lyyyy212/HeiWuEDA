import { readFile } from "node:fs/promises";
import path from "node:path";

import { CANVAS_BRAND_NAME } from "../../shared/branding.mjs";
import { pluginPath } from "./plugin-root.mjs";

const PREBUILT_WIDGET_FILE = pluginPath(
  "mcp",
  "generated",
  "hardware-learning-widget.html",
);

export const HARDWARE_LEARNING_STATIC_BUILD_DIR = path.dirname(PREBUILT_WIDGET_FILE);

let cachedStaticHtml = "";

export async function hardwareLearningStaticHtml() {
  if (cachedStaticHtml) return cachedStaticHtml;

  try {
    cachedStaticHtml = await readFile(PREBUILT_WIDGET_FILE, "utf8");
  } catch (error) {
    if (error?.code === "ENOENT") {
      throw new Error(
        "The JLC Hardware Learning widget artifact is missing. Run npm run build:artifacts before publishing the plugin.",
      );
    }
    throw error;
  }

  if (!cachedStaticHtml.includes(CANVAS_BRAND_NAME)) {
    throw new Error("The JLC Hardware Learning widget artifact is invalid.");
  }

  return cachedStaticHtml;
}
