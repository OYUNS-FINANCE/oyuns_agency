import type { Metadata } from "next";

import { LlmSettingsForm } from "@/components/settings/llm-settings-form";

export const metadata: Metadata = { title: "Models" };

export default function LlmSettingsPage() {
  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="font-serif text-3xl tracking-tight">Models</h1>
        <p className="text-muted-foreground text-sm">
          Choose the LLM provider, its API key and the model each agent uses. Changes apply to runs
          started afterwards; a run already in progress keeps its configuration.
        </p>
      </header>
      <LlmSettingsForm />
    </div>
  );
}
