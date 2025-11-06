import { FC } from "react";
import { useNavigate } from "react-router-dom";
import { SegmentedControl } from "../../components/SegmentedControl";
import { ApplicationIcons } from "../appearance/icons";
import {
  logsUrl,
  samplesUrl,
  useLogRouteParams,
  useSamplesRouteParams,
} from "../routing/url";

interface ViewSegmentControlProps {
  selectedSegment: "logs" | "samples";
}

const segments = [
  { id: "logs", label: "Tasks", icon: ApplicationIcons.navbar.tasks },
  { id: "samples", label: "Samples", icon: ApplicationIcons.sample },
];

export const ViewSegmentedControl: FC<ViewSegmentControlProps> = ({
  selectedSegment,
}) => {
  const navigate = useNavigate();
  const { logPath } = useLogRouteParams();
  const { samplesPath } = useSamplesRouteParams();
  return (
    <SegmentedControl
      segments={segments}
      selectedId={selectedSegment}
      onSegmentChange={(segment) => {
        // Translate between logs and samples routes, preserving path context
        if (segment === "samples") {
          // Going from logs to samples: use logPath if available
          const path = logPath || samplesPath || "";
          const sampleUrl = samplesUrl(path);
          navigate(sampleUrl);
        } else {
          // Going from samples to logs: use samplesPath if available
          const path = samplesPath || logPath || "";
          const logUrl = logsUrl(path);
          navigate(logUrl);
        }
      }}
    />
  );
};
