import { FC, ReactNode, useMemo, useRef } from "react";
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
  showActivity?: "all" | "sample" | "log";
  breadcrumbsEnabled?: boolean;
}

export const ApplicationNavbar: FC<ApplicationNavbarProps> = ({
  currentPath,
  fnNavigationUrl,
  bordered,
  children,
  showActivity = "all",
  breadcrumbsEnabled,
}) => {
  const optionsRef = useRef<HTMLButtonElement>(null);
  const loading = useStore((state) => state.app.status.loading);
  const sampleStatus = useStore((state) => state.sample.sampleStatus);
  const downloadProgress = useStore((state) => state.sample.downloadProgress);

  const isShowing = useStore((state) => state.app.dialogs.options);
  const setShowing = useStore(
    (state) => state.appActions.setShowingOptionsDialog,
  );

  const hasActivity = useMemo(() => {
    if (showActivity === "all") {
      return !!loading || sampleStatus === "loading";
    } else if (showActivity === "log") {
      return !!loading || sampleStatus === "loading";
    } else if (showActivity === "sample") {
      return sampleStatus === "loading";
    } else {
      return false;
    }
  }, [showActivity, loading, sampleStatus]);

  const sampleProgress = useMemo(() => {
    if (sampleStatus === "loading" && downloadProgress) {
      return downloadProgress.bytesLoaded / downloadProgress.bytesTotal;
    }
    return undefined;
  }, [sampleStatus, downloadProgress]);

  return (
    <div>
      <Navbar
        currentPath={currentPath}
        fnNavigationUrl={fnNavigationUrl}
        bordered={bordered}
        breadcrumbsEnabled={breadcrumbsEnabled}
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
      <ActivityBar animating={hasActivity} progress={sampleProgress} />
    </div>
  );
};
