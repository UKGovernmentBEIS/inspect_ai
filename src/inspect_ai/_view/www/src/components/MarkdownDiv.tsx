import clsx from "clsx";
import MarkdownIt from "markdown-it";
import markdownitMathjax3 from "markdown-it-mathjax3";
import { CSSProperties, forwardRef, memo, useEffect, useState } from "react";
import "./MarkdownDiv.css";

interface MarkdownDivProps {
  markdown: string;
  omitMedia?: boolean;
  omitMath?: boolean;
  style?: CSSProperties;
  className?: string | string[];
}

const MarkdownDivComponent = forwardRef<HTMLDivElement, MarkdownDivProps>(
  ({ markdown, omitMedia, omitMath, style, className }, ref) => {
    const html = useMarkdownRender(markdown, omitMedia, omitMath);

    return (
      <div
        ref={ref}
        dangerouslySetInnerHTML={{ __html: html }}
        style={style}
        className={clsx(className, "markdown-content")}
      />
    );
  },
);

// Memoize component to prevent re-renders when props haven't changed
export const MarkdownDiv = memo(MarkdownDivComponent);

// ---------------------------------------------------------------------------
// Cache for rendered markdown
// ---------------------------------------------------------------------------

const renderCache = new Map<string, string>();
const MAX_CACHE_SIZE = 500;

// ---------------------------------------------------------------------------
// Custom hook: trigger async render via useEffect, read result via useState
// ---------------------------------------------------------------------------

function useMarkdownRender(
  markdown: string,
  omitMedia?: boolean,
  omitMath?: boolean,
): string {
  const cacheKey = `${markdown}:${getOptionsKey(omitMedia, omitMath)}`;

  // Initialize from cache if available, otherwise show raw markdown as fallback
  const [html, setHtml] = useState<string>(
    () => renderCache.get(cacheKey) ?? markdown.replace(/\n/g, "<br/>"),
  );

  // Trigger async rendering when inputs change (only if not already cached)
  useEffect(() => {
    if (renderCache.has(cacheKey)) {
      // Cache hit — just ensure state is up to date (handles prop changes)
      setHtml(renderCache.get(cacheKey)!);
      return;
    }

    // Show raw markdown immediately while async render is in-flight
    setHtml(markdown.replace(/\n/g, "<br/>"));

    const { promise, cancel } = renderQueue.enqueue(() =>
      renderMarkdown(markdown, omitMedia, omitMath),
    );

    promise
      .then((result) => {
        // Populate cache
        if (renderCache.size >= MAX_CACHE_SIZE) {
          const firstKey = renderCache.keys().next().value;
          if (firstKey) {
            renderCache.delete(firstKey);
          }
        }
        renderCache.set(cacheKey, result);
        setHtml(result);
      })
      .catch((error) => {
        console.error("Markdown rendering error:", error);
      });

    return () => {
      cancel();
    };
  }, [markdown, omitMedia, omitMath, cacheKey]);

  return html;
}

// ---------------------------------------------------------------------------
// Pure markdown rendering pipeline
// ---------------------------------------------------------------------------

async function renderMarkdown(
  markdown: string,
  omitMedia?: boolean,
  omitMath?: boolean,
): Promise<string> {
  const protectedContent = protectBackslashesInLatex(markdown);
  const escaped = escapeHtmlCharacters(protectedContent);
  const preRendered = preRenderText(escaped);
  const protectedText = protectMarkdown(preRendered);
  const preparedForMarkdown = restoreBackslashesForLatex(protectedText);

  let html = preparedForMarkdown;
  try {
    const md = getMarkdownInstance(omitMedia, omitMath);
    html = md.render(preparedForMarkdown);
  } catch (ex) {
    console.log("Unable to markdown render content");
    console.error(ex);
  }

  const unescaped = unprotectMarkdown(html);
  const withCode = unescapeCodeHtmlEntities(unescaped);
  const withSup = unescapeSupHtmlEntities(withCode);
  return withSup;
}

// ---------------------------------------------------------------------------
// Module-level cache for lazy-initialized markdown-it instances
// ---------------------------------------------------------------------------

const mdInstanceCache: Record<string, MarkdownIt> = {};

const getOptionsKey = (omitMedia?: boolean, omitMath?: boolean): string =>
  `${omitMedia ? "1" : "0"}:${omitMath ? "1" : "0"}`;

const getMarkdownInstance = (
  omitMedia?: boolean,
  omitMath?: boolean,
): MarkdownIt => {
  const key = getOptionsKey(omitMedia, omitMath);

  if (!mdInstanceCache[key]) {
    const md = new MarkdownIt({ breaks: true, html: true });
    if (!omitMath) {
      md.use(markdownitMathjax3);
    }
    if (omitMedia) {
      md.disable(["image"]);
    }
    mdInstanceCache[key] = md;
  }

  return mdInstanceCache[key];
};

// ---------------------------------------------------------------------------
// Markdown rendering queue (async with limited concurrency)
// ---------------------------------------------------------------------------

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
    let queueTaskRef: QueueTask | null = null;

    const promise = new Promise<T>((resolve, reject) => {
      const wrappedTask = async () => {
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

      queueTaskRef = queueTask;
      this.queue.push(queueTask);
      this.processQueue();
    });

    const cancel = () => {
      cancelled = true;
      if (queueTaskRef) {
        queueTaskRef.cancelled = true;
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

// Shared rendering queue
const renderQueue = new MarkdownRenderQueue(10);

// ---------------------------------------------------------------------------
// Markdown pre/post-processing helpers
// ---------------------------------------------------------------------------

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
