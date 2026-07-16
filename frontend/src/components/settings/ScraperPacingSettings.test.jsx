import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ScraperPacingSettings from "./ScraperPacingSettings";

const settingsItems = ["jobsdb", "ctgoodjobs", "offertoday"].map((source_site) => ({
  source_site,
  interval_min_seconds: 1,
  interval_max_seconds: 3,
  burst_size: 20,
  burst_pause_seconds: 30,
}));

function jsonResponse(payload, { ok = true, status = 200 } = {}) {
  return Promise.resolve({ ok, status, json: async () => payload });
}

function sourceCard(name) {
  return screen.getByRole("heading", { level: 2, name }).closest("article");
}

describe("ScraperPacingSettings", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = String(input);
      const method = init.method || "GET";
      if (method === "GET") {
        return jsonResponse({ items: settingsItems, active_detail_task_count: 2 });
      }
      const source = url.split("/").at(-1) === "reset" ? url.split("/").at(-2) : url.split("/").at(-1);
      if (method === "POST") {
        return jsonResponse({ ...settingsItems.find((item) => item.source_site === source) });
      }
      return jsonResponse({ source_site: source, ...JSON.parse(init.body) });
    });
  });

  afterEach(() => vi.restoreAllMocks());

  it("renders independent source cards and the active-detail warning", async () => {
    const onOpenCrawlTasks = vi.fn();
    render(<ScraperPacingSettings onOpenCrawlTasks={onOpenCrawlTasks} />);

    expect(await screen.findByRole("heading", { name: "Scraper Pacing" })).toBeInTheDocument();
    expect(screen.getByText("2 active manual detail tasks")).toBeInTheDocument();
    expect(sourceCard("JobsDB")).toBeInTheDocument();
    expect(sourceCard("CTGoodJobs")).toBeInTheDocument();
    expect(sourceCard("OfferToday")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open Crawl Tasks" }));
    expect(onOpenCrawlTasks).toHaveBeenCalledOnce();
  });

  it("saves only the edited source and rebuilds that card from the server response", async () => {
    render(<ScraperPacingSettings />);
    const card = await waitFor(() => sourceCard("CTGoodJobs"));
    const minimum = within(card).getByLabelText("CTGoodJobs Minimum interval");

    fireEvent.change(minimum, { target: { value: "2.5" } });
    fireEvent.click(within(card).getByRole("button", { name: "Save CTGoodJobs" }));

    await waitFor(() => expect(within(card).getByText("Settings saved.")).toBeInTheDocument());
    const putCall = globalThis.fetch.mock.calls.find(([, init]) => init.method === "PUT");
    expect(String(putCall[0])).toMatch(/scraper-pacing\/ctgoodjobs$/);
    expect(JSON.parse(putCall[1].body)).toMatchObject({ interval_min_seconds: 2.5 });
    expect(screen.getByLabelText("JobsDB Minimum interval")).toHaveValue(1);
  });

  it("blocks invalid local values with accessible field feedback", async () => {
    render(<ScraperPacingSettings />);
    const card = await waitFor(() => sourceCard("OfferToday"));

    fireEvent.change(within(card).getByLabelText("OfferToday Minimum interval"), { target: { value: "8" } });
    fireEvent.change(within(card).getByLabelText("OfferToday Maximum interval"), { target: { value: "3" } });

    expect(within(card).getByText("Maximum must be greater than or equal to minimum.")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Save OfferToday" })).toBeDisabled();
  });

  it("resets one source from the server response without changing another card", async () => {
    render(<ScraperPacingSettings />);
    const card = await waitFor(() => sourceCard("OfferToday"));
    fireEvent.change(within(card).getByLabelText("OfferToday Burst pause"), { target: { value: "99" } });

    fireEvent.click(within(card).getByRole("button", { name: "Reset defaults" }));

    await waitFor(() => expect(within(card).getByText("Defaults restored.")).toBeInTheDocument());
    expect(within(card).getByLabelText("OfferToday Burst pause")).toHaveValue(30);
    expect(screen.getByLabelText("JobsDB Burst pause")).toHaveValue(30);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/settings/scraper-pacing/offertoday/reset",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("renders backend validation details as an alert", async () => {
    globalThis.fetch = vi.fn((input, init = {}) => {
      if ((init.method || "GET") === "GET") {
        return jsonResponse({ items: settingsItems, active_detail_task_count: 0 });
      }
      return jsonResponse({ detail: "source setting was rejected" }, { ok: false, status: 422 });
    });
    render(<ScraperPacingSettings />);
    const card = await waitFor(() => sourceCard("JobsDB"));
    fireEvent.change(within(card).getByLabelText("JobsDB Burst size"), { target: { value: "21" } });
    fireEvent.click(within(card).getByRole("button", { name: "Save JobsDB" }));

    expect(await within(card).findByRole("alert")).toHaveTextContent("source setting was rejected");
  });
});
