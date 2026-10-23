"use client";

import { X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

import { cn } from "@/lib/utils";

/** Free-text list entry: Enter or comma adds a chip, Backspace on an empty field removes one. */
export function ChipInput({
  id,
  values,
  onChange,
  placeholder,
  className,
}: {
  id: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  className?: string;
}) {
  const [draft, setDraft] = useState("");

  function commit() {
    const value = draft.trim().replace(/,$/, "").trim();
    setDraft("");
    if (!value || values.some((v) => v.toLowerCase() === value.toLowerCase())) return;
    onChange([...values, value]);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commit();
    } else if (event.key === "Backspace" && draft === "" && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  }

  return (
    <div
      className={cn(
        "border-input focus-within:border-ring focus-within:ring-ring/50 dark:bg-input/30 flex min-h-9 flex-wrap items-center gap-1.5 rounded-lg border bg-transparent px-2 py-1.5 focus-within:ring-3",
        className,
      )}
    >
      {values.map((value) => (
        <span
          key={value}
          className="bg-secondary text-secondary-foreground inline-flex items-center gap-1 rounded-md py-0.5 pr-1 pl-2 text-xs"
        >
          {value}
          <button
            type="button"
            aria-label={`Remove ${value}`}
            onClick={() => onChange(values.filter((v) => v !== value))}
            className="hover:bg-foreground/10 rounded-sm p-0.5"
          >
            <X className="size-3" aria-hidden />
          </button>
        </span>
      ))}
      <input
        id={id}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
        onBlur={commit}
        placeholder={values.length === 0 ? placeholder : undefined}
        className="placeholder:text-muted-foreground min-w-24 flex-1 bg-transparent text-sm outline-none"
      />
    </div>
  );
}
