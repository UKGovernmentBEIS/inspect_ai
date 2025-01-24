import { html } from "htm/preact";

import { EpochFilter } from "./sample-tools/EpochFilter";
import { SampleFilter } from "./sample-tools/sample-filter/SampleFilter";
import { SelectScorer } from "./sample-tools/SelectScorer";
import { SortFilter } from "./sample-tools/SortFilter";

export const SampleTools = (props) => {
  const {
    epoch,
    setEpoch,
    filter,
    filterChanged,
    sort,
    setSort,
    epochs,
    sampleDescriptor,
    score,
    setScore,
    scores,
  } = props;

  const hasEpochs = epochs > 1;
  const tools = [];

  tools.push(
    html`<${SampleFilter}
      evalDescriptor=${sampleDescriptor.evalDescriptor}
      filter=${filter}
      filterChanged=${filterChanged}
    />`,
  );

  if (scores.length > 1) {
    tools.push(
      html`<${SelectScorer}
        scores=${scores}
        score=${score}
        setScore=${setScore}
      />`,
    );
  }

  if (hasEpochs) {
    tools.push(
      html`<${EpochFilter}
        epoch=${epoch}
        setEpoch="${setEpoch}"
        epochs=${epochs}
      />`,
    );
  }

  tools.push(
    html`<${SortFilter} sort=${sort} setSort=${setSort} epochs=${hasEpochs} />`,
  );

  return tools;
};
