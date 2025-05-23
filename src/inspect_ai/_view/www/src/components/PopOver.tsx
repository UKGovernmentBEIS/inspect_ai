import { Placement } from "@popperjs/core";
import clsx from "clsx";
import React, {
  CSSProperties,
  ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { usePopper } from "react-popper";

interface PopOverProps {
  id: string;
  isOpen: boolean;
  positionEl: HTMLElement | null;
  placement?: Placement;
  showArrow?: boolean;
  offset?: [number, number];
  usePortal?: boolean;
  hoverDelay?: number;

  className?: string | string[];
  arrowClassName?: string | string[];

  children: ReactNode;
}

/**
 * A controlled Popper component for displaying content relative to a reference element
 */
export const PopOver: React.FC<PopOverProps> = ({
  id,
  isOpen,
  positionEl,
  children,
  placement = "bottom",
  showArrow = true,
  offset = [0, 8],
  className = "",
  arrowClassName = "",
  usePortal = true,
  hoverDelay = 250,
}) => {
  const popperRef = useRef<HTMLDivElement | null>(null);
  const arrowRef = useRef<HTMLDivElement | null>(null);
  const [portalContainer, setPortalContainer] = useState<HTMLElement | null>(
    null,
  );

  // For delayed hover functionality
  const [shouldShowPopover, setShouldShowPopover] = useState(false);
  const hoverTimerRef = useRef<number | null>(null);
  const isMouseMovingRef = useRef(false);

  // Setup hover timer and mouse movement detection
  useEffect(() => {
    if (!isOpen || hoverDelay <= 0) {
      setShouldShowPopover(isOpen);
      return;
    }

    const handleMouseMove = () => {
      isMouseMovingRef.current = true;

      // Clear any existing timer when mouse moves
      if (hoverTimerRef.current !== null) {
        window.clearTimeout(hoverTimerRef.current);
      }

      // Start a new timer to check if mouse has stopped moving
      hoverTimerRef.current = window.setTimeout(() => {
        if (isOpen) {
          isMouseMovingRef.current = false;
          setShouldShowPopover(true);
        }
      }, hoverDelay);
    };

    const handleMouseLeave = () => {
      if (hoverTimerRef.current !== null) {
        window.clearTimeout(hoverTimerRef.current);
      }
      isMouseMovingRef.current = false;
      setShouldShowPopover(false);
    };

    const handleMouseDown = () => {
      // Cancel popover on any mouse down
      if (hoverTimerRef.current !== null) {
        window.clearTimeout(hoverTimerRef.current);
      }
      setShouldShowPopover(false);
    };

    // Add event listeners to the positionEl (the trigger element)
    if (positionEl && isOpen) {
      positionEl.addEventListener("mousemove", handleMouseMove);
      positionEl.addEventListener("mouseleave", handleMouseLeave);

      // Add document-wide mousedown listener to dismiss on interaction
      document.addEventListener("mousedown", handleMouseDown);
      document.addEventListener("click", handleMouseDown);

      // Initial mouse move to start the timer
      handleMouseMove();
    } else {
      setShouldShowPopover(false);
    }

    return () => {
      if (positionEl) {
        positionEl.removeEventListener("mousemove", handleMouseMove);
        positionEl.removeEventListener("mouseleave", handleMouseLeave);
      }

      // Clean up the document mousedown listener
      document.removeEventListener("mousedown", handleMouseDown);

      document.removeEventListener("click", handleMouseDown);

      if (hoverTimerRef.current !== null) {
        window.clearTimeout(hoverTimerRef.current);
      }
    };
  }, [isOpen, positionEl, hoverDelay]);

  // Effect to create portal container when needed
  useEffect(() => {
    // Only create portal when the popover is open
    if (usePortal && isOpen && shouldShowPopover) {
      let container = document.getElementById(id);

      if (!container) {
        container = document.createElement("div");
        container.id = id;
        container.style.position = "absolute";
        container.style.top = "0";
        container.style.left = "0";
        container.style.zIndex = "9999";
        container.style.width = "0";
        container.style.height = "0";
        container.style.overflow = "visible";

        document.body.appendChild(container);
      }

      setPortalContainer(container);

      return () => {
        // Clean up only when unmounting or when the popover closes
        if (document.body.contains(container)) {
          document.body.removeChild(container);
          setPortalContainer(null);
        }
      };
    }

    return undefined;
  }, [usePortal, isOpen, shouldShowPopover, id]);

  // Configure modifiers for popper
  const modifiers = [
    { name: "offset", options: { offset } },
    { name: "preventOverflow", options: { padding: 8 } },
    {
      name: "arrow",
      enabled: showArrow,
      options: {
        element: arrowRef.current,
        padding: 5, // This keeps the arrow from getting too close to the corner
      },
    },
    {
      name: "computeStyles",
      options: {
        gpuAcceleration: false,
        adaptive: true,
      },
    },
    // Ensure popper is positioned correctly with respect to its reference element
    {
      name: "flip",
      options: {
        fallbackPlacements: ["top", "right", "bottom", "left"],
      },
    },
  ];

  // Use popper hook with modifiers
  const { styles, attributes, state, update } = usePopper(
    positionEl,
    popperRef.current,
    {
      placement,
      strategy: "fixed",
      modifiers,
    },
  );

  // Force update when needed refs change
  useEffect(() => {
    if (update && isOpen && shouldShowPopover) {
      // Need to delay the update slightly to ensure refs are properly set
      const timer = setTimeout(() => {
        update();
      }, 10);
      return () => clearTimeout(timer);
    }
  }, [update, isOpen, shouldShowPopover, showArrow, arrowRef.current]);

  // Define arrow data-* attribute based on placement
  const getArrowDataPlacement = () => {
    if (!state || !state.placement) return placement;
    return state.placement;
  };

  // Get the actual placement from Popper state
  const actualPlacement = state?.placement || placement;

  // For a CSS triangle, we use the border trick
  // A CSS triangle doesn't need separate border styling like a rotated square would

  // Popper container styles
  const defaultPopperStyles: CSSProperties = {
    backgroundColor: "var(--bs-body-bg)",
    padding: "12px",
    borderRadius: "4px",
    boxShadow: "0 2px 10px rgba(0,0,0,0.1)",
    border: "1px solid #eee",
    zIndex: 1200,
    position: "relative",
    // Apply opacity transition to smooth the appearance
    opacity: state?.placement ? 1 : 0,
    transition: "opacity 0.1s",
  };

  // Early return if not open or should not show due to hover delay
  if (!isOpen || (hoverDelay > 0 && !shouldShowPopover)) {
    return null;
  }

  // For position-aware rendering
  const positionedStyle =
    state && state.styles && state.styles.popper
      ? {
          ...styles.popper,
          opacity: 1,
        }
      : {
          ...styles.popper,
          opacity: 0,
          // Position offscreen initially to prevent flicker
          position: "fixed" as const,
          top: "-9999px",
          left: "-9999px",
        };

  // Create the popper content with position-aware styles
  const popperContent = (
    <div
      ref={popperRef}
      style={{ ...defaultPopperStyles, ...positionedStyle }}
      className={clsx(className)}
      {...attributes.popper}
    >
      {children}

      {showArrow && (
        <>
          {/* Invisible div for Popper.js to use as reference */}
          <div
            ref={arrowRef}
            style={{ position: "absolute", visibility: "hidden" }}
            data-placement={getArrowDataPlacement()}
          />

          {/* Arrow container - positioned by Popper */}
          <div
            className={clsx("popper-arrow-container", arrowClassName)}
            style={{
              ...styles.arrow,
              position: "absolute",
              zIndex: 1,
              // Size and positioning based on placement - smaller arrow
              ...(actualPlacement.startsWith("top") && {
                bottom: "-8px",
                width: "16px",
                height: "8px",
              }),
              ...(actualPlacement.startsWith("bottom") && {
                top: "-8px",
                width: "16px",
                height: "8px",
              }),
              ...(actualPlacement.startsWith("left") && {
                right: "-8px",
                width: "8px",
                height: "16px",
              }),
              ...(actualPlacement.startsWith("right") && {
                left: "-8px",
                width: "8px",
                height: "16px",
              }),
              // Content positioning
              overflow: "hidden",
            }}
          >
            {/* Border element (rendered behind) */}
            {actualPlacement.startsWith("top") && (
              <div
                style={{
                  position: "absolute",
                  width: 0,
                  height: 0,
                  borderStyle: "solid",
                  borderWidth: "8px 8px 0 8px",
                  borderColor: "#eee transparent transparent transparent",
                  top: "0px",
                  left: "0px",
                }}
              />
            )}
            {actualPlacement.startsWith("bottom") && (
              <div
                style={{
                  position: "absolute",
                  width: 0,
                  height: 0,
                  borderStyle: "solid",
                  borderWidth: "0 8px 8px 8px",
                  borderColor: "transparent transparent #eee transparent",
                  top: "0px",
                  left: "0px",
                }}
              />
            )}
            {actualPlacement.startsWith("left") && (
              <div
                style={{
                  position: "absolute",
                  width: 0,
                  height: 0,
                  borderStyle: "solid",
                  borderWidth: "8px 0 8px 8px",
                  borderColor: "transparent transparent transparent #eee",
                  top: "0px",
                  left: "0px",
                }}
              />
            )}
            {actualPlacement.startsWith("right") && (
              <div
                style={{
                  position: "absolute",
                  width: 0,
                  height: 0,
                  borderStyle: "solid",
                  borderWidth: "8px 8px 8px 0",
                  borderColor: "transparent #eee transparent transparent",
                  top: "0px",
                  left: "0px",
                }}
              />
            )}

            {/* Actual triangle created with CSS borders, slightly smaller and offset to create border effect */}
            <div
              style={{
                position: "absolute",
                width: 0,
                height: 0,
                borderStyle: "solid",
                backgroundColor: "transparent",
                // Position relative to border triangle
                left: "0px",
                zIndex: 1,

                // Top placement - pointing down
                ...(actualPlacement.startsWith("top") && {
                  borderWidth: "7px 7px 0 7px",
                  borderColor: "white transparent transparent transparent",
                  top: "0px",
                }),

                // Bottom placement - pointing up
                ...(actualPlacement.startsWith("bottom") && {
                  borderWidth: "0 7px 7px 7px",
                  borderColor: "transparent transparent white transparent",
                  top: "1px",
                }),

                // Left placement - pointing right
                ...(actualPlacement.startsWith("left") && {
                  borderWidth: "7px 0 7px 7px",
                  borderColor: "transparent transparent transparent white",
                  left: "0px",
                }),

                // Right placement - pointing left
                ...(actualPlacement.startsWith("right") && {
                  borderWidth: "7px 7px 7px 0",
                  borderColor: "transparent white transparent transparent",
                  left: "1px",
                }),
              }}
            />
          </div>
        </>
      )}
    </div>
  );

  // If using portal and the container exists, render through the portal
  if (usePortal && portalContainer) {
    return createPortal(popperContent, portalContainer);
  }

  // Otherwise render normally
  return popperContent;
};
