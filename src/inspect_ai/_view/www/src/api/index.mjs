import browserApi from "./api-browser.mjs";
import vscodeApi from "./api-vscode.mjs";

export default window.acquireVsCodeApi ? vscodeApi : browserApi;
