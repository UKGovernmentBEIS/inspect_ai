import { html } from "htm/preact";

// TODO: CSS
//import './ANSIDisplay.css';

import { default as ansi } from "./ansi-output.js";

export const ANSIDisplay = ({ output, style }) => {
  const ansiOutput = new ansi.ANSIOutput();
  ansiOutput.processOutput(output);

  let firstOutput = false;
  return html`<div class="ansi-display" style=${{ ...style }}>
    ${ansiOutput.outputLines.map((line) => {
      firstOutput = firstOutput || !!line.outputRuns.length;
      return html`<div class="ansi-display-line">
        ${!line.outputRuns.length
          ? firstOutput
            ? html`<br />`
            : null
          : line.outputRuns.map(
              (outputRun) =>
                html`<${OutputRun}
                  key=${outputRun.id}
                  outputRun=${outputRun}
                />`,
            )}
      </div>`;
    })}
  </div>`;
};

const kForeground = 0;
const kBackground = 1;

const OutputRun = ({ outputRun }) => {
  const computeStyles = (styles) => {
    let cssProperties = {};
    if (styles) {
      styles.forEach((style) => {
        switch (style) {
          // Bold.
          case ansi.ANSIStyle.Bold:
            cssProperties = { ...cssProperties, ...{ fontWeight: "bold" } };
            break;

          // Dim.
          case ansi.ANSIStyle.Dim:
            cssProperties = { ...cssProperties, ...{ fontWeight: "lighter" } };
            break;

          // Italic.
          case ansi.ANSIStyle.Italic:
            cssProperties = { ...cssProperties, ...{ fontStyle: "italic" } };
            break;

          // Underlined.
          case ansi.ANSIStyle.Underlined:
            cssProperties = {
              ...cssProperties,
              ...{
                textDecorationLine: "underline",
                textDecorationStyle: "solid",
              },
            };
            break;

          // Slow blink.
          case ansi.ANSIStyle.SlowBlink:
            cssProperties = {
              ...cssProperties,
              ...{ animation: "ansi-display-run-blink 1s linear infinite" },
            };
            break;

          // Rapid blink.
          case ansi.ANSIStyle.RapidBlink:
            cssProperties = {
              ...cssProperties,
              ...{ animation: "ansi-display-run-blink 0.5s linear infinite" },
            };
            break;

          // Hidden.
          case ansi.ANSIStyle.Hidden:
            cssProperties = { ...cssProperties, ...{ visibility: "hidden" } };
            break;

          // CrossedOut.
          case ansi.ANSIStyle.CrossedOut:
            cssProperties = {
              ...cssProperties,
              ...{
                textDecorationLine: "line-through",
                textDecorationStyle: "solid",
              },
            };
            break;

          // TODO Fraktur

          // DoubleUnderlined.
          case ansi.ANSIStyle.DoubleUnderlined:
            cssProperties = {
              ...cssProperties,
              ...{
                textDecorationLine: "underline",
                textDecorationStyle: "double",
              },
            };
            break;

          // TODO Framed
          // TODO Encircled
          // TODO Overlined
          // TODO Superscript
          // TODO Subscript
        }
      });
    }

    return cssProperties;
  };

  const computeForegroundBackgroundColor = (colorType, color) => {
    switch (color) {
      // Undefined.
      case undefined:
        return {};

      // One of the standard colors.
      case ansi.ANSIColor.Black:
      case ansi.ANSIColor.Red:
      case ansi.ANSIColor.Green:
      case ansi.ANSIColor.Yellow:
      case ansi.ANSIColor.Blue:
      case ansi.ANSIColor.Magenta:
      case ansi.ANSIColor.Cyan:
      case ansi.ANSIColor.White:
      case ansi.ANSIColor.BrightBlack:
      case ansi.ANSIColor.BrightRed:
      case ansi.ANSIColor.BrightGreen:
      case ansi.ANSIColor.BrightYellow:
      case ansi.ANSIColor.BrightBlue:
      case ansi.ANSIColor.BrightMagenta:
      case ansi.ANSIColor.BrightCyan:
      case ansi.ANSIColor.BrightWhite:
        if (colorType === kForeground) {
          return { color: `var(--${color})` };
        } else {
          return { background: `var(--${color})` };
        }

      // TODO@softwarenerd - This isn't hooked up.
      default:
        if (colorType === kForeground) {
          return { color: color };
        } else {
          return { background: color };
        }
    }
  };

  const computeCSSProperties = (outputRun) => {
    return !outputRun.format
      ? {}
      : {
          ...computeStyles(outputRun.format.styles),
          ...computeForegroundBackgroundColor(
            kForeground,
            outputRun.format.foregroundColor,
          ),
          ...computeForegroundBackgroundColor(
            kBackground,
            outputRun.format.backgroundColor,
          ),
        };
  };

  // Render.
  return html`<span style=${computeCSSProperties(outputRun)}
    >${outputRun.text}</span
  >`;
};
