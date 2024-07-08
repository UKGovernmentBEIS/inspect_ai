import { html } from "htm/preact";
import api from "../api/index.mjs";

export const DownloadButton = ({ logFile, label, fileName, fileContents }) => {
  return html`<button
    class="btn btn-outline-primary"
    style=${{ fontSize: "0.9em", marginTop: "3em" }}
    onclick=${async () => {
      await api.download_file(logFile, fileName, fileContents);
    }}
  >
    ${label}
  </button>`;
};
