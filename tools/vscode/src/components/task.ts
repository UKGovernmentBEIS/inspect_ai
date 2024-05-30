
import {
  TextDocument,
  Uri,

} from "vscode";
import { lines } from "../core/text";


// Task information for a document
export interface DocumentTaskInfo {
  document: Uri;
  tasks: TaskData[];
  activeTask?: TaskData;
}

// Describes the current active task
export interface TaskData {
  name: string;
  params: string[];
  line: number
}

// Reads tasks from a TextDocument
// Quickly reads the default task using text based parsing
// This can't properly deal with things like selection, so this should only
// be used when no selection behavior is warranted
const kTaskPattern = /@task/;
const kFunctionNamePattern = /def\s+(.*)\((.*)$/;

const kFunctionEndPattern = /\s*\)\s*(->\s*\S+)?\s*:\s*/;
const kParamsPattern = /^(.*?)\s*(?:\)\s*:\s*|$|\)\s*(->\s*\S+)?\s*:\s*)/;

export function readTaskData(document: TextDocument): TaskData[] {
  const tasks: TaskData[] = [];
  const docLines = lines(document.getText());

  let state: "seeking-task" | "seeking-function" | "reading-params" = "seeking-task";
  let startLine = -1;
  docLines.forEach((line, idx) => {
    switch (state) {
      case "seeking-task":
        if (kTaskPattern.test(line)) {
          startLine = idx;
          state = "seeking-function";
        }
        break;
      case "seeking-function": {
        const match = line.match(kFunctionNamePattern);
        if (match) {
          const fnName = match[1];
          const task: TaskData = {
            name: fnName,
            params: [],
            line: startLine
          };
          tasks.push(task);

          const restOfLine = match[2];
          const keepReading = readParams(restOfLine, task);
          if (keepReading) {
            state = "reading-params";
          } else {
            // We've read the complete function, go
            // back to seeking tasks            
            state = "seeking-task";
          }
        }
      }
        break;
      case "reading-params": {
        const keepReading = readParams(line, tasks[tasks.length - 1]);
        if (keepReading) {
          state = "reading-params";
        } else {
          // We've read the complete function, go
          // back to seeking tasks
          state = "seeking-task";
        }
      }
    }
  });
  return tasks;
}


const readParams = (line: string, task: TaskData) => {
  const paramsMatch = line.match(kParamsPattern);
  if (paramsMatch) {
    const paramsStr = paramsMatch[1];
    if (paramsStr) {
      const params = paramsStr.split(",");
      params.forEach((param) => {
        const name = param.split("=")[0].trim();
        if (name && name.includes(':')) {
          task.params.push(name.split(':')[0]);
        } else if (name) {
          task.params.push(name);
        }
      });
    }
  }
  return !kFunctionEndPattern.test(line);
};
