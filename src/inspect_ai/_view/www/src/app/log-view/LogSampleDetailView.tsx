import { FC } from "react";
import { useLoadLog } from "../../state/useLoadLog";
import { useLoadSample } from "../../state/useLoadSample";
import { usePollSample } from "../../state/usePollSample";
import { useLogRouteParams, logsUrl } from "../routing/url";
import { useLogSampleNavigation } from "../routing/sampleNavigation";
import { SampleDetailComponent } from "../samples/SampleDetailComponent";

/**
 * Component that displays a single sample in detail view within the logs route.
 * This is shown when navigating to /logs/path/to/file.eval/samples/sample/id/epoch
 *
 * This component handles:
 * - Loading hooks (useLoadLog, useLoadSample, usePollSample)
 * - Navigation state via useLogSampleNavigation (respects log filters)
 *
 * Unlike SampleDetailView, this component:
 * - Does NOT clear log state on unmount (user expects to return to same log state)
 * - Uses filteredSamples for navigation (respects current log filters)
 * - Navigates back to log view rather than samples grid
 *
 * Rendering is delegated to SampleDetailComponent.
 */
export const LogSampleDetailView: FC = () => {
  // Load sample data
  useLoadLog();
  useLoadSample();
  usePollSample();

  // Get route params
  const { logPath, sampleId, epoch, sampleTabId } = useLogRouteParams();

  // Get navigation handlers from the hook
  const { onPrevious, onNext, hasPrevious, hasNext } = useLogSampleNavigation();

  return (
    <SampleDetailComponent
      sampleId={sampleId}
      epoch={epoch}
      tabId={sampleTabId}
      navigation={{
        onPrevious,
        onNext,
        hasPrevious,
        hasNext,
      }}
      navbarConfig={{
        currentPath: logPath,
        fnNavigationUrl: logsUrl,
        bordered: true,
      }}
    />
  );
};
