import { kScoreTypeOther } from "../../../constants";
import { RenderedContent } from "../../../metadata/RenderedContent";
import { ScoreDescriptor } from "../types";

export const otherScoreDescriptor = (): ScoreDescriptor => {
  return {
    scoreType: kScoreTypeOther,
    compare: () => {
      return 0;
    },
    render: (score) => {
      return (
        <RenderedContent
          id="other-score-value"
          entry={{ name: "other-score-value", value: score }}
        />
      );
    },
  };
};
