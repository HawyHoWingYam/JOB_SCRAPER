import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ScraperPacingSummary from "./ScraperPacingSummary";

describe("ScraperPacingSummary", () => {
  it("shows the selected source saved values as read-only task-start settings", () => {
    const onOpenSettings = vi.fn();
    render(
      <ScraperPacingSummary
        sourceSite="ctgoodjobs"
        settings={{
          interval_min_seconds: 1,
          interval_max_seconds: 3,
          burst_size: 20,
          burst_pause_seconds: 30,
        }}
        onOpenSettings={onOpenSettings}
      />,
    );

    expect(screen.getByText(/Saved Detail Pacing · CTGoodJobs/)).toBeInTheDocument();
    expect(screen.getByText("Random interval 1-3 seconds")).toBeInTheDocument();
    expect(screen.getByText("Burst 20 attempts")).toBeInTheDocument();
    expect(screen.getByText("Burst pause 30 seconds")).toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Scraper Pacing Settings" }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
  });
});
