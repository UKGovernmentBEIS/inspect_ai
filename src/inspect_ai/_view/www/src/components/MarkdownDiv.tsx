import clsx from "clsx";
import markdownit from "markdown-it";
import markdownitMathjax3 from "markdown-it-mathjax3";
import {
  CSSProperties,
  forwardRef,
  memo,
  startTransition,
  useEffect,
  useState,
} from "react";
import "./MarkdownDiv.css";

interface MarkdownDivProps {
  markdown: string;
  omitMedia?: boolean;
  style?: CSSProperties;
  className?: string | string[];
}

const MarkdownDivComponent = forwardRef<HTMLDivElement, MarkdownDivProps>(
  ({ markdown, omitMedia, style, className }, ref) => {
    // Check cache for rendered content
    const cacheKey = `${markdown}:${omitMedia ? "1" : "0"}`;
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

      // Reset to raw markdown text when markdown changes (keep this synchronous for immediate feedback)
      setRenderedHtml(markdown.replace(/\n/g, "<br/>"));

      // Process markdown asynchronously using the queue
      const { promise, cancel } = renderQueue.enqueue(async () => {
        // Protect backslashes in LaTeX expressions
        const protectedContent = protectBackslashesInLatex(markdown);

        // Escape all tags
        const escaped = escapeHtmlCharacters(protectedContent);

        // Pre-render any text that isn't handled by markdown
        const preRendered = preRenderText(escaped);

        const protectedText = protectMarkdown(preRendered);

        // Restore backslashes for LaTeX processing
        const preparedForMarkdown = restoreBackslashesForLatex(protectedText);

        let html = preparedForMarkdown;
        try {
          // Use pre-initialized markdown-it instance
          const md = omitMedia ? mdInstanceNoMedia : mdInstance;
          html = md.render(preparedForMarkdown);
        } catch (ex) {
          console.log("Unable to markdown render content");
          console.error(ex);
        }

        const unescaped = unprotectMarkdown(html);

        // For `code` tags, reverse the escaping if we can
        const withCode = unescapeCodeHtmlEntities(unescaped);

        // For `sup` tags, reverse the escaping if we can
        const withSup = unescapeSupHtmlEntities(withCode);

        return withSup;
      });

      // Update state when rendering completes
      promise
        .then((result) => {
          // Update cache (with simple size limit)
          if (renderCache.size >= MAX_CACHE_SIZE) {
            // Remove oldest entry (first key)
            const firstKey = renderCache.keys().next().value;
            if (firstKey) {
              renderCache.delete(firstKey);
            }
          }
          renderCache.set(cacheKey, result);

          // Use startTransition to mark this as a non-urgent update
          startTransition(() => {
            setRenderedHtml(result);
          });
        })
        .catch((error) => {
          console.error("Markdown rendering error:", error);
        });

      return () => {
        // Cancel rendering if component unmounts
        cancel();
      };
    }, [markdown, omitMedia, cachedHtml, renderedHtml, cacheKey]);

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

// Pre-initialize markdown-it instances to avoid recreation overhead
const mdInstance = markdownit({ breaks: true, html: true }).use(
  markdownitMathjax3,
);
const mdInstanceNoMedia = markdownit({ breaks: true, html: true })
  .use(markdownitMathjax3)
  .disable(["image"]);

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

// Shared rendering queue
const renderQueue = new MarkdownRenderQueue(10);

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
