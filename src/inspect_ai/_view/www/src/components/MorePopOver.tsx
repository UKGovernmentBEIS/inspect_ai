import { Popover } from "bootstrap";
import { FC, ReactNode, useEffect, useRef } from "react";
import "./MorePopover.css";

interface MorePopoverProps {
  title: string;
  customClass?: string;
  children: ReactNode;
}

export const MorePopover: FC<MorePopoverProps> = ({
  title,
  customClass,
  children,
}) => {
  const popoverRef = useRef<HTMLAnchorElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!popoverRef.current || !contentRef.current) return;

    const contentEl = contentRef.current;
    const popOverContent = document.createElement("div");

    // Clone children into popover content
    Array.from(contentEl.childNodes).forEach((child) =>
      popOverContent.appendChild(child.cloneNode(true)),
    );

    // Capture the current ref value for cleanup
    const popoverElement = popoverRef.current;

    // Initialize Bootstrap popover
    new Popover(popoverElement, {
      content: popOverContent,
      title,
      html: true,
      customClass,
      trigger: "focus",
    });

    // Cleanup on unmount
    return () => {
      const popoverInstance = Popover.getInstance(popoverElement);
      if (popoverInstance) {
        popoverInstance.dispose();
      }
    };
  }, [title, customClass]);

  return (
    <>
      <a
        ref={popoverRef}
        tabIndex={0}
        className="more-popover-button btn"
        role="button"
        data-bs-toggle="popover"
        data-bs-trigger="focus"
      >
        <i className="more-icon" />
      </a>
      <div ref={contentRef} className="more-popover-content">
        {children}
      </div>
    </>
  );
};
