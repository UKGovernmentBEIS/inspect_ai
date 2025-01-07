// @ts-check
import { html } from "htm/preact";
import { TranscriptVirtualList } from "./transcript/TranscriptView.mjs";

/**
 * Renders the SampleTranscript component.
 *
 * @param {Object} props - The parameters for the component.
 * @param {string} props.id - The id of this component
 * @param {import("../types/log").Events} props.evalEvents - The transcript to display.
 * @param {import("htm/preact").MutableRef<HTMLElement>} props.scrollRef - The scrollable parent element
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
export const SampleTranscript = ({ id, evalEvents, scrollRef }) => {
  return html`<${TranscriptVirtualList}
    id=${id}
    events=${evalEvents}
    scrollRef=${scrollRef}
  />`;
};
