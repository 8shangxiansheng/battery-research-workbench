/**
 * Flow-limit fixes: FeatureCatalogue family filter (Limit-2).
 * @vitest-environment jsdom
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

const clientMock = { listFeatureDefinitions: vi.fn() };
vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  client: clientMock,
}));

const { FeatureCatalogue } = await import("../src/components/workbench/FeatureCatalogue");

function entry(code: string, family: string, name = code) {
  return {
    code, display_name_en: name, display_name_zh: name, family, units: "a.u.",
    scope: ["frame"], definition_status: "DEFINED_AND_VALIDATED", parity_status: "PARITY_CONFIRMED",
    formula_text: "x", formula_policy_version: "v1", formula_source_id: "SRC::1",
    availability: "AVAILABLE",
  };
}

const CATALOGUE = [
  entry("amplitude_a_u", "RAW", "Amplitude"),
  entry("BOTTOM_AMP", "PHYSICAL", "Bottom amplitude"),
  entry("BPS", "PHASE", "Phase shift"),
  entry("TDM", "TD", "TD mass"),
  entry("FDM", "FD", "FD mass"),
];

function setup() {
  clientMock.listFeatureDefinitions.mockResolvedValue({
    data: { catalogue: CATALOGUE, formula_source_id: "SRC::1" }, meta: {},
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><FeatureCatalogue selected={[]} onToggle={() => {}} /></QueryClientProvider>);
}

describe("catalogue family filter (Limit-2)", () => {
  it("shows all five groups by default", async () => {
    setup();
    const sel = await screen.findByTestId("catalogue-family-filter");
    expect(sel).toHaveValue("all");
    expect(screen.getByTestId("catalogue-BOTTOM_AMP")).toBeInTheDocument();
    expect(screen.getByTestId("catalogue-TDM")).toBeInTheDocument();
    expect(screen.getByTestId("catalogue-FDM")).toBeInTheDocument();
    expect(screen.getByTestId("catalogue-amplitude_a_u")).toBeInTheDocument();
  });

  it("FD filter keeps only frequency-domain entries", async () => {
    setup();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByTestId("catalogue-family-filter"), "FD");
    expect(screen.getByTestId("catalogue-FDM")).toBeInTheDocument();
    expect(screen.queryByTestId("catalogue-TDM")).not.toBeInTheDocument();
    expect(screen.queryByTestId("catalogue-BOTTOM_AMP")).not.toBeInTheDocument();
    expect(screen.queryByTestId("catalogue-amplitude_a_u")).not.toBeInTheDocument();
  });

  it("physical filter + search compose", async () => {
    setup();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByTestId("catalogue-family-filter"), "physical");
    await user.type(screen.getByLabelText(/搜索特征/), "BPS");
    expect(screen.getByRole("status")).toHaveTextContent("没有匹配");
    expect(screen.queryByTestId("catalogue-BOTTOM_AMP")).not.toBeInTheDocument();
  });
});
