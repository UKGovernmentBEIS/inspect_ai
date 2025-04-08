import { clsx } from "clsx";

import { FC, useCallback } from "react";
import { ApplicationIcons } from "../app/appearance/icons";
import { useMessageVisibility } from "../state/hooks";
import "./MessageBand.css";

interface MessageBandProps {
  id: string;
  message: string;
  scope?: "sample" | "eval";
  type: "info" | "warning" | "error";
}

export const MessageBand: FC<MessageBandProps> = ({
  id,
  message,
  type,
  scope = "eval",
}) => {
  const className: string[] = [type];

  const [visible, setVisible] = useMessageVisibility(id, scope);
  const handleClick = useCallback(() => {
    setVisible(false);
  }, [setVisible]);

  if (!visible) {
    className.push("hidden");
  }

  return (
    <div className={clsx("message-band", className)}>
      <i className={ApplicationIcons.logging[type]} />
      {message}
      <button
        className={clsx("btn", "message-band-btn", type)}
        title="Close"
        onClick={handleClick}
      >
        <i className={ApplicationIcons.close}></i>
      </button>
    </div>
  );
};
