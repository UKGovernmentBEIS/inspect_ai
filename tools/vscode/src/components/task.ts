import { TextDocument, Uri } from "vscode";
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
  line: number;
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

  let state: "seeking-task" | "seeking-function" | "reading-params" =
    "seeking-task";
  let startLine = -1;
  docLines.forEach((line, idx) => {
    switch (state) {
      case "seeking-task":
        if (kTaskPattern.test(line)) {
          startLine = idx;
          state = "seeking-function";
        }
        break;
      case "seeking-function":
        {
          const match = line.match(kFunctionNamePattern);
          if (match) {
            const fnName = match[1];
            const task: TaskData = {
              name: fnName,
              params: [],
              line: startLine,
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
      const params = parseParameters(paramsStr);
      params.forEach((param) => {
        task.params.push(param.trim());
      });
    }
  }
  return !kFunctionEndPattern.test(line);
};

const parseParameters = (paramStr: string): string[] => {
  let bracketDepth = 0;
  let currentParam = "";
  const params: string[] = [];

  // Accumulate chars, tracking brackets and only
  // pay attention to commas outside brackets
  for (let i = 0; i < paramStr.length; i++) {
    const char = paramStr[i];

    if (["[", "(", "{"].includes(char)) {
      bracketDepth++;
      currentParam += char;
    } else if (["]", ")", "}"].includes(char)) {
      bracketDepth--;
      currentParam += char;
    } else if (char === "," && bracketDepth === 0) {
      params.push(currentParam.trim());
      currentParam = "";
    } else {
      currentParam += char;
    }
  }

  // Add the last parameter (since there was no trailing comma)
  if (currentParam.trim()) {
    params.push(currentParam.trim());
  }

  // Extract parameter names
  return params
    .map((param) => {
      // Get everything before the colon (the parameter name)
      const nameMatch = param.match(/^\s*([a-zA-Z_][a-zA-Z0-9_]*)/);
      return nameMatch ? nameMatch[1] : "";
    })
    .filter(Boolean);
};
