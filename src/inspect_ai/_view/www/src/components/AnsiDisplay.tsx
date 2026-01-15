import { ANSIColor, ANSIOutput, ANSIOutputRun, ANSIStyle } from "ansi-output";
import clsx from "clsx";
import { CSSProperties, FC, useState } from "react";
import { ToolButton } from "./ToolButton";

import styles from "./AnsiDisplay.module.css";

interface ANSIDisplayProps {
  output: string;
  style?: CSSProperties;
  className?: string[] | string;
}

export const ANSIDisplay: FC<ANSIDisplayProps> = ({
  output,
  style,
  className,
}) => {
  const [showRaw, setShowRaw] = useState(false);
  const ansiOutput = new ANSIOutput();
  ansiOutput.processOutput(output);

  // Check if more than 80% of lines share the same background color
  const getUniformBackgroundColor = (): string | undefined => {
    const backgroundColorCounts = new Map<string, number>();
    let totalLinesWithBackground = 0;

    // Count background colors across all lines
    for (const line of ansiOutput.outputLines) {
      let lineBackgroundColor: string | undefined = undefined;

      // Get the background color for this line (from any run that has one)
      for (const run of line.outputRuns) {
        if (run.format?.backgroundColor) {
          lineBackgroundColor = run.format.backgroundColor;
          break;
        }
      }

      if (lineBackgroundColor) {
        totalLinesWithBackground++;
        backgroundColorCounts.set(
          lineBackgroundColor,
          (backgroundColorCounts.get(lineBackgroundColor) || 0) + 1,
        );
      }
    }

    // Return undefined if no lines have backgrounds
    if (totalLinesWithBackground === 0) {
      return undefined;
    }

    // Compute percentages for each background color
    const backgroundColorPercentages = new Map<string, number>();
    for (const [color, count] of backgroundColorCounts.entries()) {
      backgroundColorPercentages.set(color, count / totalLinesWithBackground);
    }

    // Find the color with the highest percentage
    let dominantColor: string | undefined = undefined;
    let maxPercentage = 0;

    for (const [color, percentage] of backgroundColorPercentages.entries()) {
      if (percentage > maxPercentage) {
        maxPercentage = percentage;
        dominantColor = color;
      }
    }

    // Return the color if it appears in more than 80% of lines
    return maxPercentage > 0.8 ? dominantColor : undefined;
  };

  const uniformBackgroundColor = getUniformBackgroundColor();
  const backgroundStyle = uniformBackgroundColor
    ? computeForegroundBackgroundColor(kBackground, uniformBackgroundColor)
    : {};

  let firstOutput = false;
  return (
    <div
      className={clsx(styles.ansiDisplayContainer, className)}
      style={{ ...style }}
    >
      <ToolButton
        className={clsx(styles.ansiDisplayToggle, "text-size-smallest")}
        icon="bi bi-code-slash"
        label=""
        latched={showRaw}
        onClick={() => setShowRaw(!showRaw)}
        title={showRaw ? "Show rendered output" : "Show raw output"}
      />
      {showRaw ? (
        <pre className={clsx(styles.ansiDisplay, styles.ansiDisplayRaw)}>
          {output}
        </pre>
      ) : (
        <div className={clsx(styles.ansiDisplay)} style={backgroundStyle}>
          {ansiOutput.outputLines.map((line, index) => {
            firstOutput = firstOutput || !!line.outputRuns.length;
            return (
              <div key={index} className={clsx(styles.ansiDisplayLine)}>
                {!line.outputRuns.length ? (
                  firstOutput ? (
                    <br />
                  ) : null
                ) : (
                  line.outputRuns.map((outputRun) => (
                    <OutputRun key={outputRun.id} run={outputRun} />
                  ))
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

const kForeground = 0;
const kBackground = 1;

interface OutputRunProps {
  run: ANSIOutputRun;
}

const OutputRun: FC<OutputRunProps> = ({ run }) => {
  // Render.
  return <span style={computeCSSProperties(run)}>{run.text}</span>;
};

const computeCSSProperties = (outputRun: ANSIOutputRun) => {
  return !outputRun.format
    ? {}
    : {
        ...computeStyles(outputRun.format.styles || []),
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

const computeStyles = (styles: ANSIStyle[]) => {
  let cssProperties = {};
  if (styles) {
    styles.forEach((style) => {
      switch (style) {
        // Bold.
        case ANSIStyle.Bold:
          cssProperties = { ...cssProperties, ...{ fontWeight: "bold" } };
          break;

        // Dim.
        case ANSIStyle.Dim:
          cssProperties = { ...cssProperties, ...{ fontWeight: "lighter" } };
          break;

        // Italic.
        case ANSIStyle.Italic:
          cssProperties = { ...cssProperties, ...{ fontStyle: "italic" } };
          break;

        // Underlined.
        case ANSIStyle.Underlined:
          cssProperties = {
            ...cssProperties,
            ...{
              textDecorationLine: "underline",
              textDecorationStyle: "solid",
            },
          };
          break;

        // Slow blink.
        case ANSIStyle.SlowBlink:
          cssProperties = {
            ...cssProperties,
            ...{ animation: "ansi-display-run-blink 1s linear infinite" },
          };
          break;

        // Rapid blink.
        case ANSIStyle.RapidBlink:
          cssProperties = {
            ...cssProperties,
            ...{ animation: "ansi-display-run-blink 0.5s linear infinite" },
          };
          break;

        // Hidden.
        case ANSIStyle.Hidden:
          cssProperties = { ...cssProperties, ...{ visibility: "hidden" } };
          break;

        // CrossedOut.
        case ANSIStyle.CrossedOut:
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
        case ANSIStyle.DoubleUnderlined:
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

const computeForegroundBackgroundColor = (
  colorType: number,
  color?: string,
) => {
  switch (color) {
    // Undefined.
    case undefined:
      return {};

    // One of the standard colors.
    case ANSIColor.Black:
    case ANSIColor.Red:
    case ANSIColor.Green:
    case ANSIColor.Yellow:
    case ANSIColor.Blue:
    case ANSIColor.Magenta:
    case ANSIColor.Cyan:
    case ANSIColor.White:
    case ANSIColor.BrightBlack:
    case ANSIColor.BrightRed:
    case ANSIColor.BrightGreen:
    case ANSIColor.BrightYellow:
    case ANSIColor.BrightBlue:
    case ANSIColor.BrightMagenta:
    case ANSIColor.BrightCyan:
    case ANSIColor.BrightWhite:
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
