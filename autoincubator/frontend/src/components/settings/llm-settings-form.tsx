"use client";

import { Check, Loader2, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Segmented } from "@/components/common/segmented";
import { ErrorState, LoadingState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useLlmCatalog,
  useLlmSettings,
  useResetLlmSettings,
  useSaveLlmSettings,
  useTestLlmSettings,
} from "@/lib/api/queries";
import type {
  AgentModels,
  LLMCatalog,
  LLMProviderName,
  LLMSettingsUpdate,
  LLMSettingsView,
} from "@/lib/api/types";
import { describeError, formatDateTime } from "@/lib/format";

const PROVIDERS = [
  { value: "anthropic", label: "Anthropic" },
  { value: "openai", label: "OpenAI / compatible" },
  { value: "fake", label: "Offline demo" },
] as const satisfies readonly { value: LLMProviderName; label: string }[];

export const AGENTS = [
  { key: "scout_model", label: "Scout", hint: "High volume: a cheap model is fine." },
  { key: "analyst_model", label: "Analyst", hint: "" },
  { key: "skeptic_model", label: "Skeptic", hint: "Judgement-heavy: use a strong model." },
  { key: "product_architect_model", label: "Product architect", hint: "" },
  { key: "gtm_strategist_model", label: "GTM strategist", hint: "" },
  { key: "financial_modeler_model", label: "Financial modeler", hint: "" },
  { key: "editor_model", label: "Editor", hint: "Judgement-heavy: use a strong model." },
] as const satisfies readonly { key: keyof AgentModels; label: string; hint: string }[];

export interface LlmValues {
  provider: LLMProviderName;
  baseUrl: string;
  apiKey: string;
  clearKey: boolean;
  models: AgentModels;
}

export function toValues(view: LLMSettingsView): LlmValues {
  return {
    provider: view.provider,
    baseUrl: view.base_url ?? "",
    apiKey: "",
    clearKey: false,
    models: view.models,
  };
}

export type FieldErrors = Partial<Record<"baseUrl" | "models", string>>;

/** Maps the form to the API body, or returns field errors. Exported for tests. */
export function toBody(
  values: LlmValues,
): { ok: true; body: LLMSettingsUpdate } | { ok: false; errors: FieldErrors } {
  const errors: FieldErrors = {};
  const baseUrl = values.baseUrl.trim();
  if (baseUrl !== "") {
    try {
      const url = new URL(baseUrl);
      if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("scheme");
    } catch {
      errors.baseUrl = "Enter an http(s) URL, e.g. https://host/v1";
    }
  }
  if (Object.values(values.models).some((m) => m.trim() === "")) {
    errors.models = "Every agent needs a model.";
  }
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  const key = values.apiKey.trim();
  return {
    ok: true,
    body: {
      provider: values.provider,
      base_url: baseUrl === "" ? null : baseUrl,
      models: Object.fromEntries(
        Object.entries(values.models).map(([k, v]) => [k, v.trim()]),
      ) as AgentModels,
      api_key: key === "" ? null : key,
      clear_api_key: values.clearKey && key === "",
    },
  };
}

function sameModels(a: AgentModels, b: AgentModels): boolean {
  return AGENTS.every(({ key }) => a[key] === b[key]);
}

function Editor({ saved, catalog }: { saved: LLMSettingsView; catalog: LLMCatalog }) {
  const save = useSaveLlmSettings();
  const reset = useResetLlmSettings();
  const test = useTestLlmSettings();
  const [values, setValues] = useState<LlmValues>(() => toValues(saved));
  const [errors, setErrors] = useState<FieldErrors>({});
  const [dirty, setDirty] = useState(false);

  const edit = (patch: Partial<LlmValues>) => {
    setValues((prev) => ({ ...prev, ...patch }));
    setErrors({});
    setDirty(true);
    test.reset();
  };

  function onProvider(provider: LLMProviderName) {
    const prevPreset = values.provider === "fake" ? undefined : catalog.presets[values.provider];
    const nextPreset = provider === "fake" ? undefined : catalog.presets[provider];
    // Swap to the new provider's preset only if the models are still the old provider's.
    const swap = nextPreset && (!prevPreset || sameModels(values.models, prevPreset));
    edit({
      provider,
      clearKey: false,
      apiKey: "",
      ...(swap ? { models: nextPreset } : {}),
    });
  }

  const keyStatus =
    values.provider === "anthropic"
      ? saved.anthropic_key
      : values.provider === "openai"
        ? saved.openai_key
        : null;
  const preset = values.provider === "fake" ? undefined : catalog.presets[values.provider];
  const suggestions = catalog.models.filter((m) => m.provider === values.provider);
  const needsKey = values.provider !== "fake";
  const keyAvailable =
    values.apiKey.trim() !== "" || (keyStatus?.is_set === true && !values.clearKey);

  function submit(event: FormEvent) {
    event.preventDefault();
    const result = toBody(values);
    if (!result.ok) {
      setErrors(result.errors);
      return;
    }
    save.mutate(result.body, {
      onSuccess: (view) => {
        setValues(toValues(view));
        setDirty(false);
      },
    });
  }

  function runTest() {
    const result = toBody(values);
    if (!result.ok) {
      setErrors(result.errors);
      return;
    }
    test.mutate(result.body);
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-6">
      <div className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">Provider</span>
        <Segmented
          label="Provider"
          value={values.provider}
          options={PROVIDERS}
          onChange={onProvider}
          className="w-full sm:w-fit"
        />
        {values.provider === "fake" && (
          <p className="text-muted-foreground text-xs">
            Canned responses, no network and no key. Useful to try the app; the ideas are not real.
          </p>
        )}
      </div>

      {needsKey && (
        <>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="api-key">API key</Label>
            <div className="flex gap-2">
              <Input
                id="api-key"
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={values.apiKey}
                placeholder={
                  keyStatus?.is_set && !values.clearKey
                    ? `Set (…${keyStatus.hint ?? ""}) — type to replace`
                    : values.provider === "anthropic"
                      ? "sk-ant-…"
                      : "sk-…"
                }
                onChange={(event) => edit({ apiKey: event.target.value, clearKey: false })}
                className="font-mono"
              />
              {keyStatus?.is_set && keyStatus.source === "ui" && !values.clearKey && (
                <Button type="button" variant="outline" onClick={() => edit({ clearKey: true })}>
                  Remove
                </Button>
              )}
            </div>
            <p className="text-muted-foreground text-xs">
              {values.clearKey
                ? "The saved key will be removed when you save."
                : keyStatus?.is_set
                  ? keyStatus.source === "ui"
                    ? "Stored encrypted. It is never shown again."
                    : "Currently taken from the server environment; a key saved here takes priority."
                  : "No key yet. Stored encrypted on the server and never shown again."}
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="base-url">Base URL (optional)</Label>
            <Input
              id="base-url"
              inputMode="url"
              value={values.baseUrl}
              placeholder={
                values.provider === "openai"
                  ? "https://api.openai.com/v1 — or an OpenAI-compatible gateway"
                  : "https://api.anthropic.com"
              }
              aria-invalid={errors.baseUrl ? true : undefined}
              onChange={(event) => edit({ baseUrl: event.target.value })}
              className="font-mono"
            />
            {errors.baseUrl && <p className="text-destructive text-sm">{errors.baseUrl}</p>}
            {values.provider === "openai" && values.baseUrl.trim() !== "" && (
              <p className="text-muted-foreground text-xs">
                The endpoint must support strict JSON-schema structured output. Models without a
                known price are not counted in the cost cap.
              </p>
            )}
          </div>
        </>
      )}

      <fieldset className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <legend className="text-sm font-medium">Model per agent</legend>
          {preset && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => edit({ models: preset })}
            >
              Use recommended
            </Button>
          )}
        </div>
        <datalist id="model-suggestions">
          {suggestions.map((m) => (
            <option key={m.id} value={m.id}>
              {`$${m.input_per_mtok} in / $${m.output_per_mtok} out per M tokens`}
            </option>
          ))}
        </datalist>
        <div className="grid gap-3 sm:grid-cols-2">
          {AGENTS.map(({ key, label, hint }) => (
            <div key={key} className="flex flex-col gap-1">
              <Label htmlFor={key}>{label}</Label>
              <Input
                id={key}
                list="model-suggestions"
                value={values.models[key]}
                spellCheck={false}
                onChange={(event) =>
                  edit({ models: { ...values.models, [key]: event.target.value } })
                }
                className="font-mono"
              />
              {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
            </div>
          ))}
        </div>
        {errors.models && <p className="text-destructive text-sm">{errors.models}</p>}
      </fieldset>

      {test.data && (
        <p
          role="status"
          className={
            test.data.ok
              ? "text-signal flex items-center gap-1.5 text-sm"
              : "text-destructive flex items-start gap-1.5 text-sm"
          }
        >
          {test.data.ok ? (
            <Check className="size-4" aria-hidden />
          ) : (
            <X className="mt-0.5 size-4 shrink-0" aria-hidden />
          )}
          <span>
            {test.data.ok
              ? `${test.data.message} ${test.data.model}${test.data.latency_ms != null ? ` answered in ${test.data.latency_ms} ms.` : ""}`
              : `${test.data.model}: ${test.data.message}`}
          </span>
        </p>
      )}
      {test.isError && (
        <p role="alert" className="text-destructive text-sm">
          Could not run the test: {describeError(test.error)}
        </p>
      )}
      {save.isError && (
        <p role="alert" className="text-destructive text-sm">
          Could not save: {describeError(save.error)}
        </p>
      )}
      {reset.isError && (
        <p role="alert" className="text-destructive text-sm">
          Could not reset: {describeError(reset.error)}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={save.isPending || !dirty}>
          {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
          Save
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={runTest}
          disabled={test.isPending || (needsKey && !keyAvailable)}
        >
          {test.isPending && <Loader2 className="animate-spin" aria-hidden />}
          Test connection
        </Button>
        {saved.source === "ui" && (
          <Button
            type="button"
            variant="ghost"
            disabled={reset.isPending}
            onClick={() =>
              reset.mutate(undefined, {
                onSuccess: (view) => {
                  setValues(toValues(view));
                  setDirty(false);
                  test.reset();
                },
              })
            }
          >
            Use server environment
          </Button>
        )}
        <span role="status" className="text-muted-foreground flex items-center gap-1 text-xs">
          {save.isSuccess && !dirty ? (
            <>
              <Check className="text-signal size-3.5" aria-hidden /> Saved
            </>
          ) : saved.updated_at ? (
            `Last saved ${formatDateTime(saved.updated_at)}`
          ) : (
            "Using the server environment — nothing saved yet"
          )}
        </span>
      </div>
    </form>
  );
}

export function LlmSettingsForm() {
  const settings = useLlmSettings();
  const catalog = useLlmCatalog();
  if (settings.isPending || catalog.isPending) return <LoadingState label="Loading settings…" />;
  const error = settings.error ?? catalog.error;
  if (error || !settings.data || !catalog.data) {
    return (
      <ErrorState
        title="Could not load the model settings"
        message={describeError(error)}
        onRetry={() => {
          void settings.refetch();
          void catalog.refetch();
        }}
      />
    );
  }
  // Remount after a save/reset so the form always starts from the stored values.
  return (
    <Editor
      key={`${settings.data.source}-${settings.data.updated_at ?? "env"}`}
      saved={settings.data}
      catalog={catalog.data}
    />
  );
}
