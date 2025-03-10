import { SampleSummary } from "../api/types";
import { Event } from "../types";
import { resolveAttachments } from "../utils/attachments";
import { createLogger } from "../utils/logger";
import { createPolling } from "../utils/polling";
import { StoreState } from "./store";

// The logger
const log = createLogger("samplePolling");

interface PollingState {
  eventId: number;
  attachmentId: number;

  attachments: Record<string, string>;

  eventMapping: Record<string, number>;
  events: Event[];
}

export function createSamplePolling(
  get: () => StoreState,
  set: (fn: (state: StoreState) => void) => void,
) {
  // Tracks the currently polling instance
  let currentPolling: ReturnType<typeof createPolling> | null = null;

  // Track whether or not we're active
  let isActive = true;

  const pollingState: PollingState = {
    eventId: -1,
    attachmentId: -1,

    eventMapping: {},
    attachments: {},
    events: [],
  };

  // Function to start polling for a specific log file
  const startPolling = (logFile: string, summary: SampleSummary) => {
    log.debug("START POLLING");
    // Create a unique identifier for this polling session
    const pollingId = `${logFile}:${summary.id}-${summary.epoch}`;

    // If we're already polling this exact resource, don't restart
    if (currentPolling && currentPolling.name === pollingId) {
      return; // Already polling this resource, no need to restart
    }

    // Stop any existing polling first
    if (currentPolling) {
      currentPolling.stop();
      set((state) => {
        state.sample.runningEvents = [];
      });
      pollingState.eventId = -1;
      pollingState.attachmentId = -1;
      pollingState.eventMapping = {};
      pollingState.attachments = {};
      pollingState.events = [];
    }
    isActive = true;

    log.debug(`POLLING RUNNING SAMPLE: ${summary.id}-${summary.epoch}`);

    // Create the polling callback
    const pollCallback = async () => {
      if (!isActive) {
        log.debug(
          `Component unmounted, stopping poll for: ${summary.id}-${summary.epoch}`,
        );
        return false; // Stop polling
      }

      const state = get();
      const api = state.api;
      if (!api) {
        throw new Error("Required API is missing");
      }

      if (!api.get_log_sample_data) {
        return false; // Stop polling
      }

      log.debug(`GET RUNNING SAMPLE: ${summary.id}-${summary.epoch}`);

      if (!isActive) {
        return false; // Stop polling
      }

      const eventId = pollingState.eventId;
      const attachmentId = pollingState.attachmentId;
      log.debug(`> event: ${eventId}, attachments: ${attachmentId}`);
      const sampleDataResponse = await api.get_log_sample_data(
        logFile,
        summary.id,
        summary.epoch,
        eventId,
        attachmentId,
      );

      if (!isActive) {
        return false; // Stop polling
      }

      if (sampleDataResponse?.status === "NotFound") {
        // Stop polling
        return false;
      }

      if (
        sampleDataResponse?.status === "OK" &&
        sampleDataResponse.sampleData
      ) {
        if (!isActive) {
          return false; // Stop polling
        }

        // Push the attachments
        log.debug(
          `PROCESS ${sampleDataResponse.sampleData.attachments.length} ATTACHMENTS`,
        );
        Object.values(sampleDataResponse.sampleData.attachments).forEach(
          (v) => {
            pollingState.attachments[v.hash] = v.content;
          },
        );

        // Go through each event and resolve it, either appending or replacing
        log.debug(
          `PROCESS ${sampleDataResponse.sampleData.events.length} EVENTS`,
        );
        for (const eventData of sampleDataResponse.sampleData.events) {
          const existingIndex = pollingState.eventMapping[eventData.event_id];
          const resolvedEvent = resolveAttachments<Event>(
            eventData.event,
            pollingState.attachments,
          );
          if (existingIndex) {
            pollingState.events[existingIndex] = resolvedEvent;
          } else {
            // Note where this event is going in the array
            const currentIndex = pollingState.events.length;
            pollingState.eventMapping[eventData.event_id] = currentIndex;

            // Place the event on the array
            pollingState.events.push(resolvedEvent);
          }
        }

        // update max attachment id
        if (sampleDataResponse.sampleData.attachments.length > 0) {
          const maxAttachment =
            sampleDataResponse.sampleData.attachments.reduce(
              (max, attachment) => Math.max(max, attachment.id),
              pollingState.attachmentId,
            );
          log.debug(`UPDATE MAX ATTACHMENT ID TO ${maxAttachment}`);
          pollingState.attachmentId = maxAttachment;
        }

        // update max event id
        if (sampleDataResponse.sampleData.events.length > 0) {
          const maxEvent = sampleDataResponse.sampleData.events.reduce(
            (max, event) => Math.max(max, event.id),
            pollingState.eventId,
          );
          log.debug(`UPDATE MAX EVENT ID TO ${maxEvent}`);
          pollingState.eventId = maxEvent;
        }

        set((state) => {
          state.sample.runningEvents = [...pollingState.events];
        });
      }

      // Continue polling
      return true;
    };

    // Create the polling instance
    const name = `${logFile}:${summary.id}-${summary.epoch}`;
    const polling = createPolling(name, pollCallback, {
      maxRetries: 10,
      interval: 2,
    });

    // Store the polling instance and start it
    currentPolling = polling;
    polling.start();
  };

  // Stop polling
  const stopPolling = () => {
    if (currentPolling) {
      currentPolling.stop();
      currentPolling = null;
    }
  };

  const cleanup = () => {
    log.debug(`CLEANUP`);
    isActive = false;
    stopPolling();
  };

  return {
    startPolling,
    stopPolling,
    cleanup,
  };
}
