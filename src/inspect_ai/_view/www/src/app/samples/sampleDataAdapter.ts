import { Events } from "../../@types/log";
import { EventData, SampleData } from "../../client/api/types";
import { resolveAttachments } from "../../utils/attachments";

export const sampleDataAdapter = () => {
  const attachments: Record<string, string> = {};
  const events: Record<string, EventData> = {};

  return {
    addData: (data: SampleData) => {
      data.attachments.forEach((a) => {
        if (attachments[a.hash] === undefined) {
          attachments[a.hash] = a.content;
        }
      });

      data.events.forEach((e) => {
        if (events[e.event_id] === undefined) {
          events[e.event_id] = e;
        }
      });
    },
    resolvedEvents: (): Events => {
      const eventDatas = Object.values(events);

      const resolvedEvents = eventDatas.map((ed: EventData) => {
        return ed.event;
      }) as Events;

      return resolveAttachments<Events>(resolvedEvents, attachments);
    },
  };
};
