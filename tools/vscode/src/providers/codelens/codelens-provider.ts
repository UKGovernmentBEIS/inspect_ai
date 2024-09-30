import { CancellationToken, CodeLens, CodeLensProvider, Command, ExtensionContext, TextDocument, Uri, languages } from "vscode";
import { isNotebook } from "../../components/notebook";

export function activateCodeLens(context: ExtensionContext) {
  const provider = new InspectCodeLensProvider();
  const selector = { language: "python" };
  context.subscriptions.push(
    languages.registerCodeLensProvider(selector, provider)
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
      }
    ];
  }
}

class InspectCodeLensProvider implements CodeLensProvider {
  constructor() { }

  provideCodeLenses(
    document: TextDocument,
    token: CancellationToken
  ): CodeLens[] {
    const lenses: CodeLens[] = [];

    // respect cancellation request
    if (token.isCancellationRequested) {
      return [];
    }

    // Go through line by line and show a lens
    // for any task decorated functions
    for (let i = 0; i < document.lineCount; i++) {
      const line = document.lineAt(i);
      if (kTaskDecoratorPattern.test(line.text)) {
        // Get the function name from the next line (keep looking for next function)
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
const kTaskDecoratorPattern = /^\s*@task\b/;
const kFuncPattern = /^\s*def\s*(.*)\(.*$/;
