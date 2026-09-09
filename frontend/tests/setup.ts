import "@testing-library/jest-dom/vitest";

// Radix Checkbox (ParameterDialog verified toggle) requires ResizeObserver in jsdom
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;
