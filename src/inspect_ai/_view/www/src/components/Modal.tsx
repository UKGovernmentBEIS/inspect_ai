import clsx from "clsx";
import { FC, ReactNode } from "react";

interface ModalProps {
  id: string;
  showing: boolean;
  setShowing: (showing: boolean) => void;
  title?: string;
  children: ReactNode;
  className?: string | string[];
}

export const Modal: FC<ModalProps> = ({
  id,
  title,
  showing,
  setShowing,
  children,
  className,
}) => {
  return (
    <div
      id={id}
      className={clsx("modal", "fade", showing ? "show" : "", className)}
      tabIndex={-1}
      style={{ display: showing ? "block" : "none" }}
    >
      <div className="modal-dialog">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">{title}</h5>
            <button
              type="button"
              className="btn-close"
              data-bs-dismiss="modal"
              aria-label="Close"
              onClick={() => {
                setShowing(!showing);
              }}
            ></button>
          </div>
          <div className="modal-body">{children}</div>
          <div className="modal-footer">
            <button
              type="button"
              className="btn btn-secondary"
              data-bs-dismiss="modal"
              onClick={() => {
                setShowing(!showing);
              }}
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
