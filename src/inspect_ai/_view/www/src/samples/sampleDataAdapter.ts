import { EventData, SampleData } from "../api/types";
import { Events } from "../types/log";
import { resolveAttachments } from "../utils/attachments";

export const sampleDataAdapter = () => {
  const attachments: Record<string, string> = {};
  const events: Record<string, EventData> = {};

  return {
    addData: (data: SampleData) => {
      data.attachments.forEach((a) => {
        attachments[a.hash] = a.content;
      });

      data.events.forEach((e) => {
        events[e.event_id] = e;
      });
    },
    resolvedEvents: (): Events => {
      const eventDatas = Object.values(events);
      const resolvedEvents = eventDatas.map((ed: EventData) => {
        return ed.event;
      });
      return resolveAttachments(resolvedEvents, attachments);
    },
  };
};
