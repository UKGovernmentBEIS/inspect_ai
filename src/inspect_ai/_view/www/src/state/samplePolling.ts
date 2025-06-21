import { Event } from "../app/types";
import {
  AttachmentData,
  ClientAPI,
  EventData,
  SampleData,
  SampleSummary,
} from "../client/api/types";
import { resolveAttachments } from "../utils/attachments";
import { createLogger } from "../utils/logger";
import { createPolling } from "../utils/polling";
import { resolveSample } from "./sampleUtils"; // Import the shared utility
import { StoreState } from "./store";

const log = createLogger("samplePolling");

const kNoId = -1;
const kPollingInterval = 2;
const kPollingMaxRetries = 10;

// Keeps the state for polling (the last ids for events
// and attachments, the attachments and events, and
// a mapping from eventIds to event indexes to enable
// replacing events)
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
  // The polling function that will be returned
  let currentPolling: ReturnType<typeof createPolling> | null = null;

  // handle aborts
  let abortController: AbortController;

  // The inintial polling state
  const pollingState: PollingState = {
    eventId: kNoId,
    attachmentId: kNoId,

    eventMapping: {},
    attachments: {},
    events: [],
  };

  // Function to start polling for a specific log file
  const startPolling = (logFile: string, summary: SampleSummary) => {
    // Create a unique identifier for this polling session
    const pollingId = `${logFile}:${summary.id}-${summary.epoch}`;
    log.debug(`Start Polling ${pollingId}`);

    // If we're already polling this resource, don't restart
    if (currentPolling && currentPolling.name === pollingId) {
      log.debug(`Aleady polling, ignoring start`);
      return;
    }

    // Stop any existing polling first
    if (currentPolling) {
      log.debug(`Resetting existing polling`);
      currentPolling.stop();

      // Clear any current running events
      set((state) => {
        state.sample.runningEvents = [];
      });

      // Reset the current polling state
      resetPollingState(pollingState);
    }
    abortController = new AbortController();

    // Create the polling callback
    log.debug(`Polling sample: ${summary.id}-${summary.epoch}`);
    const pollCallback = async () => {
      const state = get();

      // Get the api
      const api = state.api;
      if (!api) {
        throw new Error("Required API is missing");
      }

      if (!api.get_log_sample_data) {
        throw new Error("Required API get_log_sample_data is undefined.");
      }

      if (abortController.signal.aborted) {
        return false;
      }

      // Fetch sample data
      state.sampleActions.setSampleStatus("streaming");
      const eventId = pollingState.eventId;
      const attachmentId = pollingState.attachmentId;
      const sampleDataResponse = await api.get_log_sample_data(
        logFile,
        summary.id,
        summary.epoch,
        eventId,
        attachmentId,
      );

      if (abortController.signal.aborted) {
        return false;
      }

      if (sampleDataResponse?.status === "NotFound") {
        // A 404 from the server means that this sample
        // has been flushed to the main eval file, no events
        // are available and we should retrieve the data from the
        // sample file itself.

        // Stop polling since we now have the complete sample
        stopPolling();

        // Also fetch a fresh sample and clear the runnning Events
        // (if there were ever running events)
        if (state.sample.runningEvents.length > 0) {
          try {
            log.debug(
              `LOADING COMPLETED SAMPLE AFTER FLUSH: ${summary.id}-${summary.epoch}`,
            );
            const sample = await api.get_log_sample(
              logFile,
              summary.id,
              summary.epoch,
            );

            if (sample) {
              const migratedSample = resolveSample(sample);

              // Update the store with the completed sample
              set((state) => {
                state.sampleActions.setSelectedSample(migratedSample);
                state.sampleActions.setSampleStatus("ok");
                state.sample.runningEvents = [];
              });
            } else {
              set((state) => {
                state.sampleActions.setSampleStatus("error");
                state.sample.sampleError = new Error(
                  "Unable to load sample - an unknown error occurred",
                );
                state.sample.runningEvents = [];
              });
            }
          } catch (e) {
            set((state) => {
              state.sample.sampleError = e as Error;
              state.sampleActions.setSampleStatus("error");
              state.sample.runningEvents = [];
            });
          }
        } else {
          state.sampleActions.setSampleStatus("ok");
          state.sample.runningEvents = [];
        }
        return false;
      }

      if (
        sampleDataResponse?.status === "OK" &&
        sampleDataResponse.sampleData
      ) {
        if (abortController.signal.aborted) {
          return false;
        }

        if (sampleDataResponse.sampleData) {
          // Process attachments
          processAttachments(sampleDataResponse.sampleData, pollingState);

          // Process events
          const processedEvents = processEvents(
            sampleDataResponse.sampleData,
            pollingState,
            api,
            logFile,
          );

          // update max attachment id
          if (sampleDataResponse.sampleData.attachments.length > 0) {
            const maxAttachment = findMaxId(
              sampleDataResponse.sampleData.attachments,
              pollingState.attachmentId,
            );
            log.debug(`New max attachment ${maxAttachment}`);
            pollingState.attachmentId = maxAttachment;
          }

          // update max event id
          if (sampleDataResponse.sampleData.events.length > 0) {
            const maxEvent = findMaxId(
              sampleDataResponse.sampleData.events,
              pollingState.eventId,
            );
            log.debug(`New max event ${maxEvent}`);
            pollingState.eventId = maxEvent;
          }

          // Update the running events (ensure identity of runningEvents fails equality)
          if (processedEvents) {
            set((state) => {
              state.sample.runningEvents = [...pollingState.events];
            });
          }
        }
      }

      // Continue polling
      return true;
    };

    // Create the polling instance
    const polling = createPolling(pollingId, pollCallback, {
      maxRetries: kPollingMaxRetries,
      interval: kPollingInterval,
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
    log.debug(`Cleanup`);
    if (abortController) {
      abortController.abort();
    }
    stopPolling();
  };

  return {
    startPolling,
    stopPolling,
    cleanup,
  };
}

const resetPollingState = (state: PollingState) => {
  state.eventId = kNoId;
  state.attachmentId = kNoId;
  state.eventMapping = {};
  state.attachments = {};
  state.events = [];
};

function processAttachments(
  sampleData: SampleData,
  pollingState: PollingState,
) {
  log.debug(`Processing ${sampleData.attachments.length} attachments`);
  Object.values(sampleData.attachments).forEach((v) => {
    pollingState.attachments[v.hash] = v.content;
  });
}

function processEvents(
  sampleData: SampleData,
  pollingState: PollingState,
  api: ClientAPI,
  log_file: string,
) {
  // Go through each event and resolve it, either appending or replacing
  log.debug(`Processing ${sampleData.events.length} events`);
  if (sampleData.events.length === 0) {
    return false;
  }

  for (const eventData of sampleData.events) {
    // Identify if this event id already has an event in the event list
    const existingIndex = pollingState.eventMapping[eventData.event_id];

    // Resolve attachments within this event
    const resolvedEvent = resolveAttachments<Event>(
      eventData.event,
      pollingState.attachments,
      (attachmentId: string) => {
        const snapshot = {
          eventId: eventData.event_id,
          attachmentId,
          available_attachments: Object.keys(pollingState.attachments),
        };

        if (api.log_message) {
          api.log_message(
            log_file,
            `Unable to resolve attachment ${attachmentId}\n` +
              JSON.stringify(snapshot),
          );
        }
        console.warn(`Unable to resolve attachment ${attachmentId}`, snapshot);
      },
    );

    if (existingIndex) {
      // There is an existing event in the stream, replace it
      log.debug(`Replace event ${existingIndex}`);
      pollingState.events[existingIndex] = resolvedEvent;
    } else {
      // This is a new event, add to the event list and note
      // its position
      log.debug(`New event ${pollingState.events.length}`);

      const currentIndex = pollingState.events.length;
      pollingState.eventMapping[eventData.event_id] = currentIndex;
      pollingState.events.push(resolvedEvent);
    }
  }
  return true;
}

const findMaxId = (
  items: EventData[] | AttachmentData[],
  currentMax: number,
) => {
  if (items.length > 0) {
    const newMax = Math.max(...items.map((i) => i.id), currentMax);
    return newMax;
  }
  return currentMax;
};
