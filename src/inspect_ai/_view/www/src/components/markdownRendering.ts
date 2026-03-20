/**
 * Pure functions for the markdown rendering pipeline.
 * Extracted for testability (no CSS/React imports).
 */

import MarkdownIt from "markdown-it";
import markdownitMathjax3 from "markdown-it-mathjax3";

// Module-level cache for lazy-initialized markdown-it instances
const mdInstanceCache: Record<string, MarkdownIt> = {};

const getOptionsKey = (omitMedia?: boolean, omitMath?: boolean): string =>
  `${omitMedia ? "1" : "0"}:${omitMath ? "1" : "0"}`;

/** Unescape HTML entities within math token content before MathJax processing.
 *  This is safe because MathJax renders TeX to SVG/MathML, not raw HTML. */
export const unescapeHtmlForMath = (content: string): string => {
  return content
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&apos;/g, "'")
    .replace(/&quot;/g, '"');
};

export const getMarkdownInstance = (
  omitMedia?: boolean,
  omitMath?: boolean,
): MarkdownIt => {
  const key = getOptionsKey(omitMedia, omitMath);

  if (!mdInstanceCache[key]) {
    const md = new MarkdownIt({ breaks: true, html: true });
    if (!omitMath) {
      md.use(markdownitMathjax3);

      // Wrap math renderers to unescape HTML entities in TeX content
      // before MathJax processes them. HTML chars in LaTeX blocks are
      // entity-encoded by the pipeline for XSS safety, but MathJax needs
      // the raw characters (e.g. < for \lt comparisons). This is safe
      // because MathJax renders to SVG, not to injectable HTML.
      const origInline = md.renderer.rules.math_inline;
      const origBlock = md.renderer.rules.math_block;

      if (origInline) {
        md.renderer.rules.math_inline = (tokens, idx, options, env, self) => {
          tokens[idx].content = unescapeHtmlForMath(tokens[idx].content);
          return origInline(tokens, idx, options, env, self);
        };
      }
      if (origBlock) {
        md.renderer.rules.math_block = (tokens, idx, options, env, self) => {
          tokens[idx].content = unescapeHtmlForMath(tokens[idx].content);
          return origBlock(tokens, idx, options, env, self);
        };
      }
    }
    if (omitMedia) {
      md.disable(["image"]);
    }
    mdInstanceCache[key] = md;
  }

  return mdInstanceCache[key];
};

export const escapeHtmlCharacters = (content: string): string => {
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

export const protectBackslashesInLatex = (content: string): string => {
  if (!content) return content;

  try {
    // Match inline math: $...$
    const inlineRegex = /\$(.*?)\$/g;

    // Match block math: $$...$$
    const blockRegex = /\$\$([\s\S]*?)\$\$/g;

    // Replace backslashes in LaTeX blocks with placeholders to protect them
    // from HTML escaping. Only backslashes need protection — other characters
    // (<, >, &, ', ") are left for escapeHtmlCharacters to handle, and then
    // unescaped specifically within MathJax token rendering (see getMarkdownInstance).
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
    console.error("Error protecting LaTeX content:", error);
    return content;
  }
};

export const restoreBackslashesForLatex = (content: string): string => {
  if (!content) {
    return content;
  }

  try {
    // Restore only backslash placeholders — other characters (<, >, &, ', ")
    // are kept as HTML entities and unescaped within MathJax token rendering.
    let result = content.replace(/___LATEX_BACKSLASH___/g, "\\");

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

const kLetterListPattern = /^([a-zA-Z][).]\s.*?)$/gm;
const kCommonmarkReferenceLinkPattern = /\[([^\]]*)\]: (?!http)(.*)/g;

export const preRenderText = (txt: string): string => {
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

export const protectMarkdown = (txt: string): string => {
  if (!txt) return txt;

  return txt.replaceAll(
    kCommonmarkReferenceLinkPattern,
    "(open:767A125E)$1(close:767A125E) $2 ",
  );
};

export const unprotectMarkdown = (txt: string): string => {
  if (!txt) return txt;

  txt = txt.replaceAll("(open:767A125E)", "[");
  txt = txt.replaceAll("(close:767A125E)", "]");
  return txt;
};

export function unescapeSupHtmlEntities(str: string): string {
  if (!str) {
    return str;
  }
  return str
    .replace(/&lt;sup&gt;/g, "<sup>")
    .replace(/&lt;\/sup&gt;/g, "</sup>");
}

export function unescapeCodeHtmlEntities(str: string): string {
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
