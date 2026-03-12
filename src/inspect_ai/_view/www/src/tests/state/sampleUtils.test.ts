import { resolveSample } from "../../state/sampleUtils";

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

const makeSample = (overrides: Record<string, unknown> = {}) => ({
  input: "test input",
  messages: [],
  events: [],
  attachments: {},
  message_pool: [],
  call_pool: [],
  ...overrides,
});

const sys = msg("msg-1", "system", "You are helpful.");
const usr = msg("msg-2", "user", "What is 2+2?");
const msgs = [
  msg("0", "system", "Sys"),
  msg("1", "user", "Q1"),
  msg("2", "assistant", "A1"),
  msg("3", "user", "Q2"),
  msg("4", "assistant", "A2"),
];

describe("resolveSample", () => {
  it.each([
    {
      name: "resolves input_refs from message_pool",
      sample: makeSample({
        message_pool: [sys, usr],
        events: [modelEvent([], [[0, 2]])],
      }),
      check: (resolved: any) => {
        expect(resolved.events[0].input).toEqual([sys, usr]);
        expect(resolved.events[0].input_refs).toBeNull();
        expect(resolved.message_pool).toEqual([]);
      },
    },
    {
      name: "resolves call_refs from call_pool",
      sample: makeSample({
        call_pool: [
          { role: "user", content: "Hello" },
          { role: "assistant", content: "Hi" },
        ],
        events: [modelEventWithCall({ model: "test" }, [[0, 2]], "messages")],
      }),
      check: (resolved: any) => {
        expect(resolved.events[0].call.request.messages).toEqual([
          { role: "user", content: "Hello" },
          { role: "assistant", content: "Hi" },
        ]);
        expect(resolved.events[0].call.call_refs).toBeNull();
        expect(resolved.call_pool).toEqual([]);
      },
    },
    {
      name: "uses call_key to restore under a custom key",
      sample: makeSample({
        call_pool: [{ role: "user", content: "Hello via contents" }],
        events: [modelEventWithCall({ model: "test" }, [[0, 1]], "contents")],
      }),
      check: (resolved: any) => {
        expect(resolved.events[0].call.request.contents).toEqual([
          { role: "user", content: "Hello via contents" },
        ]);
        expect(resolved.events[0].call.request.messages).toBeUndefined();
      },
    },
    {
      name: "resolves pool before attachments",
      sample: makeSample({
        message_pool: [msg("msg-1", "user", "attachment://abc123")],
        attachments: { abc123: "resolved content" },
        events: [modelEvent([], [[0, 1]])],
      }),
      check: (resolved: any) => {
        expect(resolved.events[0].input[0].content).toBe("resolved content");
      },
    },
    {
      name: "resolves non-contiguous range refs",
      sample: makeSample({
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
      }),
      check: (resolved: any) => {
        expect(resolved.events[0].input).toEqual([msgs[0], msgs[3], msgs[4]]);
      },
    },
  ])("$name", ({ sample, check }) => {
    check(resolveSample(sample));
  });
});
