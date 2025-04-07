import * as assert from "assert";
import {
  CancellationToken,
  Position,
  Range,
  TextDocument,
  TextLine,
  EndOfLine,
  Uri,
} from "vscode";
import { InspectCodeLensProvider } from "../providers/codelens/codelens-provider";

class MockTextLine implements TextLine {
  constructor(
    private lineText: string,
    private _lineNumber: number,
  ) {}

  get text(): string {
    return this.lineText;
  }
  get lineNumber(): number {
    return this._lineNumber;
  }
  get range(): Range {
    return new Range(
      new Position(this._lineNumber, 0),
      new Position(this._lineNumber, this.lineText.length),
    );
  }
  get rangeIncludingLineBreak(): Range {
    return this.range;
  }
  get firstNonWhitespaceCharacterIndex(): number {
    return 0;
  }
  get isEmptyOrWhitespace(): boolean {
    return this.lineText.trim().length === 0;
  }
}

class MockTextDocument implements TextDocument {
  private lines: string[];

  constructor(content: string) {
    this.lines = content.split("\n");
  }

  get lineCount(): number {
    return this.lines.length;
  }

  lineAt(lineOrPos: number | Position): TextLine {
    const line = typeof lineOrPos === "number" ? lineOrPos : lineOrPos.line;
    return new MockTextLine(this.lines[line], line);
  }

  getText(): string {
    return this.lines.join("\n");
  }

  // Implement other required interface members with mock values
  get uri(): Uri {
    return { scheme: "file", path: "test.py" } as Uri;
  }
  get fileName(): string {
    return "test.py";
  }
  get isUntitled(): boolean {
    return false;
  }
  get languageId(): string {
    return "python";
  }
  get version(): number {
    return 1;
  }
  get isDirty(): boolean {
    return false;
  }
  get isClosed(): boolean {
    return false;
  }
  save(): Thenable<boolean> {
    return Promise.resolve(true);
  }
  offsetAt(): number {
    return 0;
  }
  positionAt(): Position {
    return new Position(0, 0);
  }
  getWordRangeAtPosition(): Range | undefined {
    return undefined;
  }
  validateRange(range: Range): Range {
    return range;
  }
  validatePosition(): Position {
    return new Position(0, 0);
  }
  get eol(): EndOfLine {
    return EndOfLine.LF;
  }
}

suite("CodeLens Provider Test Suite", () => {
  let provider: InspectCodeLensProvider;
  let cancellationToken: CancellationToken;

  setup(() => {
    provider = new InspectCodeLensProvider();
    cancellationToken = {
      isCancellationRequested: false,
      onCancellationRequested: () => ({ dispose: () => {} }),
    };
  });

  function createDocument(content: string): TextDocument {
    return new MockTextDocument(content);
  }

  test('should return code lenses when using "from inspect import task"', () => {
    const document = createDocument(`
from inspect_ai import task

@task
def my_task():
    pass`);

    const lenses = provider.provideCodeLenses(document, cancellationToken);
    assert.strictEqual(
      lenses.length,
      2,
      "Should return two lenses (run and debug) for inspect task",
    );
  });

  test('should return code lenses when using "from inspect import task as t"', () => {
    const document = createDocument(`
from inspect_ai import task as t

@t
def my_task():
    pass`);

    const lenses = provider.provideCodeLenses(document, cancellationToken);
    assert.strictEqual(
      lenses.length,
      2,
      "Should return lenses when task is imported with alias",
    );
  });

  test('should return code lenses when using "import inspect"', () => {
    const document = createDocument(`
import inspect_ai

@inspect_ai.task
def my_task():
    pass`);

    const lenses = provider.provideCodeLenses(document, cancellationToken);
    assert.strictEqual(
      lenses.length,
      2,
      "Should return lenses when using full inspect import",
    );
  });

  test("should handle multiple task decorators in the same file", () => {
    const document = createDocument(`
from inspect_ai import task

@task
def first_task():
    pass

@task
def second_task():
    pass`);

    const lenses = provider.provideCodeLenses(document, cancellationToken);
    assert.strictEqual(lenses.length, 4, "Should return lenses for both tasks");
  });

  test("should not return code lenses for non-inspect task decorator", () => {
    const document = createDocument(`
from pytask import task

@task
def other_task():
    pass`);

    const lenses = provider.provideCodeLenses(document, cancellationToken);
    assert.strictEqual(
      lenses.length,
      0,
      "Should not return code lenses for non-inspect task",
    );
  });

  test("should handle task decorator without following function", () => {
    const document = createDocument(`
from inspect import task

@task
# Some comment here`);

    const lenses = provider.provideCodeLenses(document, cancellationToken);
    assert.strictEqual(
      lenses.length,
      0,
      "Should handle malformed task decorator safely",
    );
  });

  test("should handle empty document", () => {
    const document = createDocument("");
    const lenses = provider.provideCodeLenses(document, cancellationToken);
    assert.strictEqual(lenses.length, 0, "Should handle empty document safely");
  });

  test("Should handle multiline import statements", () => {
    const document = createDocument(`
from inspect_ai import (
    Task,
    task as t,
)

@t
def my_task():
    pass`);

    const lenses = provider.provideCodeLenses(document, cancellationToken);
    assert.strictEqual(
      lenses.length,
      2,
      "Should return lenses for multiline import",
    );
  });

  test("Should handle multiple imports in a single line", () => {
    const document = createDocument(`
from inspect_ai import Task, task as t

@t
def my_task():
    pass`);

    const lenses = provider.provideCodeLenses(document, cancellationToken);
    assert.strictEqual(
      lenses.length,
      2,
      "Should return lenses for multiple imports in a single line",
    );
  });

  test("Should handle task decorator without import", () => {
    const document = createDocument(`
@task
def my_task():
    pass`);

    const lenses = provider.provideCodeLenses(document, cancellationToken);
    assert.strictEqual(
      lenses.length,
      0,
      "Should return lenses for task decorator without import",
    );
  });
});
