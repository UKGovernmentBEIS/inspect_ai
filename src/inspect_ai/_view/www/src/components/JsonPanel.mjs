// @ts-check
/// <reference path="../types/prism.d.ts" />
import Prism from "prismjs";
import "prismjs/components/prism-json";

import { html } from "htm/preact";
import { useRef } from "preact/hooks";
import { FontSize } from "../appearance/Fonts.mjs";

const kPrismRenderMaxSize = 250000;

/**
 * A panel component to render JSON data with syntax highlighting.
 *
 * @param {Object} props - The component properties.
 * @param {string} [props.id] - The code element id
 * @param {unknown} [props.data] - The JSON data to be rendered.
 * @param {string} [props.json] - The JSON data to be rendered.
 * @param {boolean} [props.simple] - Simple styling
 * @param {Object} [props.style] - Optional styles to apply to the panel.
 *
 * @returns {import('preact').JSX.Element} The rendered component.
 */
export const JSONPanel = ({ id, json, data, simple, style }) => {
  const sourceCode = json || JSON.stringify(data, undefined, 2);
  const codeRef = useRef();

  if (codeRef.current) {
    if (sourceCode.length < kPrismRenderMaxSize) {
      // @ts-ignore
      codeRef.current.innerHTML = Prism.highlight(
        sourceCode,
        Prism.languages.javascript,
        "javacript",
      );
    } else {
      const textNode = document.createTextNode(sourceCode);
      // @ts-ignore
      codeRef.current.innerText = "";
      // @ts-ignore
      codeRef.current.appendChild(textNode);
    }
  }

  return html`<div>
    <pre
      style=${{
        background: simple ? undefined : "var(--bs-light)",
        width: "100%",
        padding: "0.5em",
        borderRadius: simple ? undefined : "var(--bs-border-radius)",
        ...style,
      }}
    >
    <code 
      id=${id}
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
