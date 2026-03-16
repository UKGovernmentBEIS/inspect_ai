import { jest } from "@jest/globals";
import { findScrollableParent, scrollRangeToCenter } from "../../utils/dom";

describe("findScrollableParent", () => {
  let container: HTMLDivElement;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
  });

  afterEach(() => {
    document.body.removeChild(container);
  });

  test("returns null for null element", () => {
    expect(findScrollableParent(null)).toBeNull();
  });

  test("returns null when no scrollable parent exists", () => {
    const child = document.createElement("div");
    container.appendChild(child);
    expect(findScrollableParent(child)).toBeNull();
  });

  test("finds scrollable parent with overflow-y: auto", () => {
    const scrollable = document.createElement("div");
    scrollable.style.overflowY = "auto";
    // Mock scrollHeight and clientHeight since jsdom doesn't compute them
    Object.defineProperty(scrollable, "scrollHeight", { value: 500 });
    Object.defineProperty(scrollable, "clientHeight", { value: 200 });

    const child = document.createElement("div");
    scrollable.appendChild(child);
    container.appendChild(scrollable);

    expect(findScrollableParent(child)).toBe(scrollable);
  });

  test("finds scrollable parent with overflow-y: scroll", () => {
    const scrollable = document.createElement("div");
    scrollable.style.overflowY = "scroll";
    Object.defineProperty(scrollable, "scrollHeight", { value: 500 });
    Object.defineProperty(scrollable, "clientHeight", { value: 200 });

    const child = document.createElement("div");
    scrollable.appendChild(child);
    container.appendChild(scrollable);

    expect(findScrollableParent(child)).toBe(scrollable);
  });

  test("skips elements that don't have enough scroll height", () => {
    const notScrollable = document.createElement("div");
    notScrollable.style.overflowY = "auto";
    // scrollHeight - clientHeight = 50, which is less than default minScrollBuffer (100)
    Object.defineProperty(notScrollable, "scrollHeight", { value: 250 });
    Object.defineProperty(notScrollable, "clientHeight", { value: 200 });

    const child = document.createElement("div");
    notScrollable.appendChild(child);
    container.appendChild(notScrollable);

    expect(findScrollableParent(child)).toBeNull();
  });

  test("respects custom minScrollBuffer option", () => {
    const scrollable = document.createElement("div");
    scrollable.style.overflowY = "auto";
    // scrollHeight - clientHeight = 50, which is >= minScrollBuffer of 30
    Object.defineProperty(scrollable, "scrollHeight", { value: 250 });
    Object.defineProperty(scrollable, "clientHeight", { value: 200 });

    const child = document.createElement("div");
    scrollable.appendChild(child);
    container.appendChild(scrollable);

    expect(findScrollableParent(child, { minScrollBuffer: 30 })).toBe(
      scrollable,
    );
  });

  test("finds nearest scrollable parent when multiple exist", () => {
    const outerScrollable = document.createElement("div");
    outerScrollable.style.overflowY = "auto";
    Object.defineProperty(outerScrollable, "scrollHeight", { value: 1000 });
    Object.defineProperty(outerScrollable, "clientHeight", { value: 400 });

    const innerScrollable = document.createElement("div");
    innerScrollable.style.overflowY = "auto";
    Object.defineProperty(innerScrollable, "scrollHeight", { value: 500 });
    Object.defineProperty(innerScrollable, "clientHeight", { value: 200 });

    const child = document.createElement("div");
    innerScrollable.appendChild(child);
    outerScrollable.appendChild(innerScrollable);
    container.appendChild(outerScrollable);

    expect(findScrollableParent(child)).toBe(innerScrollable);
  });

  test("handles non-HTMLElement by traversing to parent", () => {
    const scrollable = document.createElement("div");
    scrollable.style.overflowY = "auto";
    Object.defineProperty(scrollable, "scrollHeight", { value: 500 });
    Object.defineProperty(scrollable, "clientHeight", { value: 200 });

    // Create an SVG element (Element but not HTMLElement)
    const svgElement = document.createElementNS(
      "http://www.w3.org/2000/svg",
      "svg",
    );
    scrollable.appendChild(svgElement);
    container.appendChild(scrollable);

    // SVG elements are Elements but not HTMLElements, so the function
    // should traverse to find the scrollable HTMLElement parent
    expect(findScrollableParent(svgElement)).toBe(scrollable);
  });
});

describe("scrollRangeToCenter", () => {
  let container: HTMLDivElement;
  let scrollable: HTMLDivElement;
  let content: HTMLDivElement;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);

    scrollable = document.createElement("div");
    scrollable.style.overflowY = "auto";
    Object.defineProperty(scrollable, "scrollHeight", { value: 1000 });
    Object.defineProperty(scrollable, "clientHeight", { value: 200 });
    Object.defineProperty(scrollable, "scrollTop", {
      value: 0,
      writable: true,
    });

    content = document.createElement("div");
    content.textContent = "Test content for selection";
    scrollable.appendChild(content);
    container.appendChild(scrollable);
  });

  afterEach(() => {
    document.body.removeChild(container);
  });

  test("does nothing when range has no client rects", () => {
    const range = document.createRange();
    // Empty range has no client rects
    range.setStart(content, 0);
    range.setEnd(content, 0);

    // Mock getClientRects to return empty
    range.getClientRects = jest
      .fn<() => DOMRectList>()
      .mockReturnValue([] as unknown as DOMRectList);

    // Should not throw
    expect(() => scrollRangeToCenter(range)).not.toThrow();
  });

  test("calls scrollTo on scrollable parent", () => {
    const range = document.createRange();
    range.selectNodeContents(content);

    // Mock the necessary methods
    const mockRect = { top: 300, left: 0, width: 100, height: 20 };
    range.getClientRects = jest
      .fn<() => DOMRectList>()
      .mockReturnValue([mockRect] as unknown as DOMRectList);

    const scrollToMock = jest.fn();
    scrollable.scrollTo = scrollToMock;
    scrollable.getBoundingClientRect = jest
      .fn<() => DOMRect>()
      .mockReturnValue({
        top: 0,
        left: 0,
        width: 400,
        height: 200,
      } as DOMRect);

    scrollRangeToCenter(range);

    expect(scrollToMock).toHaveBeenCalledWith({
      top: expect.any(Number),
      behavior: "auto",
    });
  });

  test("uses smooth behavior when specified", () => {
    const range = document.createRange();
    range.selectNodeContents(content);

    const mockRect = { top: 300, left: 0, width: 100, height: 20 };
    range.getClientRects = jest
      .fn<() => DOMRectList>()
      .mockReturnValue([mockRect] as unknown as DOMRectList);

    const scrollToMock = jest.fn();
    scrollable.scrollTo = scrollToMock;
    scrollable.getBoundingClientRect = jest
      .fn<() => DOMRect>()
      .mockReturnValue({
        top: 0,
        left: 0,
        width: 400,
        height: 200,
      } as DOMRect);

    scrollRangeToCenter(range, { behavior: "smooth" });

    expect(scrollToMock).toHaveBeenCalledWith({
      top: expect.any(Number),
      behavior: "smooth",
    });
  });

  test("falls back to scrollIntoView when no scrollable parent and fallback enabled", () => {
    // Mock scrollIntoView globally on HTMLElement prototype since jsdom doesn't have it
    const scrollIntoViewMock = jest.fn();
    HTMLElement.prototype.scrollIntoView = scrollIntoViewMock;

    // Create element without scrollable parent
    const standaloneDiv = document.createElement("div");
    const textNode = document.createTextNode("Standalone text");
    standaloneDiv.appendChild(textNode);
    container.appendChild(standaloneDiv);

    const range = document.createRange();
    range.selectNode(textNode);

    const mockRect = { top: 500, left: 0, width: 100, height: 20 };
    range.getClientRects = jest
      .fn<() => DOMRectList>()
      .mockReturnValue([mockRect] as unknown as DOMRectList);

    scrollRangeToCenter(range, { fallbackToScrollIntoView: true });

    expect(scrollIntoViewMock).toHaveBeenCalledWith({
      behavior: "auto",
      block: "center",
    });
  });

  test("does not fall back to scrollIntoView when fallback disabled", () => {
    // Create element without scrollable parent
    const standaloneDiv = document.createElement("div");
    standaloneDiv.textContent = "Standalone";
    container.appendChild(standaloneDiv);

    const range = document.createRange();
    range.selectNodeContents(standaloneDiv);

    const mockRect = { top: 500, left: 0, width: 100, height: 20 };
    range.getClientRects = jest
      .fn<() => DOMRectList>()
      .mockReturnValue([mockRect] as unknown as DOMRectList);

    const scrollIntoViewMock = jest.fn();
    standaloneDiv.scrollIntoView = scrollIntoViewMock;

    scrollRangeToCenter(range, { fallbackToScrollIntoView: false });

    expect(scrollIntoViewMock).not.toHaveBeenCalled();
  });

  test("clamps scroll position to minimum of 0", () => {
    const range = document.createRange();
    range.selectNodeContents(content);

    // Position the selection near the top so calculated scroll would be negative
    const mockRect = { top: 10, left: 0, width: 100, height: 20 };
    range.getClientRects = jest
      .fn<() => DOMRectList>()
      .mockReturnValue([mockRect] as unknown as DOMRectList);

    const scrollToMock = jest.fn();
    scrollable.scrollTo = scrollToMock;
    scrollable.getBoundingClientRect = jest
      .fn<() => DOMRect>()
      .mockReturnValue({
        top: 0,
        left: 0,
        width: 400,
        height: 200,
      } as DOMRect);

    scrollRangeToCenter(range);

    expect(scrollToMock).toHaveBeenCalledWith({
      top: 0, // Should be clamped to 0, not negative
      behavior: "auto",
    });
  });
});
