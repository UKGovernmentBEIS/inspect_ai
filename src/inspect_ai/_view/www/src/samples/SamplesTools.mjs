import { html } from "htm/preact";

import { EpochFilter } from "./tools/EpochFilter.mjs";
import { SortFilter } from "./tools/SortFilter.mjs";
import { SampleFilter } from "./tools/SampleFilter.mjs";
import { SelectScorer } from "./tools/SelectScorer.mjs";

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
    html`<${SampleFilter}
      filter=${filter}
      filterChanged=${filterChanged}
      descriptor=${sampleDescriptor}
    />`,
  );

  tools.push(
    html`<${SortFilter}
      sampleDescriptor=${sampleDescriptor}
      sort=${sort}
      setSort=${setSort}
      epochs=${hasEpochs}
    />`,
  );

  return tools;
};
