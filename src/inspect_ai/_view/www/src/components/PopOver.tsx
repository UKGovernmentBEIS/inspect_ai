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
        padding: 8,
      },
    },
    {
      name: "computeStyles",
      options: {
        gpuAcceleration: false,
        adaptive: true,
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

  // Get appropriate color for the arrow based on side it's on
  const getArrowBorderStyling = (): CSSProperties => {
    const placement = getArrowDataPlacement();

    const borderStyle = "1px solid #eee";
    const result: CSSProperties = {
      borderTop: "none",
      borderLeft: "none",
      borderRight: "none",
      borderBottom: "none",
    };

    if (placement.startsWith("top")) {
      result.borderRight = borderStyle;
      result.borderBottom = borderStyle;
    } else if (placement.startsWith("bottom")) {
      result.borderTop = borderStyle;
      result.borderLeft = borderStyle;
    } else if (placement.startsWith("left")) {
      result.borderTop = borderStyle;
      result.borderRight = borderStyle;
    } else if (placement.startsWith("right")) {
      result.borderBottom = borderStyle;
      result.borderLeft = borderStyle;
    }

    return result;
  };

  // Popper container styles
  const defaultPopperStyles: CSSProperties = {
    backgroundColor: "white",
    padding: "12px",
    borderRadius: "4px",
    boxShadow: "0 2px 10px rgba(0,0,0,0.1)",
    border: "1px solid #eee",
    zIndex: 1200,
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
        <div
          ref={arrowRef}
          className={clsx("popper-arrow", arrowClassName)}
          style={{
            ...styles.arrow,
            position: "absolute",
            width: "8px",
            height: "8px",
            backgroundColor: "white",
            ...getArrowBorderStyling(),
            transform: "rotate(45deg)",
            // Ensure the arrow isn't too close to content
            margin: "-4px",
            top: 0,
            zIndex: 1,
          }}
          data-placement={getArrowDataPlacement()}
        />
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
