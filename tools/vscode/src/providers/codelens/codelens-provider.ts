import {
  CancellationToken,
  CodeLens,
  CodeLensProvider,
  Command,
  ExtensionContext,
  TextDocument,
  Uri,
  languages,
} from "vscode";
import { isNotebook } from "../../components/notebook";

export function activateCodeLens(context: ExtensionContext) {
  const provider = new InspectCodeLensProvider();
  const selector = { language: "python" };
  context.subscriptions.push(
    languages.registerCodeLensProvider(selector, provider),
  );
}

// The Code Lens commands
function taskCommands(uri: Uri, fn: string): Command[] {
  if (isNotebook(uri)) {
    return [
      {
        title: "$(play) Run Task",
        tooltip: "Execute this evaluation task.",
        command: "inspect.runTask",
        arguments: [uri, fn],
      },
    ];
  } else {
    return [
      {
        title: "$(debug-alt) Debug Task",
        tooltip: "Debug this evaluation task.",
        command: "inspect.debugTask",
        arguments: [uri, fn],
      },
      {
        title: "$(play) Run Task",
        tooltip: "Execute this evaluation task.",
        command: "inspect.runTask",
        arguments: [uri, fn],
      },
    ];
  }
}

export class InspectCodeLensProvider implements CodeLensProvider {
  private hasInspectImport(document: TextDocument): {
    hasImport: boolean;
    alias?: string;
  } {
    const text = document.getText();
    // Handle multiline imports by removing newlines between parentheses
    const normalizedText = text.replace(normalizeTextPattern, "($1)");

    const fromImportMatch = normalizedText.match(fromImportPattern);
    if (fromImportMatch) {
      return { hasImport: true, alias: fromImportMatch[1] };
    }
    if (hasImportPattern.test(normalizedText)) {
      return { hasImport: true };
    }
    return { hasImport: false };
  }

  provideCodeLenses(
    document: TextDocument,
    token: CancellationToken,
  ): CodeLens[] {
    const lenses: CodeLens[] = [];

    // respect cancellation request
    if (token.isCancellationRequested) {
      return [];
    }

    // Check for inspect import first
    const importInfo = this.hasInspectImport(document);
    if (!importInfo.hasImport) {
      return [];
    }

    // Go through line by line and show a lens
    // for any task decorated functions
    for (let i = 0; i < document.lineCount; i++) {
      const line = document.lineAt(i);
      const decoratorMatch = line.text.match(kDecoratorPattern);

      if (decoratorMatch) {
        const isInspectTask =
          decoratorMatch[1] !== undefined || // @inspect.task
          decoratorMatch[0] === "@task" || // @task (when from inspect import task)
          (importInfo.alias && decoratorMatch[2] === importInfo.alias); // @t (when from inspect import task as t)

        if (!isInspectTask) {
          continue;
        }

        // Get the function name from the next line
        let j = i + 1;
        while (j < document.lineCount) {
          const funcLine = document.lineAt(j);
          const match = funcLine.text.match(kFuncPattern);
          if (match) {
            taskCommands(document.uri, match[1]).forEach((cmd) => {
              lenses.push(new CodeLens(line.range, cmd));
            });
            break;
          }
          j++;
        }
      }
    }
    return lenses;
  }
}

const fromImportPattern =
  /from\s+inspect_ai\s+import\s+(?:\(\s*)?(?:[\w,\s]*,\s*)?task(?:\s+as\s+(\w+))?/;
const hasImportPattern = /import\s+inspect_ai\b/;
const kFuncPattern = /^\s*def\s*(.*)\(.*$/;
const kDecoratorPattern = /^\s*@(inspect_ai\.)?task\b|@(\w+)\b/;
const normalizeTextPattern = /\(\s*\n\s*([^)]+)\s*\n\s*\)/g;
