import { html } from "htm/preact";
import { arrayToString, inputString } from "../utils/Format.mjs";
import { MarkdownDiv } from "../components/MarkdownDiv.mjs";
import { SampleScores } from "./SampleScores.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";
import { MetaDataView } from "../components/MetaDataView.mjs";

const labelStyle = {
  paddingRight: "2em",
  paddingLeft: "0",
  paddingBottom: "0",
  ...TextStyle.label,
  ...TextStyle.secondary,
};

/**
 * @param {Object} props - The component props.
 * @param {import("../types/log").EvalSample} props.sample - The sample.
 * @param {import("../samples/SamplesDescriptor.mjs").SamplesDescriptor} props.sampleDescriptor - The sample descriptor.
 * @param {Object} props.style - The style for the element.
 * @param {string} props.scorer - The scorer.
 * @returns {import("preact").JSX.Element} The SampleScoreView component.
 */
export const SampleScoreView = ({
  sample,
  sampleDescriptor,
  style,
  scorer,
}) => {
  if (!sampleDescriptor) {
    return html``;
  }
  const scoreInput = inputString(sample.input);
  if (sample.choices && sample.choices.length > 0) {
    scoreInput.push("");
    scoreInput.push(
      ...sample.choices.map((choice, index) => {
        return `${String.fromCharCode(65 + index)}) ${choice}`;
      }),
    );
  }

  const scorerDescriptor = sampleDescriptor.evalDescriptor.scorerDescriptor(
    sample,
    { scorer, name: scorer },
  );
  const explanation = scorerDescriptor.explanation() || "(No Explanation)";
  const answer = scorerDescriptor.answer();

  return html`
    <div
      class="container-fluid"
      style=${{
        paddingTop: "1em",
        paddingLeft: "0",
        fontSize: FontSize.base,
        ...style,
      }}
    >
      <div>
        <div style=${{ ...labelStyle }}>Input</div>
        <div>
          <${MarkdownDiv}
            markdown=${scoreInput.join("\n")}
            style=${{ wordBreak: "break-all" }}
          />
        </div>
      </div>

      <table
        class="table"
        style=${{ width: "100%", marginBottom: "0", marginTop: "1em" }}
      >
        <thead style=${{ borderBottomColor: "#00000000" }}>
          <tr>
            <th style=${{ ...labelStyle, fontWeight: "400" }}>Target</th>
            <th
              style=${{ ...labelStyle, paddingBottom: "0", fontWeight: "400" }}
            >
              Answer
            </th>
            <th
              style=${{
                ...labelStyle,
                paddingLeft: "2em",
                paddingBottom: "0",
                fontWeight: "400",
              }}
            >
              Score
            </th>
          </tr>
        </thead>
        <tbody style=${{ borderBottomColor: "#00000000" }}>
          <tr>
            <td
              style=${{
                paddingRight: "2em",
                paddingLeft: "0",
                paddingTop: "0",
              }}
            >
              <${MarkdownDiv}
                markdown=${arrayToString(
                  arrayToString(sample?.target || "none"),
                )}
                style=${{ paddingLeft: "0" }}
                class="no-last-para-padding"
              />
            </td>
            <td style=${{ paddingTop: "0", paddingLeft: "0" }}>
              <${MarkdownDiv}
                class="no-last-para-padding"
                markdown=${answer}
                style=${{ paddingLeft: "0" }}
              />
            </td>
            <td style=${{ paddingLeft: "2em", paddingTop: "0" }}>
              <${SampleScores}
                sample=${sample}
                sampleDescriptor=${sampleDescriptor}
                scorer=${scorer}
              />
            </td>
          </tr>
        </tbody>
      </table>

      ${explanation && explanation !== answer
        ? html` <table
            class="table"
            style=${{ width: "100%", marginBottom: "0" }}
          >
            <thead>
              <tr>
                <th
                  style=${{
                    paddingBottom: "0",
                    paddingLeft: "0",
                    ...labelStyle,
                    fontWeight: "400",
                  }}
                >
                  Explanation
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style=${{ paddingLeft: "0" }}>
                  <${MarkdownDiv}
                    markdown=${arrayToString(explanation)}
                    style=${{ paddingLeft: "0" }}
                    class="no-last-para-padding"
                  />
                </td>
              </tr>
            </tbody>
          </table>`
        : ""}
      ${
        // @ts-ignore
        sample?.score?.metadata &&
        // @ts-ignore
        Object.keys(sample?.score?.metadata).length > 0
          ? html` <table
              class="table"
              style=${{ width: "100%", marginBottom: "0" }}
            >
              <thead>
                <tr>
                  <th
                    style=${{
                      paddingBottom: "0",
                      paddingLeft: "0",
                      ...labelStyle,
                      fontWeight: "400",
                    }}
                  >
                    Metadata
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td style=${{ paddingLeft: "0" }}>
                    <${MetaDataView}
                      id="task-sample-score-metadata"
                      classes="tab-pane"
                      entries="${
                        // @ts-ignore
                        sample?.score?.metadata
                      }"
                      style=${{ marginTop: "1em" }}
                    />
                  </td>
                </tr>
              </tbody>
            </table>`
          : ""
      }
    </div>
  `;
};
