import { html } from "htm/preact";

showdown.setOption("simpleLineBreaks", true);
showdown.setOption("literalMidWordUnderscores", true);
const converter = new showdown.Converter();

export const MarkdownDiv = (props) => {
  const { markdown, style } = props;

  // Escape all tags
  const escaped = markdown ? escape(markdown) : "";

  // Pre-render any text that isn't handled by markdown
  const preRendered = preRenderText(escaped);
  const renderedHtml = converter.makeHtml(preRendered);

  // For `code` tags, reverse the escaping if we can
  const withCode = unescapeCodeHtmlEntities(renderedHtml);

  // Return the rendered markdown
  const markup = { __html: withCode };

  return html`<div
    dangerouslySetInnerHTML=${markup}
    style=${style}
    class="${props.class ? `${props.class} ` : ""}markdown-content"
  />`;
};

const kLetterListPattern = /^([a-zA-Z][).]\s.*?)$/gm;
const kCommonmarkReferenceLinkPattern = /\[(.*)\]:( +.+)/g;

const preRenderText = (txt) => {
  // Special handling for ordered lists that look like
  // multiple choice (e.g. a), b), c), d) etc..)
  const rendered = txt.replaceAll(
    kLetterListPattern,
    "<p style='margin-bottom: 0.2em;'>$1</p>",
  );

  // Special handling for commonmark like reference links which might
  // look like:
  // [alias]: http://www.google.com
  // but text like:
  // [expert]: answer
  // Also fools this
  return rendered.replaceAll(kCommonmarkReferenceLinkPattern, "[$1]:$2");
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
