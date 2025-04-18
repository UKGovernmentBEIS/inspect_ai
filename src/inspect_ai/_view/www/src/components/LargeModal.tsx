import clsx from "clsx";
import { ProgressBar } from "./ProgressBar";

import { FC, ReactNode, RefObject, useEffect, useRef } from "react";
import styles from "./LargeModal.module.css";

export interface ModalTool {
  label: string;
  icon: string;
  onClick: () => void;
  enabled: boolean;
}

export interface ModalTools {
  left: ModalTool[];
  right: ModalTool[];
}

interface LargeModalProps {
  id?: string;
  title?: string;
  detail: string;
  detailTools?: ModalTools;
  showProgress: boolean;
  footer?: ReactNode;
  visible: boolean;
  onkeyup: (e: any) => void;
  onHide: () => void;
  scrollRef: RefObject<HTMLDivElement | null>;
  children: ReactNode;
}

export const LargeModal: FC<LargeModalProps> = ({
  id,
  title,
  detail,
  detailTools,
  children,
  footer,
  onkeyup,
  visible,
  onHide,
  showProgress,
  scrollRef,
}) => {
  // The footer
  const modalFooter = footer ? (
    <div className={"modal-footer"}>{footer}</div>
  ) : (
    ""
  );

  // Support restoring the scroll position
  // but only do this for the first time that the children are set
  const modalRef = useRef(null);
  scrollRef = scrollRef || modalRef;

  // Focus the modal when it becomes visible
  const dialogRef = useRef<HTMLDivElement>(null);

  // Use effect to focus the modal when visible changes
  useEffect(() => {
    if (visible && dialogRef.current) {
      dialogRef.current.focus();
    }
  }, [visible]);

  return (
    <div
      id={id}
      className={clsx(
        "modal",
        styles.modal,
        !visible ? styles.hidden : undefined,
      )}
      role="dialog"
      onKeyUp={onkeyup}
      tabIndex={visible ? 0 : undefined}
      ref={dialogRef}
    >
      <div
        className={clsx(
          "modal-dialog",
          "modal-dialog-scrollable",
          styles.modalBody,
        )}
        role="document"
      >
        <div className={clsx("modal-content", styles.content)}>
          <div className={clsx("modal-header", styles.header)}>
            <div
              className={clsx("modal-title", "text-size-smaller", styles.title)}
            >
              {title || ""}
            </div>

            {detail ? (
              <div className={styles.detail}>
                {detailTools?.left
                  ? detailTools.left.map((tool, idx) => {
                      return <TitleTool key={`tool-left-${idx}`} {...tool} />;
                    })
                  : ""}
                <div className={clsx("text-size-smaller", styles.detailText)}>
                  <div>{detail}</div>
                </div>

                {detailTools?.right
                  ? detailTools.right.map((tool, idx) => {
                      return <TitleTool key={`tool-right-${idx}`} {...tool} />;
                    })
                  : ""}
              </div>
            ) : undefined}
            <button
              type="button"
              className={clsx(
                "btn",
                "btn-close-large-dialog",
                "text-size-larger",
                styles.close,
              )}
              onClick={onHide}
              aria-label="Close"
            >
              <HtmlEntity html={"&times;"} />
            </button>
          </div>
          <ProgressBar animating={showProgress} />
          <div className={"modal-body"} ref={scrollRef}>
            {children}
          </div>
          {modalFooter}
        </div>
      </div>
    </div>
  );
};

interface HtmlEntityProps {
  html: string;
}

const HtmlEntity: FC<HtmlEntityProps> = ({ html }) => (
  <span dangerouslySetInnerHTML={{ __html: html }} />
);

interface TitleToolProps {
  label: string;
  icon: string;
  enabled: boolean;
  onClick: () => void;
}

const TitleTool: FC<TitleToolProps> = ({ label, icon, enabled, onClick }) => {
  return (
    <button
      type="button"
      className={clsx(
        "btn",
        "btn-outline",
        "text-size-small",
        styles.titleTool,
      )}
      aria-label={label}
      onClick={onClick}
      disabled={!enabled}
    >
      <i className={icon} />
    </button>
  );
};
