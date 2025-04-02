import clsx from "clsx";
import { FC, ReactNode } from "react";
import styles from "./Modal.module.css";

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
    <>
      {showing && (
        <div className={styles.backdrop} onClick={() => setShowing(false)} />
      )}
      <div
        id={id}
        className={clsx("modal", "fade", showing ? "show" : "", className)}
        tabIndex={-1}
        style={{ display: showing ? "block" : "none" }}
      >
        <div className={clsx("modal-dialog", styles.modal)}>
          <div className="modal-content">
            <div className={clsx("modal-header", styles.header)}>
              <div
                className={clsx(
                  "modal-title",
                  "text-size-base",
                  styles.modalTitle,
                )}
              >
                {title}
              </div>
              <button
                type="button"
                className={clsx(
                  "btn-close",
                  "text-size-smaller",
                  styles.btnClose,
                )}
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
    </>
  );
};
