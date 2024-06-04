import "./vscode-controls.css";
import "./env-config-webview.css";

import { EnvConfiguration } from "../env-config-provider"

import {
  provideVSCodeDesignSystem,
  allComponents,
} from "@vscode/webview-ui-toolkit";
import { debounce } from "lodash";
import { fastCombobox, fastOption, provideFASTDesignSystem } from "@microsoft/fast-components";
import { showEmptyPanel, kBounceInterval, restoreInputState, restoreSelectState } from "./webview-utils";

const kModelInfo: Record<string, string> = {
  openai: "https://platform.openai.com/docs/models/overview",
  anthropic: "https://docs.anthropic.com/claude/docs/models-overview",
  google: "https://cloud.google.com/vertex-ai/generative-ai/docs/learn/models",
  mistral: "https://docs.mistral.ai/platform/endpoints/",
  hf: "https://huggingface.co/models?pipeline_tag=text-generation&sort=trending",
  together: "https://docs.together.ai/docs/inference-models#chat-models",
  bedrock: "https://aws.amazon.com/bedrock/",
  azureai: "https://ai.azure.com/explore/models",
  cf: "https://developers.cloudflare.com/workers-ai/models/#text-generation",
};

// Load the vscode design system
provideVSCodeDesignSystem().register(allComponents);

// Declare the acquireVsCodeApi function to tell TypeScript about it
declare function acquireVsCodeApi(): any;

// Use the function to get the VS Code API handle
provideFASTDesignSystem()
  .register(
    fastCombobox(),
    fastOption(),
  );

// Get access to the VS Code API from within the webview context
const vscode = acquireVsCodeApi();

// Process messages
window.addEventListener("message", (e) => {
  switch (e.data.type) {
    case "initialize":

      // Set the env values
      const env = e.data.message.env;
      restoreEnv(env);

      const controls = document.getElementById("configuration-controls");
      controls?.classList.remove("hidden");

      attachListeners();


      break;
    case "envChanged":

      // Set the state values
      restoreEnv(e.data.message.env);
      break;

    case "noInspect":
      showEmptyPanel("Inspect package not installed", "configuration-controls");

  }
});

// Once loaded, initialize the process
window.addEventListener("load", main);

function main() {
  // Send the initialize message
  vscode.postMessage({
    command: "initialize",
  });
}

function getModelEl() {
  return document.getElementById("model") as HTMLInputElement;
}

function getProviderEl() {
  return document.getElementById("provider") as HTMLSelectElement;
}

function getProviderText() {
  const providerEl = getProviderEl();
  return providerEl.value;
}

function resetModel() {
  const modelEl = getModelEl();
  modelEl.value = "";
}

function showProviderHelp() {
  const providerEl = getProviderEl();

  // Shows a help icon next to the model name with additional model details
  let modelHelpEl = document.getElementById("model-help");
  if (modelHelpEl && !providerEl.value) {
    modelHelpEl.remove();
  } else {
    if (providerEl.value) {
      if (kModelInfo[getProviderText()]) {
        if (!modelHelpEl) {
          modelHelpEl = document.createElement("vscode-link");
          modelHelpEl.id = "model-help";
          modelHelpEl.setAttribute("title", "Available Models");
          const questionEl = document.createElement("div");
          questionEl.classList.add("codicon");
          questionEl.classList.add("codicon-question");
          modelHelpEl.appendChild(questionEl);

          const labelContainerEl = document.getElementById("provider-label-container");
          labelContainerEl?.appendChild(modelHelpEl);
          modelHelpEl.addEventListener("click", () => {
            openUrl(kModelInfo[getProviderText()]);
          });
        }
      } else {
        if (modelHelpEl) {
          modelHelpEl.remove();
        }
      }
    }
  }
}

const restoreEnv = (config: EnvConfiguration) => {
  restoreSelectState("provider", config.provider);
  restoreInputState("model", config.model);
  restoreInputState("model-base-url", config.modelBaseUrl);

  restoreInputState("max-connections", config.maxConnections);
  restoreInputState("max-retries", config.maxRetries);
  restoreInputState("timeout", config.timeout);

  restoreInputState("log-dir", config.logDir);
  restoreSelectState("log-level", config.logLevel);

  showProviderHelp();
};


const attachListeners = () => {

  const providerChanged = (e: Event) => {
    // If the user chooses 'none' from the dropdown, this will fire
    const txt = getProviderText();
    if (txt === "") {
      getProviderEl().value = "";
    }
    if (e.target) {
      setEnvValue("provider", txt);
      resetModel();
      showProviderHelp();
    }
  }

  const el = document.getElementById("provider") as HTMLSelectElement;

  el.addEventListener("change", providerChanged);

  setEnvWhenKeyup("model", "model");

  setEnvWhenKeyup("model-base-url", "modelBaseUrl");

  const showBaseUrlEl = document.getElementById("show-base-url") as HTMLAnchorElement;
  showBaseUrlEl.addEventListener("click", () => {
    toggleBaseUrl();
  });


  setEnvWhenKeyup("max-connections", "maxConnections");
  setEnvWhenValueChanged("max-connections", "maxConnections");
  setEnvWhenKeyup("max-retries", "maxRetries");
  setEnvWhenValueChanged("max-retries", "maxRetries");
  setEnvWhenKeyup("timeout", "timeout");
  setEnvWhenValueChanged("timeout", "timeout");

  setEnvWhenKeyup("log-dir", "logDir");
  setEnvWhenValueChanged("log-level", "logLevel");
};


const setEnvWhenKeyup = (id: string, key: string, fn?: () => void) => {
  const el = document.getElementById(id) as HTMLInputElement;
  if (el) {
    el.addEventListener(
      "keyup",
      debounce((e: Event) => {
        if (e.target) {
          setEnvValue(key, (e.target as HTMLInputElement).value);
        }
        if (fn) {
          fn();
        }
      }, kBounceInterval)
    );
  }
};

const setEnvWhenValueChanged = (
  id: string,
  key: string,
  fn?: () => void,
) => {
  const el = document.getElementById(id) as HTMLSelectElement;
  el.addEventListener("change", (e: Event) => {
    if (e.target) {
      const index = el.selectedIndex;
      const value = index > -1 ? el.options[index].value : el.value;
      setEnvValue(key, value);
    }
    if (fn) {
      fn();
    }
  });
};

function setEnvValue(key: string, value: string) {
  vscode.postMessage({
    command: "setEnvValue",
    default: key,
    value,
  });
}


function openUrl(url: string) {
  vscode.postMessage({
    command: "openUrl",
    url
  })
}

function toggleBaseUrl() {
  const baseUrlContainerEl = document.getElementById("model-base-url-container");
  if (baseUrlContainerEl) {
    const hidden = baseUrlContainerEl.classList.contains("hidden");
    if (hidden) {
      baseUrlContainerEl.classList.remove("hidden");
    } else {
      baseUrlContainerEl.classList.add("hidden");
    }
  }
}