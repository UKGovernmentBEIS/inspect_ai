// @ts-check

import browserApi from "./api-browser.mjs";
import vscodeApi from "./api-vscode.mjs";
import simpleHttpApi, { simpleHttpSingleFileApi } from "./api-http.mjs";
import { getVscodeApi } from "../utils/vscode.mjs";
import { clientApi } from "./client-api.mjs";

//
/**
 * Resolves the client API
 *
 * @returns { import("./Types.mjs").ClientAPI } A Client API for the viewer
 */
const resolveApi = () => {
  // @ts-ignore
  if (getVscodeApi()) {
    return clientApi(vscodeApi);
  }

  // Check embedded script tag first
  const scriptEl = document.getElementById("log_dir_context");
  if (scriptEl) {
    const data = JSON.parse(scriptEl.textContent);
    if (data.log_file && !data.log_dir) {
      return clientApi(simpleHttpSingleFileApi(data.log_file));
    }
    if (data.log_dir) {
      return clientApi(simpleHttpApi(data.log_dir, data.log_file));
    }
  }

  // Check URL parameters
  const urlParams = new URLSearchParams(window.location.search);
  const logFile = urlParams.get("log_file");
  const logDir = urlParams.get("log_dir");

  if (logFile && !logDir) {
    return clientApi(simpleHttpSingleFileApi(logFile));
  }
  if (logDir) {
    return clientApi(simpleHttpApi(logDir, logFile));
  }

  // Default to browser API if no parameters found
  return clientApi(browserApi);
};

export default resolveApi();
