

import { window } from "vscode";

export const log = window.createOutputChannel("Inspect", { log: true });

export const start = (message: string) => {
  log.info(`Start: ${message}`);
}

export const end = (message: string) => {
  log.info(`Done:  ${message}`);
}