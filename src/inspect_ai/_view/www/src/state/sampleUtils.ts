import { EvalSample } from "../@types/log";
import { resolveAttachments } from "../utils/attachments";
import { expandEvents } from "../utils/expandEvents";

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

  // Resolve pool refs BEFORE attachments (pool messages may
  // contain attachment:// refs that need resolving in the next step)
  sample.events = expandEvents(sample.events, sample.events_data ?? null);
  sample.events_data = null;

  sample.attachments = sample.attachments || {};
  sample.input = resolveAttachments(sample.input, sample.attachments);
  sample.messages = resolveAttachments(sample.messages, sample.attachments);
  sample.events = resolveAttachments(sample.events, sample.attachments);
  sample.attachments = {};
  return sample;
};
