import { highlightElement } from "prismjs";
import { RefObject, useEffect } from "react";

// Syntax highlighting strings larger than this is too slow
const kPrismRenderMaxSize = 250000;

const highlightCodeBlocks = (container: HTMLElement) => {
  const codeBlocks = container.querySelectorAll("pre code");
  codeBlocks.forEach((block) => {
    // Skip already highlighted blocks
    if (block.hasAttribute("data-highlighted")) {
      return;
    }
    if (block.className.includes("language-")) {
      block.classList.add("sourceCode");
      highlightElement(block as HTMLElement);
      block.setAttribute("data-highlighted", "true");
    }
  });
};

export const usePrismHighlight = (
  containerRef: RefObject<HTMLDivElement | null>,
  contentLength: number,
) => {
  useEffect(() => {
    if (
      contentLength <= 0 ||
      containerRef.current === null ||
      contentLength > kPrismRenderMaxSize
    ) {
      return;
    }

    const container = containerRef.current;

    // Immediate highlight attempt
    requestAnimationFrame(() => {
      highlightCodeBlocks(container);
    });

    // MutationObserver for async-rendered content (e.g., MarkdownDiv)
    const observer = new MutationObserver((mutations) => {
      // Check if any mutation added code blocks
      const hasNewCodeBlocks = mutations.some((mutation) => {
        if (mutation.type === "childList") {
          return Array.from(mutation.addedNodes).some((node) => {
            if (node.nodeType === Node.ELEMENT_NODE) {
              const el = node as HTMLElement;
              return el.querySelector?.("pre code") || el.matches?.("pre code");
            }
            return false;
          });
        }
        return false;
      });

      if (hasNewCodeBlocks) {
        highlightCodeBlocks(container);
      }
    });

    observer.observe(container, {
      childList: true,
      subtree: true,
    });

    return () => {
      observer.disconnect();
    };
  }, [contentLength, containerRef]);
};
