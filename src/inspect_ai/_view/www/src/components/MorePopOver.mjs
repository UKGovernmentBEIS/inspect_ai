import { Popover } from "bootstrap";
import { html } from "htm/preact";
import { useEffect, useRef } from "preact/hooks";

import { ApplicationIcons } from "../appearance/Icons.mjs";
import { ApplicationStyles } from "../appearance/Styles.mjs";

export const MorePopOver = ({ title, customClass, children }) => {
  const popoverRef = useRef();
  const contentRef = useRef();

  // Initialize the popover
  useEffect(() => {
    const contentEl = contentRef.current;
    const popOverContent = document.createElement("div");
    contentEl.childNodes.forEach((child) =>
      popOverContent.appendChild(child.cloneNode(true)),
    );
    new Popover(popoverRef.current, {
      content: popOverContent,
      title,
      html: true,
      customClass: customClass,
      trigger: "focus",
    });
  }, [popoverRef, contentRef]);

  const popoverElements = [];

  // The popover display button
  popoverElements.push(html`
    <a
      tabindex="0"
      ref=${popoverRef}
      class="btn"
      role="button"
      data-bs-toggle="popover"
      data-bs-trigger="focus"
      style=${ApplicationStyles.moreButton}
      ><i class="${ApplicationIcons.more}"></i
    ></a>
  `);

  // A container to hold the popover contents
  popoverElements.push(
    html` <div style="display: none;" ref=${contentRef}>${children}</div>`,
  );

  return popoverElements;
};
