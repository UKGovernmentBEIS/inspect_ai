import { html } from "htm/preact";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

export const SelectScorer = ({ scores, score, setScore }) => {
  const scorers = scores.reduce((accum, scorer) => {
    if (
      !accum.find((sc) => {
        return scorer.scorer === sc.scorer;
      })
    ) {
      accum.push(scorer);
    }
    return accum;
  }, []);

  if (scorers.length === 1) {
    // There is only a single scorer in play, just show the list of available scores
    return html`
      <div style=${{ display: "flex" }}>
        <span
          class="select-scorer-label"
          style=${{
            alignSelf: "center",
            fontSize: FontSize.smaller,
            ...TextStyle.label,
            ...TextStyle.secondary,
          }}
          >Score:</span
        >
        <${ScoreSelector}
          scores=${scores}
          selectedIndex=${scoreIndex(score, scores)}
          selectedIndexChanged=${(index) => {
            setScore(scores[index]);
          }}
        />
      </div>
    `;
  } else {
    // selected scorer

    const scorerScores = scores.filter((sc) => {
      return sc.scorer === score.scorer;
    });

    const selectors = [
      html`<${ScorerSelector}
        scorers=${scorers}
        selectedIndex=${scorerIndex(score, scorers)}
        selectedIndexChanged=${(index) => {
          setScore(scorers[index]);
        }}
      />`,
    ];
    if (scorerScores.length > 1) {
      selectors.push(
        html`<${ScoreSelector}
          style=${{ marginLeft: "1em" }}
          scores=${scorerScores}
          selectedIndex=${scoreIndex(score, scorerScores)}
          selectedIndexChanged=${(index) => {
            setScore(scorerScores[index]);
          }}
        />`,
      );
    }

    // There are multiple scorers, so show a scorer selector and a r
    return html`
      <div style=${{ display: "flex" }}>
        <span
          class="select-scorer-label"
          style=${{
            alignSelf: "center",
            fontSize: FontSize.smaller,
            ...TextStyle.label,
            ...TextStyle.secondary,
            marginRight: "0.3em",
            marginLeft: "0.2em",
          }}
          >Scorer:</span
        >
        ${selectors}
      </div>
    `;
  }
};

const ScoreSelector = ({
  scores,
  selectedIndex,
  selectedIndexChanged,
  style,
}) => {
  return html`<select
    class="form-select form-select-sm"
    aria-label=".select-scorer-label"
    style=${{ fontSize: FontSize.smaller, ...style }}
    value=${scores[selectedIndex].name}
    onChange=${(e) => {
      selectedIndexChanged(e.target.selectedIndex);
    }}
  >
    ${scores.map((score) => {
      return html`<option value="${score.name}">${score.name}</option>`;
    })}
  </select>`;
};

const ScorerSelector = ({ scorers, selectedIndex, selectedIndexChanged }) => {
  return html`<select
    class="form-select form-select-sm"
    aria-label=".epoch-filter-label"
    style=${{ fontSize: FontSize.smaller }}
    value=${scorers[selectedIndex].scorer}
    onChange=${(e) => {
      selectedIndexChanged(e.target.selectedIndex);
    }}
  >
    ${scorers.map((scorer) => {
      return html`<option value="${scorer.scorer}">${scorer.scorer}</option>`;
    })}
  </select>`;
};

const scoreIndex = (score, scores) =>
  scores.findIndex((sc) => {
    return sc.name === score.name && sc.scorer === score.scorer;
  });

const scorerIndex = (score, scores) =>
  scores.findIndex((sc) => {
    return sc.scorer === score.scorer;
  });
