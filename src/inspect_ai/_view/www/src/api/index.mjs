// @ts-check

import browserApi from "./api-browser.mjs";
import vscodeApi from "./api-vscode.mjs";
import simpleHttpApi from "./api-http.mjs";
import { dirname } from "../utils/Path.mjs";
import { getVscodeApi } from "../utils/vscode.mjs";

//
/**
 * Resolves the client API
 *
 * @returns { import("./Types.mjs").LogViewAPI } A Client API for the viewer
 */
const resolveApi = () => {
  // @ts-ignore
  if (getVscodeApi()) {
    return vscodeApi;
  } else {
    // See if there is an log_file, log_dir embedded in the
    // document or passed via URL
    const scriptEl = document.getElementById("log_dir_context");
    if (scriptEl) {
      // Read the contents
      const data = JSON.parse(scriptEl.textContent);
      if (data.log_dir || data.log_file) {
        const log_dir = data.log_dir || dirname(data.log_file);
        return simpleHttpApi(log_dir, data.log_file);
      }
    }

    // See if there is url params passing info
    const urlParams = new URLSearchParams(window.location.search);
    const log_file = urlParams.get("log_file");
    const log_dir = urlParams.get("log_dir");
    if (log_file || log_dir) {
      return simpleHttpApi(log_dir, log_file);
    }

    // No signal information so use the standard
    // browser API
    return browserApi;
  }
};

export default resolveApi();
