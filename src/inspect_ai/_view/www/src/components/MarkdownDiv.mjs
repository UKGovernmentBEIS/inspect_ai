import markdownit from "markdown-it";
import { html } from "htm/preact";

export const MarkdownDiv = (props) => {
  const { markdown, style } = props;

  // Escape all tags
  const escaped = markdown ? escape(markdown) : "";

  // Pre-render any text that isn't handled by markdown
  const preRendered = preRenderText(escaped);

  const protectedText = protectMarkdown(preRendered);

  let renderedHtml = protectedText;
  try {
    const md = markdownit({
      breaks: true,
      html: true,
    });
    renderedHtml = md.render(protectedText);
  } catch (ex) {
    console.log("Unable to markdown render content");
    console.error(ex);
  }

  const unescaped = unprotectMarkdown(renderedHtml);

  // For `code` tags, reverse the escaping if we can
  const withCode = unescapeCodeHtmlEntities(unescaped);

  // Return the rendered markdown
  const markup = { __html: withCode };

  return html`<div
    dangerouslySetInnerHTML=${markup}
    style=${style}
    class="${props.class ? `${props.class} ` : ""}markdown-content"
  />`;
};

const kLetterListPattern = /^([a-zA-Z][).]\s.*?)$/gm;
const kCommonmarkReferenceLinkPattern = /\[([^\]]*)\]: (?!http)(.*)/g;

const preRenderText = (txt) => {
  // eslint-disable-next-line no-misleading-character-class
  txt = txt.replace(/^[\u200B\u200C\u200D\u200E\u200F\uFEFF]/, "");

  // Special handling for ordered lists that look like
  // multiple choice (e.g. a), b), c), d) etc..)
  return txt.replaceAll(
    kLetterListPattern,
    "<p style='margin-bottom: 0.2em;'>$1</p>",
  );
};

const protectMarkdown = (txt) => {
  // Special handling for commonmark like reference links which might
  // look like:
  // [alias]: http://www.google.com
  // but text like:
  // [expert]: answer
  // Also fools this
  return txt.replaceAll(
    kCommonmarkReferenceLinkPattern,
    "(open:767A125E)$1(close:767A125E) $2 ",
  );
};

const unprotectMarkdown = (txt) => {
  txt = txt.replaceAll("(open:767A125E)", "[");
  txt = txt.replaceAll("(close:767A125E)", "]");
  return txt;
};

const escape = (content) => {
  return content.replace(/[<>&'"]/g, function (c) {
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
    }
  });
};

function unescapeCodeHtmlEntities(str) {
  const htmlEntities = {
    "&lt;": "<",
    "&gt;": ">",
    "&amp;": "&",
    "&#x5C;": "\\",
    "&quot;": '"',
  };

  return str.replace(
    /(<code[^>]*>)([\s\S]*?)(<\/code>)/gi,
    function (match, starttag, content, endtag) {
      return (
        starttag +
        content.replace(
          /&(?:amp|lt|gt|quot|#39|#x2F|#x5C|#96);/g,
          function (entity) {
            return htmlEntities[entity] || entity;
          },
        ) +
        endtag
      );
    },
  );
}
