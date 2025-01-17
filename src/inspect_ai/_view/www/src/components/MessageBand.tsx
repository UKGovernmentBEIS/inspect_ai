import { clsx } from "clsx";

import { ApplicationIcons } from "../appearance/icons";
import "./MessageBand.css";

interface MessageBandProps {
  message: string;
  hidden: boolean;
  setHidden: (hidden: boolean) => void;
  type: "info" | "warning" | "error";
}

export const MessageBand: React.FC<MessageBandProps> = ({
  message,
  hidden,
  setHidden,
  type,
}) => {
  const className: string[] = [type];
  if (hidden) {
    className.push("hidden");
  }

  return (
    <div className={clsx("message-band", className)}>
      <i className={ApplicationIcons.logging[type]} />
      {message}
      <button
        className={clsx("btn", "message-band-btn", type)}
        title="Close"
        onClick={() => {
          setHidden(true);
        }}
      >
        <i className={ApplicationIcons.close}></i>
      </button>
    </div>
  );
};
