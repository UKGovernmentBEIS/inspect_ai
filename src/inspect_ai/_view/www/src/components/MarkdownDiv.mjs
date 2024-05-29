import { html } from "htm/preact";

showdown.setOption('simpleLineBreaks', true);
showdown.setOption('literalMidWordUnderscores', true);
const converter = new showdown.Converter();


export const MarkdownDiv = (props) => {
  const { markdown, style } = props;
  
  // Escape all HTML tags
  const escaped = DOMPurify.sanitize(markdown, { ALLOWED_TAGS: []});

  // Pre-render any text that isn't handled by markdown
  const preRendered = preRenderText(escaped);
  const renderedHtml = converter.makeHtml(preRendered);

  // Return the rendered markdown
  const markup = { __html: renderedHtml };
  return html`<div dangerouslySetInnerHTML=${markup} style=${style} class="${props.class ? props.class : ''} markdown-content" />`;
};


const kLetterListPattern = /^([a-zA-Z][\)\.]\s.*?)$/gm;
const kCommonmarkReferenceLinkPattern = /\[(.*)\]\:( +.+)/g;


const preRenderText = (txt) => {
  // Special handling for ordered lists that look like
  // multiple choice (e.g. a), b), c), d) etc..)
  const rendered = txt.replaceAll(kLetterListPattern, "<p style='margin-bottom: 0.2em;'>$1</p>");

  // Special handling for commonmark like reference links which might
  // look like:
  // [alias]: http://www.google.com
  // but text like:
  // [expert]: answer 
  // Also fools this
  return rendered.replaceAll(kCommonmarkReferenceLinkPattern, "\[$1\]:$2");
};