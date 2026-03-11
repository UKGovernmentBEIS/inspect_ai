import { EvalSample, Events, JsonValue } from "../@types/log";
import { resolveAttachments } from "../utils/attachments";

type SampleEvent = Events[number];
type ChatMessage = EvalSample["messages"][number];

/**
 * Expand range-encoded refs against a pool.
 * Each ref element is [start, end_exclusive) — a half-open range.
 */
export const expandRefs = <T>(refs: [number, number][], pool: T[]): T[] =>
  refs.flatMap(([start, end_exclusive]) => pool.slice(start, end_exclusive));

/**
 * Resolve input_refs and call_refs in a flat event list against their pools.
 */
const resolveEventRefs = (
  events: SampleEvent[],
  msgPool: ChatMessage[],
  callPool: JsonValue[],
): SampleEvent[] => {
  return events.map((event): SampleEvent => {
    if (event.event !== "model") return event;

    const resolved: SampleEvent = Array.isArray(event.input_refs)
      ? {
          ...event,
          input: expandRefs<ChatMessage>(
            event.input_refs as [number, number][],
            msgPool,
          ),
          input_refs: null,
        }
      : event;

    if (!resolved.call || !Array.isArray(resolved.call.call_refs))
      return resolved;

    return {
      ...resolved,
      call: {
        ...resolved.call,
        request: {
          ...resolved.call.request,
          [resolved.call.call_key || "messages"]: expandRefs<JsonValue>(
            resolved.call.call_refs as [number, number][],
            callPool,
          ),
        },
        call_refs: null,
        call_key: null,
      },
    };
  });
};

/**
 * Resolve message_pool and call_pool references in a sample's events.
 * Returns the sample unchanged if neither pool is present.
 */
const resolvePools = (sample: EvalSample): EvalSample => {
  const { message_pool, call_pool } = sample;
  if (!message_pool.length && !call_pool.length) return sample;

  return {
    ...sample,
    events: resolveEventRefs(sample.events, message_pool, call_pool),
    message_pool: [],
    call_pool: [],
  };
};

/**
 * Migrates and resolves attachments for a sample
 */
export const resolveSample = (sample: any): EvalSample => {
  sample = { ...sample };

  // Migrates old versions of samples to the new structure
  if (sample.transcript) {
    sample.events = sample.transcript.events;
    sample.attachments = sample.transcript.content;
  }

  // Resolve message pool refs BEFORE attachments (pool messages may
  // contain attachment:// refs that need resolving in the next step)
  sample = resolvePools(sample);

  sample.attachments = sample.attachments || {};
  sample.input = resolveAttachments(sample.input, sample.attachments);
  sample.messages = resolveAttachments(sample.messages, sample.attachments);
  sample.events = resolveAttachments(sample.events, sample.attachments);
  sample.attachments = {};
  return sample;
};
