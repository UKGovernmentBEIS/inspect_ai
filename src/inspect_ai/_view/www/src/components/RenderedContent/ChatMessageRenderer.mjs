import { html } from "htm/preact";

import { Buckets } from "./RenderedContent.mjs";
import { ChatView } from "../ChatView.mjs";

/**
 * @type {import("./RenderedContent.mjs").ContentRenderer}
 *
 * Renders chat messages as a ChatView component.
 */
export const ChatMessageRenderer = {
  bucket: Buckets.first,
  canRender: (entry) => {
    const val = entry.value;
    return (
      Array.isArray(val) &&
      val.length > 0 &&
      val[0]?.role !== undefined &&
      val[0]?.content !== undefined
    );
  },
  render: (id, entry) => {
    return {
      rendered: html`<${ChatView} id=${id} messages=${entry.value} />`,
    };
  },
};
