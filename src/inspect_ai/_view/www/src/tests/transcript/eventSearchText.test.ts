import { eventSearchText } from "../../app/samples/transcript/eventSearchText";
import { EventNode } from "../../app/samples/transcript/types";

const makeNode = (event: Record<string, unknown>): EventNode => {
  return new EventNode("test-id", event as never, 0);
};

describe("eventSearchText", () => {
  test("score: includes 'Intermediate Score' for intermediate scores", () => {
    const texts = eventSearchText(
      makeNode({
        event: "score",
        score: { answer: "yes", explanation: "partial", value: 0.5 },
        target: null,
        intermediate: true,
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Intermediate Score");
  });

  test("score: includes 'Score' for non-intermediate scores", () => {
    const texts = eventSearchText(
      makeNode({
        event: "score",
        score: { answer: "yes", explanation: "correct", value: "C" },
        target: "expected",
        intermediate: false,
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Score");
    expect(texts).not.toContain("Intermediate Score");
  });

  test("score_edit: includes 'Edit Score' title", () => {
    const texts = eventSearchText(
      makeNode({
        event: "score_edit",
        edit: { answer: "new", explanation: "fixed", provenance: null },
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Edit Score");
  });

  test("sample_limit: maps all limit types to titles", () => {
    const typeToTitle: Record<string, string> = {
      custom: "Custom Limit Exceeded",
      time: "Time Limit Exceeded",
      message: "Message Limit Exceeded",
      token: "Token Limit Exceeded",
      operator: "Operator Canceled",
      working: "Execution Time Limit Exceeded",
      cost: "Cost Limit Exceeded",
    };
    for (const [type, expectedTitle] of Object.entries(typeToTitle)) {
      const texts = eventSearchText(
        makeNode({
          event: "sample_limit",
          type,
          message: "",
          timestamp: "2024-01-01T00:00:00Z",
        }),
      );
      expect(texts).toContain(expectedTitle);
    }
  });

  test("approval: includes decision label", () => {
    const decisions: Record<string, string> = {
      approve: "Approved",
      reject: "Rejected",
      terminate: "Terminated",
    };
    for (const [decision, expected] of Object.entries(decisions)) {
      const texts = eventSearchText(
        makeNode({
          event: "approval",
          decision,
          explanation: "",
          timestamp: "2024-01-01T00:00:00Z",
        }),
      );
      expect(texts).toContain(expected);
    }
  });

  test("sandbox: includes action in title", () => {
    const texts = eventSearchText(
      makeNode({
        event: "sandbox",
        action: "exec",
        cmd: "ls -la",
        file: null,
        input: null,
        output: null,
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Sandbox: exec");
    expect(texts).toContain("ls -la");
  });

  test("model: includes title with role when present", () => {
    const texts = eventSearchText(
      makeNode({
        event: "model",
        model: "gpt-4",
        role: "assistant",
        output: { choices: [] },
        input: [],
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Model Call (assistant): gpt-4");
  });

  test("model: includes title without role when absent", () => {
    const texts = eventSearchText(
      makeNode({
        event: "model",
        model: "gpt-4",
        role: null,
        output: { choices: [] },
        input: [],
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Model Call: gpt-4");
  });

  test("step: includes formatted title with type prefix", () => {
    const texts = eventSearchText(
      makeNode({
        event: "step",
        name: "generate",
        type: "solver",
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("solver: generate");
  });

  test("step: includes 'Step: name' when no type", () => {
    const texts = eventSearchText(
      makeNode({
        event: "step",
        name: "my_step",
        type: null,
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Step: my_step");
  });

  test("subtask: 'Fork:' for fork type, 'Subtask:' for others", () => {
    const fork = eventSearchText(
      makeNode({
        event: "subtask",
        name: "parallel",
        type: "fork",
        input: null,
        result: null,
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(fork).toContain("Fork: parallel");

    const sub = eventSearchText(
      makeNode({
        event: "subtask",
        name: "check",
        type: "subtask",
        input: null,
        result: null,
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(sub).toContain("Subtask: check");
  });

  test("tool: includes 'Tool:' title", () => {
    const texts = eventSearchText(
      makeNode({
        event: "tool",
        function: "search",
        view: { title: "Web Search" },
        arguments: null,
        result: null,
        error: null,
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Tool: Web Search");
    expect(texts).toContain("search");
  });

  test("error: includes 'Error' title", () => {
    const texts = eventSearchText(
      makeNode({
        event: "error",
        error: { message: "something broke", traceback: null },
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Error");
    expect(texts).toContain("something broke");
  });

  test("logger: includes level as title", () => {
    const texts = eventSearchText(
      makeNode({
        event: "logger",
        message: { level: "WARNING", message: "disk space low", filename: "main.py" },
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("WARNING");
    expect(texts).toContain("disk space low");
  });

  test("info: includes 'Info' title", () => {
    const texts = eventSearchText(
      makeNode({
        event: "info",
        source: "system",
        data: "startup complete",
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Info");
    expect(texts).toContain("system");
  });

  test("sample_init: includes 'Sample' title", () => {
    const texts = eventSearchText(
      makeNode({
        event: "sample_init",
        sample: { target: "expected answer" },
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Sample");
    expect(texts).toContain("expected answer");
  });

  test("input: includes 'Input' title", () => {
    const texts = eventSearchText(
      makeNode({
        event: "input",
        input_ansi: "user typed this",
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Input");
    expect(texts).toContain("user typed this");
  });

  test("span_begin: includes formatted title with type prefix", () => {
    const texts = eventSearchText(
      makeNode({
        event: "span_begin",
        name: "evaluate",
        type: "solver",
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("solver: evaluate");
  });

  test("span_begin: includes 'Step: name' when no type", () => {
    const texts = eventSearchText(
      makeNode({
        event: "span_begin",
        name: "init",
        type: null,
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Step: init");
  });

  test("compaction: includes 'Compaction' title", () => {
    const texts = eventSearchText(
      makeNode({
        event: "compaction",
        source: "inspect",
        tokens_before: 1000,
        tokens_after: 500,
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toContain("Compaction");
    expect(texts).toContain("inspect");
  });

  test("unknown event: returns empty array", () => {
    const texts = eventSearchText(
      makeNode({
        event: "state",
        timestamp: "2024-01-01T00:00:00Z",
      }),
    );
    expect(texts).toEqual([]);
  });
});
