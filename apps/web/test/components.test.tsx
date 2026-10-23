// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";

import { cleanup, render, screen } from "@testing-library/react";
import { DollarSignIcon } from "lucide-react";
import { afterEach, describe, expect, it } from "vitest";

import { AllocationView, TraceView, WarningsView } from "@/components/engine-views";
import { EmptyState } from "@/components/empty-state";
import { KpiTile } from "@/components/kpi-tile";
import { TokenBar } from "@/components/token-bar";

afterEach(cleanup);

describe("KpiTile", () => {
  it("shows the value and marks rising spend as bad", () => {
    render(<KpiTile label="Spend" icon={DollarSignIcon} value="$135.03" current={135} previous={100} goodWhen="down" comparison="vs prior 30d" />);
    expect(screen.getByText("$135.03")).toBeInTheDocument();
    const chip = screen.getByText("+35%");
    expect(chip.className).toMatch(/warning/);
  });

  it("marks a rising cache hit rate as good", () => {
    render(<KpiTile label="Cache hit rate" icon={DollarSignIcon} value="27.1%" current={27.1} previous={24.2} goodWhen="up" comparison="vs prior 30d" />);
    expect(screen.getByText("+12%").className).toMatch(/savings/);
  });

  it("says New when there is no previous period", () => {
    render(<KpiTile label="Requests" icon={DollarSignIcon} value="12" current={12} previous={0} comparison="vs prior 30d" />);
    expect(screen.getByText("New")).toBeInTheDocument();
  });

  it("renders skeletons while loading", () => {
    const { container } = render(<KpiTile label="Spend" icon={DollarSignIcon} value="$1" current={1} previous={1} comparison="x" loading />);
    expect(screen.queryByText("$1")).not.toBeInTheDocument();
    expect(container.querySelectorAll("[data-slot='skeleton'], .animate-pulse").length).toBeGreaterThan(0);
  });
});

describe("EmptyState", () => {
  it("always explains itself and offers an action", () => {
    render(<EmptyState icon={DollarSignIcon} title="No budgets yet" description="Budgets stop spend before it happens." action={<button type="button">New budget</button>} />);
    expect(screen.getByText("No budgets yet")).toBeInTheDocument();
    expect(screen.getByText(/stop spend/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New budget" })).toBeInTheDocument();
  });
});


describe("engine views", () => {
  it("shows each pipeline stage with its token change", () => {
    render(
      <TraceView
        trace={[
          { stage: "clean", tokens_before: 9000, tokens_after: 2000, items_removed: 5, ms: 0.4, notes: ["dedup"] },
          { stage: "validate", tokens_before: 2000, tokens_after: 2000, items_removed: 0, ms: 1.2, notes: [] },
        ]}
      />,
    );
    expect(screen.getByText("Clean")).toBeInTheDocument();
    expect(screen.getByText("-7K")).toBeInTheDocument();
    expect(screen.getByText("5 items removed")).toBeInTheDocument();
  });

  it("explains an unallocated budget and lists categories", () => {
    render(<AllocationView allocation={[{ category: "history", weight: 0.6, budget: 0, used: 0 }]} />);
    expect(screen.getByText(/Everything fit after cleaning/)).toBeInTheDocument();
    expect(screen.getByText("History")).toBeInTheDocument();
  });

  it("says clearly when there are no warnings", () => {
    render(<WarningsView warnings={[]} />);
    expect(screen.getByText(/No warnings/)).toBeInTheDocument();
  });

  it("labels before and after token counts", () => {
    render(<TokenBar before={1000} after={250} budget={400} />);
    expect(screen.getByLabelText("1,000 tokens before, 250 after")).toBeInTheDocument();
  });
});
