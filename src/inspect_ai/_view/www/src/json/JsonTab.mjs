//@ts-check
import { html } from "htm/preact";

import { filename } from "../utils/Path.mjs";

import { DownloadPanel } from "../components/DownloadPanel.mjs";
import { FontSize } from "../appearance/Fonts.mjs";
import { JSONPanel } from "../components/JsonPanel.mjs";

const kJsonMaxSize = 10000000;

/**
 * Renders JSON tab
 *
 * @param {Object} props - The parameters for the component.
 * @param {string} props.logFileName - function to render json raw text
 * @param {import("../Types.mjs").Capabilities} props.capabilities - Capabilities of the application host
 * @param {boolean} props.selected - Whether this tab is selected
 * @param {string} props.json - json text
 * @returns {import("preact").JSX.Element} The Workspace component.
 */
export const JsonTab = ({ logFileName, capabilities, json }) => {
  const renderedContent = [];
  if (json.length > kJsonMaxSize && capabilities.downloadFiles) {
    // This JSON file is so large we can't really productively render it
    // we should instead just provide a DL link
    const file = `${filename(logFileName)}.json`;
    renderedContent.push(
      html`<${DownloadPanel}
        message="Log file raw JSON is too large to render."
        buttonLabel="Download JSON File"
        logFile=${logFileName}
        fileName=${file}
        fileContents=${json}
      />`,
    );
  } else {
    return html` <div
      style=${{
        padding: "0.5rem",
        fontSize: FontSize.small,
        width: "100%",
      }}
    >
      <${JSONPanel} id="task-json-contents" json=${json} simple=${true} />
    </div>`;
  }
};
