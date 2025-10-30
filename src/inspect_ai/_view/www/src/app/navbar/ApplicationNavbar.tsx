import { FC, ReactNode, useRef } from "react";
import { ActivityBar } from "../../components/ActivityBar";
import { useStore } from "../../state/store";
import { ViewerOptionsButton } from "../log-list/ViewerOptionsButton";
import { ViewerOptionsPopover } from "../log-list/ViewerOptionsPopover";
import { Navbar } from "./Navbar";

interface ApplicationNavbarProps {
  currentPath: string | undefined;
  fnNavigationUrl: (file: string, log_dir?: string) => string;
  bordered?: boolean;
  children?: ReactNode;
}

export const ApplicationNavbar: FC<ApplicationNavbarProps> = ({
  currentPath,
  fnNavigationUrl,
  bordered,
  children,
}) => {
  const optionsRef = useRef<HTMLButtonElement>(null);
  const loading = useStore((state) => state.app.status.loading);
  const sampleStatus = useStore((state) => state.sample.sampleStatus);

  const isShowing = useStore((state) => state.app.dialogs.options);
  const setShowing = useStore(
    (state) => state.appActions.setShowingOptionsDialog,
  );

  return (
    <div>
      <Navbar
        currentPath={currentPath}
        fnNavigationUrl={fnNavigationUrl}
        bordered={bordered}
      >
        {children}
        <ViewerOptionsButton
          showing={isShowing}
          setShowing={setShowing}
          ref={optionsRef}
        />
        <ViewerOptionsPopover
          positionEl={optionsRef.current}
          showing={isShowing}
          setShowing={setShowing}
        />
      </Navbar>
      <ActivityBar animating={!!loading || sampleStatus === "loading"} />
    </div>
  );
};
