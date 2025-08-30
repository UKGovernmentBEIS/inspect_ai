import { FC } from "react";
import { PopOver } from "../../../components/PopOver";

import clsx from "clsx";
import styles from "./TranscriptFilter.module.css";
import { useTranscriptFilter } from "./hooks";

export interface TranscriptFilterProps {
  showing: boolean;
  setShowing: (showing: boolean) => void;
  positionEl: HTMLElement | null;
}

export const TranscriptFilterPopover: FC<TranscriptFilterProps> = ({
  showing,
  positionEl,
  setShowing,
}) => {
  const {
    isDefaultFilter,
    isDebugFilter,
    setDefaultFilter,
    setDebugFilter,
    filterEventType,
    eventTypes,
    filtered,
    arrangedEventTypes,
  } = useTranscriptFilter();

  return (
    <PopOver
      id={`transcript-filter-popover`}
      positionEl={positionEl}
      isOpen={showing}
      setIsOpen={setShowing}
      placement="bottom-end"
      hoverDelay={-1}
    >
      <div className={clsx(styles.links, "text-size-smaller")}>
        <a
          className={clsx(
            styles.link,
            isDefaultFilter ? styles.selected : undefined,
          )}
          onClick={() => setDefaultFilter()}
        >
          Default
        </a>
        |
        <a
          className={clsx(
            styles.link,
            isDebugFilter ? styles.selected : undefined,
          )}
          onClick={() => setDebugFilter()}
        >
          Debug
        </a>
      </div>

      <div className={clsx(styles.grid, "text-size-smaller")}>
        {arrangedEventTypes(2).map((eventType) => {
          return (
            <div
              key={eventType}
              className={clsx(styles.row)}
              onClick={() => {
                filterEventType(eventType, filtered.includes(eventType));
              }}
            >
              <input
                type="checkbox"
                checked={!filtered.includes(eventType)}
                onChange={(e) => {
                  filterEventType(eventType, e.target.checked);
                }}
              ></input>
              {eventTypes[eventType]}
            </div>
          );
        })}
      </div>
    </PopOver>
  );
};
