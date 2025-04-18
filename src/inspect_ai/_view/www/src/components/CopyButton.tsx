import clsx from "clsx";
import { JSX, useState } from "react";
import { ApplicationIcons } from "../app/appearance/icons";
import styles from "./CopyButton.module.css";

interface CopyButtonProps {
  value: string;
  onCopySuccess?: () => void;
  onCopyError?: (error: Error) => void;
  className?: string;
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
      className={clsx(styles.copyButton, className)}
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
