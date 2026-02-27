import clsx from "clsx";
import MarkdownIt from "markdown-it";
import {
  CSSProperties,
  forwardRef,
  memo,
  startTransition,
  useEffect,
  useState,
} from "react";
import "./MarkdownDiv.css";

// Lazy-load mathjax plugin only when math content is detected
let mathjaxPluginPromise: Promise<any> | null = null;
const getMathjaxPlugin = (): Promise<any> => {
  if (!mathjaxPluginPromise) {
    mathjaxPluginPromise = import("markdown-it-mathjax3").then(
      (m) => m.default,
    );
  }
  return mathjaxPluginPromise;
};

// Quick check for math patterns in content
const hasMathContent = (text: string): boolean => {
  return text.includes("$") || text.includes("\\(") || text.includes("\\[");
};

interface MarkdownDivProps {
  markdown: string;
  omitMedia?: boolean;
  omitMath?: boolean;
  style?: CSSProperties;
  className?: string | string[];
}

const MarkdownDivComponent = forwardRef<HTMLDivElement, MarkdownDivProps>(
  ({ markdown, omitMedia, omitMath, style, className }, ref) => {
    // Check cache for rendered content
    const optionsKey = getOptionsKey(omitMedia, omitMath);
    const cacheKey = `${markdown}:${optionsKey}`;
    const cachedHtml = renderCache.get(cacheKey);

    // Initialize with content (cached or unrendered markdown)
    const [renderedHtml, setRenderedHtml] = useState<string>(() => {
      if (cachedHtml) {
        return cachedHtml;
      }
      return markdown.replace(/\n/g, "<br/>");
    });

    useEffect(() => {
      // If already cached, no need to re-render
      if (cachedHtml) {
        // Only update state if it's different (avoid unnecessary re-render)
        if (renderedHtml !== cachedHtml) {
          startTransition(() => {
            setRenderedHtml(cachedHtml);
          });
        }
        return;
      }

      // Reset to raw markdown text when markdown changes
      setRenderedHtml(markdown.replace(/\n/g, "<br/>"));

      // Process markdown asynchronously using the coordinator.
      // The coordinator batches completions from multiple MarkdownDiv
      // instances into a single startTransition → one React commit.
      const { cancel } = renderCoordinator.enqueue(
        cacheKey,
        async () => {
          // Full markdown preprocessing pipeline
          const protectedContent = protectBackslashesInLatex(markdown);
          const escaped = escapeHtmlCharacters(protectedContent);
          const preRendered = preRenderText(escaped);
          const protectedText = protectMarkdown(preRendered);
          const preparedForMarkdown = restoreBackslashesForLatex(protectedText);

          let html = preparedForMarkdown;
          try {
            const contentHasMath = hasMathContent(markdown);
            const md = await getMarkdownInstance(
              omitMedia,
              omitMath,
              contentHasMath,
            );
            html = md.render(preparedForMarkdown);
          } catch (ex) {
            console.log("Unable to markdown render content");
            console.error(ex);
          }

          const unescaped = unprotectMarkdown(html);
          const withCode = unescapeCodeHtmlEntities(unescaped);
          const withSup = unescapeSupHtmlEntities(withCode);

          return withSup;
        },
        (result) => {
          // This callback is called INSIDE the coordinator's startTransition,
          // batched with other MarkdownDiv completions → ONE React commit.
          if (renderCache.size >= MAX_CACHE_SIZE) {
            const firstKey = renderCache.keys().next().value;
            if (firstKey) {
              renderCache.delete(firstKey);
            }
          }
          renderCache.set(cacheKey, result);
          setRenderedHtml(result);
        },
      );

      return () => {
        cancel();
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps -- renderedHtml
      // intentionally excluded: including it causes wasteful re-runs when the
      // async render completes and updates state (30-50 extra effect evaluations
      // per sample load). The effect only needs to re-run when the SOURCE data
      // changes (markdown, options, cacheKey), not when the output updates.
    }, [markdown, omitMedia, omitMath, cachedHtml, cacheKey]);

    return (
      <div
        ref={ref}
        dangerouslySetInnerHTML={{ __html: renderedHtml }}
        style={style}
        className={clsx(className, "markdown-content")}
      />
    );
  },
);

// Memoize component to prevent re-renders when props haven't changed
export const MarkdownDiv = memo(MarkdownDivComponent);

// Cache for rendered markdown to avoid re-processing identical content
const renderCache = new Map<string, string>();
const MAX_CACHE_SIZE = 500;

// Module-level cache for lazy-initialized markdown-it instances
const mdInstanceCache: Record<string, MarkdownIt> = {};

const getOptionsKey = (omitMedia?: boolean, omitMath?: boolean): string =>
  `${omitMedia ? "1" : "0"}:${omitMath ? "1" : "0"}`;

const getMarkdownInstance = async (
  omitMedia?: boolean,
  omitMath?: boolean,
  contentHasMath?: boolean,
): Promise<MarkdownIt> => {
  // If math should be rendered and content has math patterns, load mathjax
  const useMath = !omitMath && contentHasMath;
  const key = `${getOptionsKey(omitMedia, omitMath)}:${useMath ? "1" : "0"}`;

  if (!mdInstanceCache[key]) {
    const md = new MarkdownIt({ breaks: true, html: true });
    if (useMath) {
      const mathjaxPlugin = await getMathjaxPlugin();
      md.use(mathjaxPlugin);
    }
    if (omitMedia) {
      md.disable(["image"]);
    }
    mdInstanceCache[key] = md;
  }

  return mdInstanceCache[key];
};

// Markdown rendering queue to make markdown rendering async while limiting concurrency
interface QueueTask {
  task: () => Promise<void>;
  cancelled: boolean;
}

class MarkdownRenderQueue {
  private queue: QueueTask[] = [];
  private activeCount = 0;
  private readonly maxConcurrent: number;

  constructor(maxConcurrent: number = 10) {
    this.maxConcurrent = maxConcurrent;
  }

  enqueue<T>(task: () => Promise<T>): {
    promise: Promise<T>;
    cancel: () => void;
  } {
    let cancelled = false;

    const promise = new Promise<T>((resolve, reject) => {
      const wrappedTask = async () => {
        // Skip if cancelled before execution
        if (cancelled) {
          return;
        }

        try {
          const result = await task();
          if (!cancelled) {
            resolve(result);
          }
        } catch (error) {
          if (!cancelled) {
            reject(error);
          }
        }
      };

      const queueTask: QueueTask = {
        task: wrappedTask,
        cancelled: false,
      };

      this.queue.push(queueTask);
      this.processQueue();
    });

    const cancel = () => {
      cancelled = true;
      // Mark task as cancelled in queue
      const index = this.queue.findIndex((t) => !t.cancelled);
      if (index !== -1) {
        this.queue[index].cancelled = true;
      }
    };

    return { promise, cancel };
  }

  private async processQueue(): Promise<void> {
    if (this.activeCount >= this.maxConcurrent || this.queue.length === 0) {
      return;
    }

    // Find next non-cancelled task
    let queueTask: QueueTask | undefined;
    while (this.queue.length > 0) {
      const task = this.queue.shift();
      if (task && !task.cancelled) {
        queueTask = task;
        break;
      }
    }

    if (!queueTask) {
      return;
    }

    this.activeCount++;

    try {
      await queueTask.task();
    } finally {
      this.activeCount--;
      this.processQueue();
    }
  }
}

/**
 * Coordinates markdown render results to batch React state updates.
 *
 * Problem: When 10-15 MarkdownDiv instances complete async rendering,
 * each fires startTransition(() => setRenderedHtml(result)) from a
 * separate Promise microtask. React 18 does NOT batch across microtasks,
 * causing 10-15 separate React commits (30-40ms each = 300-600ms total).
 *
 * Solution: Collect completed results and deliver them ALL in a single
 * startTransition callback via queueMicrotask. React batches all setState
 * calls within one startTransition into ONE commit.
 */
class MarkdownRenderCoordinator {
  private completedResults: Map<string, string> = new Map();
  private pendingCallbacks: Map<string, (html: string) => void> = new Map();
  private flushScheduled = false;
  private queue: MarkdownRenderQueue;

  constructor(maxConcurrent: number = 10) {
    this.queue = new MarkdownRenderQueue(maxConcurrent);
  }

  enqueue(
    cacheKey: string,
    task: () => Promise<string>,
    onComplete: (html: string) => void,
  ): { cancel: () => void } {
    this.pendingCallbacks.set(cacheKey, onComplete);

    const { promise, cancel } = this.queue.enqueue(task);

    promise
      .then((result) => {
        this.completedResults.set(cacheKey, result);
        this.scheduleFlush();
      })
      .catch((error) => {
        this.pendingCallbacks.delete(cacheKey);
        console.error("Markdown rendering error:", error);
      });

    return {
      cancel: () => {
        cancel();
        this.pendingCallbacks.delete(cacheKey);
        this.completedResults.delete(cacheKey);
      },
    };
  }

  private scheduleFlush() {
    if (!this.flushScheduled) {
      this.flushScheduled = true;
      queueMicrotask(() => this.flush());
    }
  }

  private flush() {
    this.flushScheduled = false;
    const batch = new Map(this.completedResults);
    this.completedResults.clear();

    if (batch.size === 0) return;

    startTransition(() => {
      for (const [key, html] of batch) {
        const callback = this.pendingCallbacks.get(key);
        if (callback) {
          callback(html);
          this.pendingCallbacks.delete(key);
        }
      }
    });
  }
}

// Shared rendering coordinator — batches markdown render completions
// into single React commits to avoid cascading re-renders
const renderCoordinator = new MarkdownRenderCoordinator(10);

const kLetterListPattern = /^([a-zA-Z][).]\s.*?)$/gm;
const kCommonmarkReferenceLinkPattern = /\[([^\]]*)\]: (?!http)(.*)/g;

const protectBackslashesInLatex = (content: string): string => {
  if (!content) return content;

  try {
    // Match inline math: $...$
    const inlineRegex = /\$(.*?)\$/g;

    // Match block math: $$...$$
    const blockRegex = /\$\$([\s\S]*?)\$\$/g;

    // Replace backslashes and HTML characters in LaTeX blocks with placeholders
    let result = content.replace(inlineRegex, (_match, latex) => {
      const protectedTex = latex
        .replace(/\\/g, "___LATEX_BACKSLASH___")
        .replace(/</g, "___LATEX_LT___")
        .replace(/>/g, "___LATEX_GT___")
        .replace(/&/g, "___LATEX_AMP___")
        .replace(/'/g, "___LATEX_APOS___")
        .replace(/"/g, "___LATEX_QUOT___");
      return `$${protectedTex}$`;
    });

    result = result.replace(blockRegex, (_match, latex) => {
      const protectedTex = latex
        .replace(/\\/g, "___LATEX_BACKSLASH___")
        .replace(/</g, "___LATEX_LT___")
        .replace(/>/g, "___LATEX_GT___")
        .replace(/&/g, "___LATEX_AMP___")
        .replace(/'/g, "___LATEX_APOS___")
        .replace(/"/g, "___LATEX_QUOT___");
      return `$$${protectedTex}$$`;
    });

    return result;
  } catch (error) {
    console.error("Error protecting LaTeX content:", error);
    return content;
  }
};

const restoreBackslashesForLatex = (content: string): string => {
  if (!content) {
    return content;
  }

  try {
    // Restore all protected LaTeX content
    let result = content
      .replace(/___LATEX_BACKSLASH___/g, "\\")
      .replace(/___LATEX_LT___/g, "<")
      .replace(/___LATEX_GT___/g, ">")
      .replace(/___LATEX_AMP___/g, "&")
      .replace(/___LATEX_APOS___/g, "'")
      .replace(/___LATEX_QUOT___/g, '"');

    // Then fix dots notation for better MathJax compatibility
    // This replaces \dots with \ldots which has better support
    result = fixDotsNotation(result);

    return result;
  } catch (error) {
    console.error("Error restoring LaTeX content:", error);
    return content; // Return input content if something goes wrong
  }
};

// Fixes dots notation in LaTeX by replacing \dots with \ldots for better compatibility
const fixDotsNotation = (content: string): string => {
  if (!content) return content;

  try {
    // Handle both inline and block math
    // First, fix inline math expressions ($...$)
    let result = content.replace(/(\$[^$]*?)\\dots([^$]*?\$)/g, "$1\\ldots$2");

    // Then, fix block math expressions ($...$)
    result = result.replace(/(\$\$[^$]*?)\\dots([^$]*?\$\$)/g, "$1\\ldots$2");

    return result;
  } catch (error) {
    console.error("Error fixing dots notation:", error);
    return content;
  }
};

const escapeHtmlCharacters = (content: string): string => {
  if (!content) return content;

  return content.replace(/[<>&'"]/g, (c: string): string => {
    switch (c) {
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case "&":
        return "&amp;";
      case "'":
        return "&apos;";
      case '"':
        return "&quot;";
      default:
        throw new Error("Matched a value that isn't replaceable");
    }
  });
};

const preRenderText = (txt: string): string => {
  if (!txt) return txt;

  // eslint-disable-next-line no-misleading-character-class
  txt = txt.replace(/^[\u200B\u200C\u200D\u200E\u200F\uFEFF]/, "");

  // Special handling for ordered lists that look like
  // multiple choice (e.g. a), b), c), d) etc..)
  return txt.replaceAll(
    kLetterListPattern,
    "<p class='markdown-ordered-list-item'>$1</p>",
  );
};

const protectMarkdown = (txt: string): string => {
  if (!txt) return txt;

  // Special handling for commonmark like reference links which might
  // look like:
  // [alias]: http://www.google.com
  // but text like:
  // [expert]: answer
  // Also fools this
  return txt.replaceAll(
    kCommonmarkReferenceLinkPattern,
    "(open:767A125E)$1(close:767A125E) $2 ",
  );
};

const unprotectMarkdown = (txt: string): string => {
  if (!txt) return txt;

  txt = txt.replaceAll("(open:767A125E)", "[");
  txt = txt.replaceAll("(close:767A125E)", "]");
  return txt;
};

function unescapeSupHtmlEntities(str: string): string {
  // replace &lt;sup&gt; with <sup>
  if (!str) {
    return str;
  }
  return str
    .replace(/&lt;sup&gt;/g, "<sup>")
    .replace(/&lt;\/sup&gt;/g, "</sup>");
}

function unescapeCodeHtmlEntities(str: string): string {
  if (!str) return str;

  const htmlEntities: Record<string, string> = {
    "&lt;": "<",
    "&gt;": ">",
    "&amp;": "&",
    "&#x5C;": "\\",
    "&quot;": '"',
  };

  return str.replace(
    /(<code[^>]*>)([\s\S]*?)(<\/code>)/gi,
    (
      _match: string,
      starttag: string,
      content: string,
      endtag: string,
    ): string => {
      return (
        starttag +
        content.replace(
          /&(?:amp|lt|gt|quot|#39|#x2F|#x5C|#96);/g,
          (entity: string): string => htmlEntities[entity] || entity,
        ) +
        endtag
      );
    },
  );
}
