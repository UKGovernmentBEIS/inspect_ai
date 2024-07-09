import { html } from "htm/preact";

export const SampleScores = ({ sample, sampleDescriptor, scorer }) => {
  const scores = scorer
    ? sampleDescriptor.scorer(sample, scorer).scores()
    : sampleDescriptor.selectedScorer(sample).scores();

  if (scores.length === 1) {
    return scores[0].rendered();
  } else {
    const rows = scores.map((score) => {
      return html` <div style=${{ opacity: "0.7" }}>${score.name}</div>
        <div>${score.rendered()}</div>`;
    });
    return html`<div
      style=${{
        display: "grid",
        gridTemplateColumns: "max-content max-content",
        columnGap: "1em",
      }}
    >
      ${rows}
    </div>`;
  }
};
