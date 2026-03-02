import { resolveSample } from "../../state/sampleUtils";

// Minimal factories – only fields the resolution code dispatches on

const msg = (id: string, role: string, content: string) => ({
  id,
  role,
  content,
  source: "input",
  metadata: {},
});

const modelEvent = (input: unknown[], input_refs?: unknown[] | null) => ({
  event: "model",
  input,
  input_refs: input_refs ?? null,
});

const makeSample = (overrides: Record<string, unknown> = {}) => ({
  input: "test input",
  messages: [],
  events: [],
  attachments: {},
  ...overrides,
});

// Factory for model events with call.request data
const modelEventWithCall = (
  request: Record<string, unknown>,
  call_refs?: unknown[] | null,
  call_key?: string | null,
) => ({
  event: "model",
  input: [],
  input_refs: null,
  call: {
    request,
    response: null,
    call_refs: call_refs ?? null,
    call_key: call_key ?? null,
  },
});

describe("resolveSample", () => {
  test("resolves input_refs from message_pool into ModelEvent.input", () => {
    const sys = msg("msg-1", "system", "You are helpful.");
    const usr = msg("msg-2", "user", "What is 2+2?");
    const pool = [sys, usr];

    const sample = makeSample({
      message_pool: pool,
      events: [modelEvent([], [[0, 2]])],
    });

    const resolved = resolveSample(sample);
    expect((resolved.events[0] as any).input).toEqual([sys, usr]);
    expect((resolved.events[0] as any).input_refs).toBeNull();
    expect((resolved as any).message_pool).toEqual([]);
  });

  test("resolves call_refs from call_pool into call.request[key]", () => {
    const m1 = { role: "user", content: "Hello" };
    const m2 = { role: "assistant", content: "Hi" };
    const pool = [m1, m2];

    const sample = makeSample({
      call_pool: pool,
      events: [modelEventWithCall({ model: "test" }, [[0, 2]], "messages")],
    });

    const resolved = resolveSample(sample);
    const call = (resolved.events[0] as any).call;
    expect(call.request.messages).toEqual([m1, m2]);
    expect(call.call_refs).toBeNull();
    expect((resolved as any).call_pool).toEqual([]);
  });

  test("uses call_key to restore under a custom key", () => {
    const m1 = { role: "user", content: "Hello via contents" };
    const pool = [m1];

    const sample = makeSample({
      call_pool: pool,
      events: [modelEventWithCall({ model: "test" }, [[0, 1]], "contents")],
    });

    const resolved = resolveSample(sample);
    const call = (resolved.events[0] as any).call;
    expect(call.request.contents).toEqual([m1]);
    expect(call.request.messages).toBeUndefined();
  });

  test("resolves pool before attachments so attachment refs in pool messages work", () => {
    const msgWithAttachment = msg("msg-1", "user", "attachment://abc123");
    const pool = [msgWithAttachment];
    const attachments = { abc123: "resolved content" };

    const sample = makeSample({
      message_pool: pool,
      attachments,
      events: [modelEvent([], [[0, 1]])],
    });

    const resolved = resolveSample(sample);
    expect((resolved.events[0] as any).input[0].content).toBe(
      "resolved content",
    );
  });

  test("resolves non-contiguous range refs", () => {
    const msgs = [
      msg("0", "system", "Sys"),
      msg("1", "user", "Q1"),
      msg("2", "assistant", "A1"),
      msg("3", "user", "Q2"),
      msg("4", "assistant", "A2"),
    ];

    const sample = makeSample({
      message_pool: msgs,
      events: [
        modelEvent(
          [],
          [
            [0, 1],
            [3, 5],
          ],
        ),
      ],
    });

    const resolved = resolveSample(sample);
    expect((resolved.events[0] as any).input).toEqual([
      msgs[0],
      msgs[3],
      msgs[4],
    ]);
  });
});
