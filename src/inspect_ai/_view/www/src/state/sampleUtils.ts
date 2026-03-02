import { EvalSample, Events, JsonValue } from "../@types/log";
import { resolveAttachments } from "../utils/attachments";

type SampleEvent = Events[number];
type ChatMessage = EvalSample["messages"][number];

/**
 * Expand range-encoded refs against a pool.
 * Each ref element is [start, end) (half-open range).
 */
const expandRefs = <T>(refs: number[][], pool: T[]): T[] => {
  const result: T[] = [];
  for (const item of refs) {
    for (let i = item[0]; i < item[1]; i++) {
      result.push(pool[i]);
    }
  }
  return result;
};

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

    let resolved: SampleEvent = event;

    if (Array.isArray(event.input_refs)) {
      resolved = {
        ...resolved,
        input: expandRefs<ChatMessage>(event.input_refs, msgPool),
        input_refs: null,
      };
    }

    if (resolved.call) {
      const refs = resolved.call.call_refs;
      if (Array.isArray(refs)) {
        const msgKey = resolved.call.call_key || "messages";
        const request = { ...resolved.call.request };
        request[msgKey] = expandRefs<JsonValue>(refs, callPool);
        resolved = {
          ...resolved,
          call: {
            ...resolved.call,
            request,
            call_refs: null,
            call_key: null,
          },
        };
      }
    }

    return resolved;
  });
};

/**
 * Resolve message_pool and call_pool references in a sample's events.
 * Returns the sample unchanged if neither pool is present.
 */
const resolvePools = (sample: EvalSample): EvalSample => {
  const msgPool = sample.message_pool;
  const callPool = sample.call_pool;
  if (!msgPool?.length && !callPool?.length) return sample;

  return {
    ...sample,
    events: resolveEventRefs(sample.events, msgPool ?? [], callPool ?? []),
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
