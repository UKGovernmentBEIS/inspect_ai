import JSON5 from "json5";
import { dirname } from "../../utils/path";
import { getVscodeApi } from "../../utils/vscode";
import { clientApi } from "./client-api";
import staticHttpApi from "./static-http/api-static-http";
import { ClientAPI } from "./types";
import { viewServerApi } from "./view-server/api-view-server";
import vscodeApi from "./vscode/api-vscode";

/**
 * Resolves the client API
 */
const resolveApi = (): ClientAPI => {
  const debug = false;
  if (getVscodeApi()) {
    // This is VSCode
    return clientApi(vscodeApi, undefined, debug);
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
          const api = staticHttpApi(log_dir, data.log_file);
          return clientApi(api, data.log_file, debug);
        }
      }
    }

    // See if there is url params passing info (could be hosted)
    const urlParams = new URLSearchParams(window.location.search);
    const log_file = urlParams.get("log_file");
    const log_dir = urlParams.get("log_dir");
    const forceViewServerApi = urlParams.get("inspect_server") === "true";

    const resolved_log_dir = log_dir ?? undefined;
    const resolved_log_file = log_file ?? undefined;

    if (forceViewServerApi) {
      return clientApi(
        viewServerApi({ logDir: resolved_log_dir }),
        resolved_log_file,
        debug,
      );
    }

    if (resolved_log_dir !== undefined || resolved_log_file !== undefined) {
      return clientApi(
        staticHttpApi(resolved_log_dir, resolved_log_file),
        resolved_log_file,
        debug,
      );
    }

    // No signal information so use the standard
    // view server API (inspect view)
    return clientApi(viewServerApi(), undefined, debug);
  }
};

export default resolveApi();
