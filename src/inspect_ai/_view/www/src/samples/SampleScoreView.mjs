import { html } from "htm/preact";
import {
  arrayToString,
  shortenCompletion,
  inputString,
} from "../utils/Format.mjs";
import { MarkdownDiv } from "../components/MarkdownDiv.mjs";
import { SampleScores } from "./SampleScores.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";
import { Card, CardBody, CardHeader } from "../components/Card.mjs";

const labelStyle = {
  paddingRight: "2em",
  paddingLeft: "0",
  paddingBottom: "0",
  ...TextStyle.label,
  ...TextStyle.secondary,
};

export const SampleScoreView = ({
  sample,
  sampleDescriptor,
  style,
  scorer,
}) => {
  if (!sampleDescriptor) {
    return "";
  }
  const scoreInput = [inputString(sample.input)];
  if (sample.choices && sample.choices.length > 0) {
    scoreInput.push("");
    scoreInput.push(
      ...sample.choices.map((choice, index) => {
        return `${String.fromCharCode(65 + index)}) ${choice}`;
      }),
    );
  }

  const scorerDescriptor = sampleDescriptor.scorer(sample, scorer);
  const explanation = scorerDescriptor.explanation() || "(No Explanation)";
  const answer = scorerDescriptor.answer();

  return html`
    <${Card} style=${{ marginTop: "0.5em" }}>
      <${CardHeader} label="Result"/>
      <${CardBody}>
      <div
        style=${{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(100px, 1fr))",
          justifyContent: "space-between",
          columnGap: "0.5em",
          fontSize: FontSize.small,
          paddingBottom: "1em",
          ...style,
        }}>
        <div style=${{ gridColumn: "1/-1" }}>
          <div style=${{ ...labelStyle }}>Input</div>
          <div>
            <${MarkdownDiv}
              markdown=${scoreInput.join("\n")}
              style=${{ wordBreak: "break-all" }}
            />
          </div>
        </div>

        <div>
          <div style=${{ ...labelStyle }}>Target</div>
          <${MarkdownDiv}
            markdown=${arrayToString(arrayToString(sample?.target || "none"))}
            style=${{ paddingLeft: "0" }}
            class="no-last-para-padding"
          />
        </div>

        <div>
          <div style=${{ ...labelStyle }}>Answer</div>
          <${MarkdownDiv}
            class="no-last-para-padding"
            markdown=${shortenCompletion(answer)}
            style=${{ paddingLeft: "0" }}
          />
        </div>

        <div>
          <div style=${{ ...labelStyle }}>Score</div>
          <${SampleScores}
            sample=${sample}
            sampleDescriptor=${sampleDescriptor}
            scorer=${scorer}
          />
        </div>
      </div>
      </${CardBody}>

      ${
        explanation && explanation !== answer
          ? html`<${CardBody}>
        <div style=${{ fontSize: FontSize.small }}>
          <div style=${{ ...labelStyle }}>Explanation</div>
            <${MarkdownDiv} markdown=${arrayToString(explanation)} style=${{ paddingLeft: "0" }} class="no-last-para-padding"/>
        </div>
      </${CardBody}>`
          : ""
      }
    </${Card}>
  `;
};
