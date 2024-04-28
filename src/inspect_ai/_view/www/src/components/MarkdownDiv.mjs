import { html } from "htm/preact";

showdown.setOption('simpleLineBreaks', true);
const converter = new showdown.Converter();


export const MarkdownDiv = (props) => {
  const { markdown, style } = props;

  // Pre-render any text that isn't handled by markdown
  const preRenderedMarkdown = preRenderAlphaLists(markdown);

  // Render the markdown and sanitize the output
  const dirtyHtml = converter.makeHtml(preRenderedMarkdown);
  const cleanHtml = DOMPurify.sanitize(dirtyHtml);
  
  // Return the rendered markdown
  const markup = { __html: cleanHtml };
  return html`<div dangerouslySetInnerHTML=${markup} style=${style} class="${props.class ? props.class : ''} markdown-content" />`;
};


// Special handling for ordered lists that look like
// multiple choice (e.g. a), b), c), d) etc..)
const kLetterListPattern = /^([a-zA-Z][\)\.]\s.*?)$/gm;
const preRenderAlphaLists = (txt) => {
  return txt.replaceAll(kLetterListPattern, "<p style='margin-bottom: 0.2em;'>$1</p>");
}