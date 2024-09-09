// @ts-check
/// <reference path="../types/prism.d.ts" />
import Prism from "prismjs";
import "prismjs/components/prism-json";

import { html } from "htm/preact";
import { useRef } from "preact/hooks";
import { FontSize } from "../appearance/Fonts.mjs";

/**
 * A panel component to render JSON data with syntax highlighting.
 *
 * @param {Object} props - The component properties.
 * @param {unknown} props.data - The JSON data to be rendered.
 * @param {Object} [props.style] - Optional styles to apply to the panel.
 *
 * @returns {import('preact').JSX.Element} The rendered component.
 */
export const JSONPanel = ({ data, style }) => {
  const sourceCode = JSON.stringify(data, undefined, 2);
  const codeRef = useRef();

  if (codeRef.current) {
    // @ts-ignore
    codeRef.current.innerHTML = Prism.highlight(
      sourceCode,
      Prism.languages.javascript,
      "javacript",
    );
  }

  return html`<div>
    <pre
      style=${{
        background: "var(--bs-light)",
        width: "100%",
        padding: "0.5em",
        borderRadius: "var(--bs-border-radius)",
        ...style,
      }}
    >
    <code 
      ref=${codeRef}
      class="sourceCode-json" 
      style=${{
      fontSize: FontSize.small,
      whiteSpace: "pre-wrap",
      wordWrap: "anywhere",
    }}>
    </code>
    </pre>
  </div>`;
};
