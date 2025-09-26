import { FC } from "react";
import { PopOver } from "../../components/PopOver";

import clsx from "clsx";
import styles from "./ViewerOptionsPopover.module.css";

export interface ViewerOptionsPopoverProps {
  showing: boolean;
  setShowing: (showing: boolean) => void;
  positionEl: HTMLElement | null;
}

export const ViewerOptionsPopover: FC<ViewerOptionsPopoverProps> = ({
  showing,
  positionEl,
  setShowing,
}) => {
  return (
    <PopOver
      id={`viewer-options-filter-popover`}
      positionEl={positionEl}
      isOpen={showing}
      setIsOpen={setShowing}
      placement="auto"
      hoverDelay={-1}
      offset={[-10, 5]}
      showArrow={false}
    >
      <div className={clsx(styles.container, "text-size-smaller")}></div>
    </PopOver>
  );
};
