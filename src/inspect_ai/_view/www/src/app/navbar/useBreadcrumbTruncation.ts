import { useEffect, useState, useCallback, RefObject } from "react";

interface BreadcrumbSegment {
  text: string;
  url?: string;
}

interface TruncatedBreadcrumbs {
  visibleSegments: BreadcrumbSegment[];
  hiddenCount: number;
  showEllipsis: boolean;
}

export const useBreadcrumbTruncation = (
  segments: BreadcrumbSegment[],
  containerRef: RefObject<HTMLElement | null>,
): TruncatedBreadcrumbs => {
  const [truncatedData, setTruncatedData] = useState<TruncatedBreadcrumbs>({
    visibleSegments: segments,
    hiddenCount: 0,
    showEllipsis: false,
  });

  const measureAndTruncate = useCallback(() => {
    if (!containerRef.current || segments.length <= 3) {
      setTruncatedData({
        visibleSegments: segments,
        hiddenCount: 0,
        showEllipsis: false,
      });
      return;
    }

    const container = containerRef.current;
    const containerWidth = container.offsetWidth;

    // Create a test element to measure breadcrumb widths
    const testElement = document.createElement("ol");
    testElement.className = "breadcrumb";
    testElement.style.position = "absolute";
    testElement.style.visibility = "hidden";
    testElement.style.whiteSpace = "nowrap";
    testElement.style.margin = "0";
    testElement.style.padding = "0";

    container.appendChild(testElement);

    // Test if all segments fit
    testElement.innerHTML = segments
      .map((segment) => `<li class="breadcrumb-item">${segment.text}</li>`)
      .join("");

    if (testElement.scrollWidth <= containerWidth) {
      container.removeChild(testElement);
      setTruncatedData({
        visibleSegments: segments,
        hiddenCount: 0,
        showEllipsis: false,
      });
      return;
    }

    // Find the maximum number of segments we can show
    // Always keep first and last segments
    const firstSegment = segments[0];
    const lastSegment = segments[segments.length - 1];

    let maxVisible = 2; // Start with just first and last

    // Try adding segments from the end (most recent path) first
    for (let endCount = 1; endCount < segments.length - 1; endCount++) {
      const candidateSegments = [
        firstSegment,
        ...segments.slice(segments.length - 1 - endCount, -1),
        lastSegment,
      ];

      // Test with ellipsis
      const testHTML = [
        `<li class="breadcrumb-item">${firstSegment.text}</li>`,
        `<li class="breadcrumb-item">...</li>`,
        ...segments
          .slice(segments.length - 1 - endCount, -1)
          .map((s) => `<li class="breadcrumb-item">${s.text}</li>`),
        `<li class="breadcrumb-item">${lastSegment.text}</li>`,
      ].join("");

      testElement.innerHTML = testHTML;

      if (testElement.scrollWidth <= containerWidth) {
        maxVisible = candidateSegments.length;
        setTruncatedData({
          visibleSegments: candidateSegments,
          hiddenCount: segments.length - candidateSegments.length,
          showEllipsis: true,
        });
      } else {
        break;
      }
    }

    // If we couldn't fit any middle segments, just show first ... last
    if (maxVisible === 2) {
      setTruncatedData({
        visibleSegments: [firstSegment, lastSegment],
        hiddenCount: segments.length - 2,
        showEllipsis: true,
      });
    }

    container.removeChild(testElement);
  }, [segments, containerRef]);

  useEffect(() => {
    measureAndTruncate();

    const resizeObserver = new ResizeObserver(measureAndTruncate);
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      resizeObserver.disconnect();
    };
  }, [measureAndTruncate]);

  return truncatedData;
};
