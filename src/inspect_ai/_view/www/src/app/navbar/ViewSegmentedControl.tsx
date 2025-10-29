import { FC } from "react";
import { useNavigate } from "react-router-dom";
import { SegmentedControl } from "../../components/SegmentedControl";
import { ApplicationIcons } from "../appearance/icons";

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

  return (
    <SegmentedControl
      segments={segments}
      selectedId={selectedSegment}
      onSegmentChange={(segment) => {
        navigate(`/${segment}`);
      }}
    />
  );
};
