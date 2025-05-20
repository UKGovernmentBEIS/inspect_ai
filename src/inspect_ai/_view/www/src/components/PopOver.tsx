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
}) => {
  const popperRef = useRef<HTMLDivElement | null>(null);
  const arrowRef = useRef<HTMLDivElement | null>(null);
  const [portalContainer, setPortalContainer] = useState<HTMLElement | null>(
    null,
  );

  // Effect to create portal container when needed
  useEffect(() => {
    // Only create portal when the popover is open
    if (usePortal && isOpen) {
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
  }, [usePortal, isOpen, id]);

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
    if (update && isOpen) {
      // Need to delay the update slightly to ensure refs are properly set
      const timer = setTimeout(() => {
        update();
      }, 10);
      return () => clearTimeout(timer);
    }
  }, [update, isOpen, showArrow, arrowRef.current]);

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
    backgroundColor: "white",
    padding: "12px",
    borderRadius: "4px",
    boxShadow: "0 2px 10px rgba(0,0,0,0.1)",
    border: "1px solid #eee",
    zIndex: 1200,
    position: "relative",
  };

  // Early return if not open
  if (!isOpen) return null;

  // Create the popper content
  const popperContent = (
    <div
      ref={popperRef}
      style={{ ...defaultPopperStyles, ...styles.popper }}
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
                  borderWidth: "0 8px 8px 8px",
                  borderColor: "transparent transparent #eee transparent",
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
                  borderWidth: "8px 8px 0 8px",
                  borderColor: "#eee transparent transparent transparent",
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
                top: "1px",
                zIndex: 1,

                // Top placement - pointing down
                ...(actualPlacement.startsWith("top") && {
                  borderWidth: "0 7px 7px 7px",
                  borderColor: "transparent transparent white transparent",
                }),

                // Bottom placement - pointing up
                ...(actualPlacement.startsWith("bottom") && {
                  borderWidth: "7px 7px 0 7px",
                  borderColor: "white transparent transparent transparent",
                  top: "0px",
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
