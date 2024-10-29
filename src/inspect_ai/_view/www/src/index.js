import { render } from "preact";
import { html } from "htm/preact";

import { App } from "./App.mjs";
import api from "./api/index.mjs";
import { getVscodeApi } from "./utils/vscode.mjs";
import { throttle } from "./utils/sync.mjs";

// Read any state from the page itself
const vscode = getVscodeApi();
let initialState = undefined;
if (vscode) {
  initialState = vscode.getState();
}

render(
  html`<${App}
    api=${api}
    initialState=${initialState}
    saveInitialState=${throttle((state) => {
      const vscode = getVscodeApi();
      if (vscode) {
        vscode.setState(state);
      }
    }, 1000)}
  />`,
  document.getElementById("app"),
);
