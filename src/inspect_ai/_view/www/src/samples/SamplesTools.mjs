import { html } from "htm/preact";

import { EpochFilter } from "./tools/EpochFilter.mjs";
import { SortFilter } from "./tools/SortFilter.mjs";
import { SampleFilter } from "./tools/SampleFilter.mjs";

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
  } = props;

  const hasEpochs = epochs > 1;
  const tools = [];
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
    html`<${SortFilter} sort=${sort} setSort=${setSort} epochs=${hasEpochs} />`,
  );

  return tools;
};
