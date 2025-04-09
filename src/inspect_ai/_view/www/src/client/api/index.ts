import JSON5 from "json5";
import { dirname } from "../../utils/path";
import { getVscodeApi } from "../../utils/vscode";
import browserApi from "./api-browser";
import simpleHttpApi from "./api-http";
import vscodeApi from "./api-vscode";
import { clientApi } from "./client-api";
import { ClientAPI } from "./types";

//
/**
 * Resolves the client API
 */
const resolveApi = (): ClientAPI => {
  if (getVscodeApi()) {
    // This is VSCode
    return clientApi(vscodeApi);
  } else {
    // See if there is an log_file, log_dir embedded in the
    // document or passed via URL (could be hosted)
    const scriptEl = document.getElementById("log_dir_context");
    if (scriptEl) {
      // Read the contents
      const context = scriptEl.textContent;
      if (context !== null) {
        const data = JSON5.parse(context);
        if (data.log_dir || data.log_file) {
          const log_dir = data.log_dir || dirname(data.log_file);
          const api = simpleHttpApi(log_dir, data.log_file);
          return clientApi(api, data.log_file);
        }
      }
    }

    // See if there is url params passing info (could be hosted)
    const urlParams = new URLSearchParams(window.location.search);
    const log_file = urlParams.get("log_file");
    const log_dir = urlParams.get("log_dir");
    if (log_file !== null || log_dir !== null) {
      const resolved_log_dir = log_dir === null ? undefined : log_dir;
      const resolved_log_file = log_file === null ? undefined : log_file;
      const api = simpleHttpApi(resolved_log_dir, resolved_log_file);
      return clientApi(api, resolved_log_file);
    }

    // No signal information so use the standard
    // browser API (inspect view)
    return clientApi(browserApi);
  }
};

export default resolveApi();
