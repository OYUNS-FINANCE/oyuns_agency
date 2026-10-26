import { describe, expect, it } from "vitest";

import { toBody, toValues } from "./llm-settings-form";
import type { LLMSettingsView } from "@/lib/api/types";

const view: LLMSettingsView = {
  provider: "openai",
  base_url: "https://gw.example/v1",
  models: {
    scout_model: "gpt-5-mini",
    analyst_model: "gpt-5",
    skeptic_model: "gpt-5",
    product_architect_model: "gpt-5",
    gtm_strategist_model: "gpt-5",
    financial_modeler_model: "gpt-5",
    editor_model: "gpt-5",
  },
  anthropic_key: { is_set: false },
  openai_key: { is_set: true, hint: "1234", source: "ui" },
  source: "ui",
  updated_at: "2026-10-26T00:00:00Z",
};

describe("llm settings form mapping", () => {
  it("sends no key when the field is untouched", () => {
    expect(toBody(toValues(view))).toEqual({
      ok: true,
      body: {
        provider: "openai",
        base_url: "https://gw.example/v1",
        models: view.models,
        api_key: null,
        clear_api_key: false,
      },
    });
  });

  it("sends a typed key, trimmed, and ignores remove when replacing", () => {
    const result = toBody({ ...toValues(view), apiKey: "  sk-new  ", clearKey: true });
    expect(result).toMatchObject({ ok: true, body: { api_key: "sk-new", clear_api_key: false } });
  });

  it("clears the key on request and turns a blank URL into null", () => {
    const result = toBody({ ...toValues(view), clearKey: true, baseUrl: " " });
    expect(result).toMatchObject({ ok: true, body: { base_url: null, clear_api_key: true } });
  });

  it("rejects non-http URLs and blank models", () => {
    const values = toValues(view);
    expect(toBody({ ...values, baseUrl: "ftp://x" })).toMatchObject({
      ok: false,
      errors: { baseUrl: expect.any(String) },
    });
    expect(toBody({ ...values, models: { ...values.models, editor_model: " " } })).toMatchObject({
      ok: false,
      errors: { models: expect.any(String) },
    });
  });
});
