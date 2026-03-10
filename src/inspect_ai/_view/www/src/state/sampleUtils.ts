import { EvalSample, ModelEvent } from "../@types/log";
import { Event } from "../app/types";
import { resolveAttachments } from "../utils/attachments";

export function isModelEvent(event: Event): event is ModelEvent {
  return "event" in event && (event as ModelEvent).event === "model";
}

/**
 * Resolve delta-encoded ModelEvent inputs back to full inputs.
 * Walks forward through events, accumulating full input from deltas.
 */
export function resolveInputDeltas(events: Event[]): void {
  let prevFullInput: unknown[] = [];
  for (const event of events) {
    if (!isModelEvent(event)) continue;
    if (event.input_delta) {
      event.input = [...prevFullInput, ...event.input] as typeof event.input;
      event.input_delta = false;
      prevFullInput = event.input as unknown[];
    } else {
      prevFullInput = event.input as unknown[];
    }
  }
}

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
  sample.attachments = sample.attachments || {};
  sample.input = resolveAttachments(sample.input, sample.attachments);
  sample.messages = resolveAttachments(sample.messages, sample.attachments);
  sample.events = resolveAttachments(sample.events, sample.attachments);
  sample.attachments = {};
  resolveInputDeltas(sample.events);
  return sample;
};
