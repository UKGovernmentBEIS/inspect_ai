import { RefObject } from "react";
import { Events } from "../../types/log";
import { TranscriptVirtualList } from "./TranscriptView";

interface SampleTranscriptProps {
  id: string;
  evalEvents: Events;
  scrollRef: RefObject<HTMLDivElement | null>;
}

/**
 * Renders the SampleTranscript component.=
 */
export const SampleTranscript: React.FC<SampleTranscriptProps> = ({
  id,
  evalEvents,
  scrollRef,
}) => {
  return (
    <TranscriptVirtualList id={id} events={evalEvents} scrollRef={scrollRef} />
  );
};
