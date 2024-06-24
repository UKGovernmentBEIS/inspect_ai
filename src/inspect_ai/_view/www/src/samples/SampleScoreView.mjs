import { html } from "htm/preact";
import {
  arrayToString,
  shortenCompletion,
  answerForSample,
  inputString,
} from "../utils/Format.mjs";
import { MarkdownDiv } from "../components/MarkdownDiv.mjs";

const labelStyle = {
  paddingRight: "2em",
  paddingLeft: "0",
  paddingBottom: "0",
};

export const SampleScoreView = ({ sample, sampleDescriptor, style }) => {
  const scoreInput = [inputString(sample.input)];
  if (sample.choices && sample.choices.length > 0) {
    scoreInput.push("");
    scoreInput.push(
      ...sample.choices.map((choice, index) => {
        return `${String.fromCharCode(65 + index)}) ${choice}`;
      }),
    );
  }

  return html`
    <div
      class="container-fluid"
      style=${{
        paddingTop: "0",
        paddingLeft: "0",
        fontSize: "0.8rem",
        ...style,
      }}
    >
      <div>
        <div style=${{ ...labelStyle, fontWeight: 600 }}>Input</div>
        <div>
          <${MarkdownDiv} markdown=${scoreInput.join("\n")} />
        </div>
      </div>

      <table
        class="table"
        style=${{ width: "100%", marginBottom: "0", marginTop: "1em" }}
      >
        <thead style=${{ borderBottomColor: "#00000000" }}>
          <tr>
            <th style=${labelStyle}>Target</th>
            <th style=${{ paddingBottom: "0" }}>Answer</th>
            <th style=${{ paddingLeft: "2em", paddingBottom: "0" }}>Score</th>
          </tr>
        </thead>
        <tbody style=${{ borderBottomColor: "#00000000" }}>
          <tr>
            <td style=${{ paddingRight: "2em", paddingLeft: "0" }}>
              <${MarkdownDiv}
                markdown=${arrayToString(
                  arrayToString(sample?.target || "none"),
                )}
                style=${{ paddingLeft: "0" }}
                class="no-last-para-padding"
              />
            </td>
            <td>
              <${MarkdownDiv}
                class="no-last-para-padding"
                markdown=${shortenCompletion(answerForSample(sample))}
                style=${{ paddingLeft: "0" }}
              />
            </td>
            <td style=${{ paddingLeft: "2em" }}>
              ${sampleDescriptor?.scoreDescriptor.render
                ? sampleDescriptor.scoreDescriptor.render(sample?.score?.value)
                : sample?.score?.value === null
                  ? "null"
                  : sample?.score?.value}
            </td>
          </tr>
        </tbody>
      </table>

      ${sample?.score?.explanation &&
      sample?.score?.explanation !== answerForSample(sample)
        ? html`
        <table class="table" style=${{ width: "100%", marginBottom: "0" }}>
              <thead>
                <tr>
                  <th style=${{
                    paddingBottom: "0",
                    paddingLeft: "0",
                  }}>Explanation</th>
                </tr>
              </thead>
              <tbody>
                <td style=${{ paddingLeft: "0" }}>
                  <${MarkdownDiv} markdown=${arrayToString(
                    sample?.score?.explanation,
                  )} style=${{ paddingLeft: "0" }} class="no-last-para-padding"/>
                </td>
              </tbody>
            </table
          `
        : ""}
    </div>
  `;
};
