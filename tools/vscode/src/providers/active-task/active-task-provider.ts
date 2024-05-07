import {
  DocumentSymbol,
  Event,
  EventEmitter,
  ExtensionContext,
  Position,
  Range,
  Selection,
  SymbolKind,
  TextDocument,
  Uri,
  commands,
  window,
} from "vscode";
import { sleep } from "../../core/wait";
import {
  DebugActiveTaskCommand,
  RunActiveTaskCommand,
} from "./active-task-command";
import { InspectEvalManager } from "../inspect/inspect-eval";
import { Command } from "../../core/command";

// Activates the provider which tracks the curently active task (document and task name)
export function activateActiveTaskProvider(
  inspectEvalManager: InspectEvalManager,
  context: ExtensionContext
): [Command[], ActiveTaskManager] {
  const activeTaskManager = new ActiveTaskManager(context);

  const commands = [
    new RunActiveTaskCommand(activeTaskManager, inspectEvalManager),
    new DebugActiveTaskCommand(activeTaskManager, inspectEvalManager),
  ];
  return [commands, activeTaskManager];
}

// Task information for a document
export interface ActiveTaskInfo {
  document: Uri;
  tasks: TaskData[];
  activeTask?: TaskData;
}

// Describes the current active task
export interface TaskData {
  name: string;
  params: string[];
}

// Fired when the active task changes
export interface ActiveTaskChangedEvent {
  activeTaskInfo?: ActiveTaskInfo;
}

// Tracks task information for the current editor
export class ActiveTaskManager {
  constructor(context: ExtensionContext) {
    // Listen for the editor changing and udpate task state
    // when there is a new selection
    context.subscriptions.push(
      window.onDidChangeTextEditorSelection(async (event) => {
        await this.updateActiveTask(
          event.textEditor.document,
          event.selections[0]
        );
      })
    );

    context.subscriptions.push(window.onDidChangeActiveTextEditor(async (event) => {
      if (event) {
        await this.updateActiveTask(
          event.document
        );
      }
    }));
  }
  private activeTaskInfo_: ActiveTaskInfo | undefined;
  private readonly onActiveTaskChanged_ = new EventEmitter<ActiveTaskChangedEvent>();

  // Event to be notified when task information changes
  public readonly onActiveTaskChanged: Event<ActiveTaskChangedEvent> = this.onActiveTaskChanged_.event;

  // Get the task information for the current selection
  public getActiveTaskInfo(): ActiveTaskInfo | undefined {
    return this.activeTaskInfo_;
  }

  // Refresh the task information for the current editor
  public async refresh() {
    const currentSelection = window.activeTextEditor?.selection;
    const currentDocument = window.activeTextEditor?.document;
    await this.updateActiveTask(currentDocument, currentSelection);
  }

  async updateActiveTask(document?: TextDocument, selection?: Selection) {
    let taskActive = false;
    if (document && selection) {
      if (document.languageId === "python") {
        const activeTaskInfo = await getTaskInfo(document, selection);
        this.setActiveTaskInfo(activeTaskInfo);
        taskActive = activeTaskInfo !== undefined;
      }
      await commands.executeCommand(
        "setContext",
        "inspect_ai.activeTask",
        taskActive
      );
    }
  }

  // Set the task information
  setActiveTaskInfo(task?: ActiveTaskInfo) {
    if (this.activeTaskInfo_ !== task) {
      this.activeTaskInfo_ = task;
      this.onActiveTaskChanged_.fire({ activeTaskInfo: this.activeTaskInfo_ });
    }
  }
}

async function getTaskInfo(
  document: TextDocument,
  selection: Selection
): Promise<ActiveTaskInfo | undefined> {
  // Try to get symbols to read task info for this document
  // Note that the retry is here since the symbol provider
  // has latency in loading and there wasn't a way to wait
  // on it specifically (waiting on the Python extension didn't work)
  let symbols: DocumentSymbol[] | undefined;
  let count = 0;
  do {
    symbols = await commands.executeCommand<DocumentSymbol[]>(
      "vscode.executeDocumentSymbolProvider",
      document.uri
    );
    count++;
    await sleep(500);
  } while (count <= 5 && !symbols);

  if (symbols) {
    const functionSymbols = symbols.filter(
      (symbol) => symbol.kind === SymbolKind.Function
    );

    const tasks: TaskData[] = [];
    let activeTask = undefined;

    if (functionSymbols) {
      functionSymbols.forEach((symbol) => {
        if (isTask(document, symbol)) {
          const signatureRange = getSignatureRange(document, symbol);

          const variables = symbol.children.filter(
            (child) => child.kind === SymbolKind.Variable
          );
          const params = variables
            .filter((variable) => {
              return signatureRange?.contains(variable.range);
            })
            .map((variable) => variable.name);

          const task = {
            name: symbol.name,
            params,
          };
          tasks.push(task);

          if (symbol.range.contains(selection.start)) {
            activeTask = task;
          }
        }
      });
    }

    // If there are tasks in this file, just consider the first task active
    if (tasks.length > 0 && !activeTask) {
      activeTask = tasks[0];
    }

    return {
      document: document.uri,
      tasks,
      activeTask,
    };
  }
}

function isTask(document: TextDocument, symbol: DocumentSymbol) {
  const functionText = document.getText(symbol.range);
  if (functionText.startsWith("@task")) {
    return true;
  }
}

function getSignatureRange(document: TextDocument, symbol: DocumentSymbol) {
  const functionText = document.getText(symbol.range);

  // Split the text into lines to process it line-by-line
  const lines = functionText.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith("def") && line.trim().endsWith(":")) {
      // Calculate the end position of the function definition line
      const startLine = symbol.range.start.line + i;
      const endLine = startLine;

      // End at the end of the definition line
      const endCharacter = line.length;

      // Create a new range for just the definition
      return new Range(
        new Position(startLine, 0),
        new Position(endLine, endCharacter)
      );
    }
  }
}