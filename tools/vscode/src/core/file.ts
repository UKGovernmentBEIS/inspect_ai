import { unlinkSync } from "node:fs";

import { log } from "./log";



export function removeFilesSync(filePaths: string[]) {
  filePaths.forEach(file => {
    try {
      unlinkSync(file);
    } catch (error) {
      log.appendLine(`Error deleting ${file}: ${String(error)}`);
    }
  });
}