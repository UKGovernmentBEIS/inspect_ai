import { window } from "vscode";

export const log = window.createOutputChannel("Inspect", { log: true });

export const startup = window.createOutputChannel("Inspect Startup", {
  log: true,
});

export const start = (message: string) => {
  startup.info(`Start: ${message}`);
};

export const end = (message: string) => {
  startup.info(`Done:  ${message}`);
};
