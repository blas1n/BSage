import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

/**
 * Message-bundle parity for the BSage `sage` namespace.
 *
 * After the react-i18next -> `@bsvibe/i18n` migration the translations live
 * at `frontend/messages/sage.{en,ko}.json` and are layered as the `sage`
 * namespace by `i18n/request.ts`. This test guards against the two ways the
 * two files drift: a key that exists in one locale but not the other, and a
 * leaf string that is empty (an un-translated placeholder).
 */
const here = dirname(fileURLToPath(import.meta.url));
const messagesDir = join(here, "..", "messages");

function load(locale: string): Record<string, unknown> {
  return JSON.parse(readFileSync(join(messagesDir, `sage.${locale}.json`), "utf8"));
}

/** Flatten a nested message tree to dotted leaf paths -> string values. */
function flatten(obj: unknown, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  if (typeof obj === "string") {
    out[prefix] = obj;
    return out;
  }
  if (obj && typeof obj === "object") {
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      Object.assign(out, flatten(v, prefix ? `${prefix}.${k}` : k));
    }
  }
  return out;
}

test.describe("i18n message parity (sage namespace)", () => {
  const en = flatten(load("en"));
  const ko = flatten(load("ko"));

  test("en and ko have an identical key tree", () => {
    const enKeys = Object.keys(en).sort();
    const koKeys = Object.keys(ko).sort();
    expect(koKeys).toEqual(enKeys);
  });

  test("no leaf string is empty in either locale", () => {
    for (const [key, value] of Object.entries(en)) {
      expect(value.trim(), `en leaf "${key}" is empty`).not.toBe("");
    }
    for (const [key, value] of Object.entries(ko)) {
      expect(value.trim(), `ko leaf "${key}" is empty`).not.toBe("");
    }
  });
});
