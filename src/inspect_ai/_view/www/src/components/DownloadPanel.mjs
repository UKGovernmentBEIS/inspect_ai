import { html } from "htm/preact";

import { DownloadButton } from "../components/DownloadButton.mjs";

export const DownloadPanel = ({
  message,
  buttonLabel,
  logFile,
  fileName,
  fileContents,
}) => {
  return html`<div
    style=${{
      display: "grid",
      gridTemplateRows: "content content",
      paddingTop: "3em",
      justifyItems: "center",
    }}
  >
    <div style=${{ fontSize: "0.9rem" }}>${message}</div>
    <${DownloadButton}
      label=${buttonLabel}
      logFile=${logFile}
      fileName=${fileName}
      fileContents=${fileContents}
    />
  </div>`;
};
