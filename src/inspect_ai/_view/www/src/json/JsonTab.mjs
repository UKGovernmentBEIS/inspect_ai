//@ts-check
/// <reference path="../types/prism.d.ts" />
import Prism from "prismjs";
import { html } from "htm/preact";
import { useEffect, useRef, useState } from "preact/hooks";

import { filename } from "../utils/Path.mjs";

import { DownloadPanel } from "../components/DownloadPanel.mjs";
import { FontSize } from "../appearance/Fonts.mjs";

const kPrismRenderMaxSize = 250000;
const kJsonMaxSize = 10000000;

/**
 * Renders JSON tab
 *
 * @param {Object} props - The parameters for the component.
 * @param {string} props.logFileName - function to render json raw text
 * @param {import("../Types.mjs").Capabilities} props.capabilities - Capabilities of the application host
 * @param {boolean} props.selected - Whether this tab is selected
 * @param {() => Promise<string>} props.renderJson - function to render json raw text
 * @returns {import("preact").JSX.Element} The Workspace component.
 */
export const JsonTab = ({
  logFileName,
  capabilities,
  selected,
  renderJson,
}) => {
  const codeRef = useRef(/** @type {HTMLElement|null} */ (null));
  const logFileNameRef = useRef(null);

  const [jsonText, setJsonText] = useState("");

  useEffect(() => {
    if (selected && logFileName && logFileNameRef.current !== logFileName) {
      renderJson().then((json) => {
        setJsonText(json);
        logFileNameRef.current = logFileName;
      });
    }
  }, [selected, logFileName, renderJson, setJsonText]);

  useEffect(() => {
    if (logFileNameRef.current !== logFileName) {
      setJsonText("");
    }
  }, [logFileName]);

  const renderedContent = [];
  if (jsonText.length > kJsonMaxSize && capabilities.downloadFiles) {
    // This JSON file is so large we can't really productively render it
    // we should instead just provide a DL link
    const file = `${filename(logFileName)}.json`;
    renderedContent.push(
      html`<${DownloadPanel}
        message="Log file raw JSON is too large to render."
        buttonLabel="Download JSON File"
        logFile=${logFileName}
        fileName=${file}
        fileContents=${jsonText}
      />`,
    );
  } else {
    if (codeRef.current) {
      if (jsonText.length < kPrismRenderMaxSize) {
        codeRef.current.innerHTML = Prism.highlight(
          jsonText,
          Prism.languages.javascript,
          "javacript",
        );
      } else {
        const textNode = document.createTextNode(jsonText);
        codeRef.current.innerText = "";
        codeRef.current.appendChild(textNode);
      }
    }
    renderedContent.push(
      html`<pre>
                <code id="task-json-contents" class="sourceCode" ref=${codeRef} style=${{
        fontSize: FontSize.small,
        whiteSpace: "pre-wrap",
        wordWrap: "anywhere",
      }}>
                </code>
              </pre>`,
    );
  }
  // note that we'e rendered
  return html` <div
    style=${{
      padding: "1rem",
      fontSize: FontSize.small,
      width: "100%",
    }}
  >
    ${renderedContent}
  </div>`;
};
