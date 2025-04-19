import clsx from "clsx";
import "katex/dist/katex.min.css";
import markdownit from "markdown-it";
import markdownitKatex from "markdown-it-katex";
import { CSSProperties, forwardRef } from "react";
import "./MarkdownDiv.css";

interface MarkdownDivProps {
  markdown: string;
  style?: CSSProperties;
  className?: string | string[];
}

export const MarkdownDiv = forwardRef<HTMLDivElement, MarkdownDivProps>(
  ({ markdown, style, className }, ref) => {
    // Protect backslashes in LaTeX expressions
    const protectedContent = protectBackslashesInLatex(markdown);

    // Escape all tags
    const escaped = escapeHtmlCharacters(protectedContent);

    // Pre-render any text that isn't handled by markdown
    const preRendered = preRenderText(escaped);

    const protectedText = protectMarkdown(preRendered);

    // Restore backslashes for LaTeX processing
    const preparedForMarkdown = restoreBackslashesForLatex(protectedText);

    let renderedHtml = preparedForMarkdown;
    try {
      const md = markdownit({
        breaks: true,
        html: true,
      });

      // Add KaTeX support
      md.use(markdownitKatex, {
        throwOnError: false,
        errorColor: "#cc0000",
      });

      renderedHtml = md.render(preparedForMarkdown);
    } catch (ex) {
      console.log("Unable to markdown render content");
      console.error(ex);
    }

    const unescaped = unprotectMarkdown(renderedHtml);

    // For `code` tags, reverse the escaping if we can
    const withCode = unescapeCodeHtmlEntities(unescaped);

    // Return the rendered markdown
    const markup = { __html: withCode };

    return (
      <div
        ref={ref}
        dangerouslySetInnerHTML={markup}
        style={style}
        className={clsx(className, "markdown-content")}
      />
    );
  },
);

const kLetterListPattern = /^([a-zA-Z][).]\s.*?)$/gm;
const kCommonmarkReferenceLinkPattern = /\[([^\]]*)\]: (?!http)(.*)/g;

const protectBackslashesInLatex = (content: string): string => {
  if (!content) return content;

  try {
    // Match inline math: $...$
    const inlineRegex = /\$(.*?)\$/g;

    // Match block math: $$...$$
    const blockRegex = /\$\$([\s\S]*?)\$\$/g;

    // Replace backslashes in LaTeX blocks with a placeholder
    let result = content.replace(inlineRegex, (_match, latex) => {
      const protectedTex = latex.replace(/\\/g, "___LATEX_BACKSLASH___");
      return `$${protectedTex}$`;
    });

    result = result.replace(blockRegex, (_match, latex) => {
      const protectedTex = latex.replace(/\\/g, "___LATEX_BACKSLASH___");
      return `$$${protectedTex}$$`;
    });

    return result;
  } catch (error) {
    console.error("Error protecting LaTeX backslashes:", error);
    return content;
  }
};

const restoreBackslashesForLatex = (content: string): string => {
  if (!content) {
    return content;
  }

  try {
    // First restore backslashes
    let result = content.replace(/___LATEX_BACKSLASH___/g, "\\");

    // Then fix dots notation for better KaTeX compatibility
    // This replaces \dots with \ldots which has better support
    result = fixDotsNotation(result);

    return result;
  } catch (error) {
    console.error("Error restoring LaTeX backslashes:", error);
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
