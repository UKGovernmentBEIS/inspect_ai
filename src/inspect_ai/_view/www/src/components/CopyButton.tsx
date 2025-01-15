import { JSX, useState } from "react";
import { ApplicationIcons } from "../appearance/icons";
import "./CopyButton.css";

interface CopyButtonProps {
  /** The text content to be copied to clipboard */
  value: string;
  /** Optional callback for when copy succeeds */
  onCopySuccess?: () => void;
  /** Optional callback for when copy fails */
  onCopyError?: (error: Error) => void;
  /** Optional class name for custom styling */
  className?: string;
  /** Optional aria-label for accessibility */
  ariaLabel?: string;
}

export const CopyButton = ({
  value,
  onCopySuccess,
  onCopyError,
  className = "",
  ariaLabel = "Copy to clipboard",
}: CopyButtonProps): JSX.Element => {
  const [isCopied, setIsCopied] = useState(false);

  const handleClick = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(value);
      setIsCopied(true);
      onCopySuccess?.();

      // Reset copy state after delay
      setTimeout(() => {
        setIsCopied(false);
      }, 1250);
    } catch (error) {
      onCopyError?.(
        error instanceof Error ? error : new Error("Failed to copy"),
      );
    }
  };

  return (
    <button
      type="button"
      className={["copy-button", className].filter(Boolean).join(" ")}
      onClick={handleClick}
      aria-label={ariaLabel}
      disabled={isCopied}
    >
      <i
        className={
          isCopied
            ? `${ApplicationIcons.confirm} primary`
            : ApplicationIcons.copy
        }
        aria-hidden="true"
      />
    </button>
  );
};
