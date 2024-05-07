import "./vscode-controls.css";
import "./task-config-webview.css";

import {
  provideVSCodeDesignSystem,
  allComponents,
} from "@vscode/webview-ui-toolkit";
import {
  fastCombobox,
  fastOption,
  provideFASTDesignSystem,
} from "@microsoft/fast-components";
import { DocumentState } from "../../workspace/workspace-state-provider";
import { showEmptyPanel, restoreInputState, whenChanged, setControlsVisible } from "./webview-utils";

// Load the vscode design system
provideVSCodeDesignSystem().register(allComponents);

// Declare the acquireVsCodeApi function to tell TypeScript about it
declare function acquireVsCodeApi(): any;

// Use the function to get the VS Code API handle
provideFASTDesignSystem().register(
  fastCombobox(),
  fastOption()
);

// Get access to the VS Code API from within the webview context
const vscode = acquireVsCodeApi();

// Process messages
window.addEventListener("message", (e) => {
  switch (e.data.type) {
    case "initialize":
      showEmptyPanel("No task selected", "configuration-controls");
      break;

    case "noInspect":
      showEmptyPanel("Inspect Package not installed.", "configuration-controls");
      break;

    case "setActiveTask":
      const placeholderPanel = document.querySelector(".empty-panel");
      if (placeholderPanel) {
        placeholderPanel.remove();
      }
      restoreState(e.data.state);
      attachListeners();

      const taskArgContainer = document.getElementById("task-args");
      if (taskArgContainer) {
        taskArgContainer.replaceChildren();
        if (e.data.task.activeTask?.params) {
          let count = 1;
          for (const param of e.data.task.activeTask.params) {
            const id = `task-param-${count}`;
            const textField = document.createElement("vscode-text-field");
            textField.id = id;
            textField.setAttribute("placeholder", "default");
            textField.classList.add("full-width");
            textField.innerText = param;
            if (e.data.state.params) {
              const paramValue = e.data.state.params[param];
              if (paramValue) {
                textField.setAttribute("value", paramValue);
              }
            }
            taskArgContainer.appendChild(textField);
            whenChanged(id, (value) => {
              setStateParam(param, value);
            });
            count++;
          }
          if (e.data.task.activeTask?.params.length === 0) {
            showEmptyPanel("No arguments for this task", undefined, "task-args");
          }
        }
        setControlsVisible("configuration-controls", true);
      }

      break;
  }
});

// Once loaded, initialize the process
window.addEventListener("load", main);

function restoreState(state?: DocumentState) {
  restoreInputState("epochs", state?.epochs);
  restoreInputState("limit", state?.limit);
  restoreInputState("temperature", state?.temperature);
  restoreInputState("max_tokens", state?.maxTokens);
  restoreInputState("top_p", state?.topP);
  restoreInputState("top_k", state?.topK);
}

function attachListeners() {
  whenChanged("epochs", (value) => {
    setStateValue("epochs", value);
  });

  whenChanged("limit", (value) => {
    setStateValue("limit", value);
  });

  whenChanged("temperature", (value) => {
    setStateValue("temperature", value);
  });

  whenChanged("max_tokens", (value) => {
    setStateValue("maxTokens", value);
  });

  whenChanged("top_p", (value) => {
    setStateValue("topP", value);
  });

  whenChanged("top_k", (value) => {
    setStateValue("topK", value);
  });
}

function main() {
  // Send the initialize message
  vscode.postMessage({
    command: "initialize",
  });
}

function setStateValue(key: string, value: string) {
  vscode.postMessage({
    command: "setStateValue",
    key,
    value,
  });
}

function setStateParam(key: string, value: string) {
  vscode.postMessage({
    command: "setStateParam",
    key,
    value,
  });
}
