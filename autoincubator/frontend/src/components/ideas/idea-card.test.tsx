import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { sourceUrls } from "@/lib/ideas";
import { idea } from "@/test/fixtures";

import { IdeaCard } from "./idea-card";

describe("IdeaCard", () => {
  it("shows rank, title, pitch, score, rubric, failure cause and source count", () => {
    render(<IdeaCard idea={idea()} />);
    const card = screen.getByRole("article", { name: "Receipt-to-ledger for cafés" });
    expect(within(card).getByText("#1")).toBeInTheDocument();
    expect(within(card).getByText(/Photograph paper receipts/)).toBeInTheDocument();
    expect(within(card).getByText("7.4")).toBeInTheDocument();
    expect(within(card).getByLabelText("Defensibility: 3 of 10")).toBeInTheDocument();
    expect(within(card).getByText(/bundle the same feature/)).toBeInTheDocument();
    // a, b (signals) + a (TAM, duplicate) + c (SAM) + d (competitor); SOM is an assumption.
    expect(within(card).getByText("4")).toBeInTheDocument();
    expect(within(card).getByText("sources")).toBeInTheDocument();
  });
});

describe("sourceUrls", () => {
  it("counts each cited URL once across signals and figures", () => {
    expect(sourceUrls(idea()).sort()).toEqual([
      "https://example.com/a",
      "https://example.com/b",
      "https://example.com/c",
      "https://example.com/d",
    ]);
  });
});
