import type { ColDef, ICellRendererParams } from "ag-grid-community";
import clsx from "clsx";
import { FC, ReactNode } from "react";
import { PulsingDots } from "../../../components/PulsingDots";
import { arrayToString, inputString } from "../../../utils/format";
import { truncateMarkdown } from "../../../utils/markdown";
import { SampleListItem } from "../../log-view/tabs/types";
import { RenderedText } from "../../content/RenderedText";
import { SamplesDescriptor } from "../descriptor/samplesDescriptor";
import { SampleErrorView } from "../error/SampleErrorView";
import { ScoreLabel } from "../../../app/types";
import styles from "./SampleList.module.css";

/** Wrapper for the score column cells (used in every branch of the score renderer). */
const ScoreCellDiv: FC<{ children?: ReactNode }> = ({ children }) => (
  <div className={clsx("text-size-small", styles.cell, styles.score)}>
    {children}
  </div>
);

/** Shared cell for columns that render truncated markdown (input, target, answer). */
const MarkdownCellDiv: FC<{
  semanticClass: string;
  text: string;
  trimRenderedText?: boolean;
}> = ({ semanticClass, text, trimRenderedText }) => {
  const markdown = truncateMarkdown(text, 250);
  return (
    <div
      className={clsx(
        semanticClass,
        "text-size-base",
        "three-line-clamp",
        styles.cell,
        styles.wrapAnywhere,
      )}
    >
      <RenderedText
        markdown={markdown}
        className={
          trimRenderedText
            ? clsx("no-last-para-padding", styles.noLeft)
            : undefined
        }
        forceRender={true}
        omitMedia={true}
      />
    </div>
  );
};

export function buildColumnDefs(
  samplesDescriptor: SamplesDescriptor | undefined,
  selectedScores: ScoreLabel[],
  scores: ScoreLabel[],
  epochs: number,
): ColDef<SampleListItem>[] {
  const shape = samplesDescriptor?.messageShape;
  const inputFlex = shape?.inputSize || 3;
  const targetFlex = shape?.targetSize || 1;
  const answerFlex = shape?.answerSize || 1;

  const scoreLabels =
    !selectedScores || selectedScores.length === 0
      ? []
      : scores && scores.length === 1
        ? ["Score"]
        : (selectedScores?.map((s) => s.name) ?? []);

  const columns: ColDef<SampleListItem>[] = [
    {
      colId: "id",
      headerName: "Id",
      width: (shape?.idSize ?? 2) * 16, // 16 for 1em in pixels
      minWidth: 35,
      valueGetter: (params) => params.data?.data?.id,
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data) return null;
        return (
          <div
            className={clsx(
              "sample-id",
              "text-size-base",
              "three-line-clamp",
              styles.cell,
              styles.wrapAnywhere,
            )}
          >
            {params.data.data.id}
          </div>
        );
      },
    },
    {
      colId: "epoch",
      headerName: "Epoch",
      width: 50,
      minWidth: 28,
      hide: epochs <= 1,
      valueGetter: (params) => params.data?.data?.epoch,
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data) return null;
        return (
          <div
            className={clsx(
              "sample-epoch",
              "text-size-base",
              styles.cell,
              styles.centered,
            )}
          >
            {params.data.data.epoch}
          </div>
        );
      },
    },
    {
      colId: "input",
      headerName: "Input",
      flex: inputFlex,
      minWidth: 80,
      hide: !shape?.inputSize,
      valueGetter: (params) => {
        return params.data ? inputString(params.data.data.input).join(" ") : "";
      },
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data) return null;
        return (
          <MarkdownCellDiv
            semanticClass="sample-input"
            text={inputString(params.data.data.input).join(" ")}
          />
        );
      },
    },
    {
      colId: "target",
      headerName: "Target",
      flex: targetFlex,
      minWidth: 80,
      hide: !shape?.targetSize,
      valueGetter: (params) => {
        return params.data?.data?.target != null
          ? arrayToString(params.data.data.target)
          : "";
      },
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data?.data?.target) return null;
        return (
          <MarkdownCellDiv
            semanticClass="sample-target"
            text={arrayToString(params.data.data.target)}
            trimRenderedText
          />
        );
      },
    },
    {
      colId: "answer",
      headerName: "Answer",
      flex: answerFlex,
      minWidth: 80,
      hide: !shape?.answerSize,
      valueGetter: (params) => params.data?.answer ?? "",
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data) return null;
        return (
          <MarkdownCellDiv
            semanticClass="sample-answer"
            text={params.data.answer || ""}
            trimRenderedText
          />
        );
      },
    },
    {
      colId: "limit",
      headerName: "Limit",
      width: (shape?.limitSize ?? 1) * 16,
      minWidth: 28,
      hide: !shape?.limitSize,
      valueGetter: (params) => params.data?.data?.limit,
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data) return null;
        return (
          <div
            className={clsx(
              "sample-limit",
              "text-size-small",
              "three-line-clamp",
              styles.cell,
              styles.wrapAnywhere,
            )}
          >
            {params.data.data.limit}
          </div>
        );
      },
    },
    {
      colId: "retries",
      headerName: "Retries",
      width: (shape?.retriesSize ?? 1) * 16,
      minWidth: 28,
      hide: !shape?.retriesSize,
      valueGetter: (params) => params.data?.data?.retries,
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data) return null;
        const { data } = params.data;
        return (
          <div
            className={clsx(
              "sample-retries",
              "text-size-small",
              "three-line-clamp",
              styles.cell,
              styles.centered,
            )}
          >
            {data.retries && data.retries > 0 ? data.retries : undefined}
          </div>
        );
      },
    },
  ];

  scoreLabels.forEach((label, i) => {
    columns.push({
      headerName: label,
      colId: `score-${i}`,
      width: 80,
      minWidth: 28,
      valueGetter: (params) => {
        if (!params.data?.data || !samplesDescriptor) return undefined;
        return samplesDescriptor.evalDescriptor.score(
          params.data.data,
          selectedScores[i],
        )?.value;
      },
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data) return null;
        const { data, completed } = params.data;
        const rendered = samplesDescriptor?.evalDescriptor
          .score(data, selectedScores[i])
          ?.render();

        if (completed && rendered !== undefined) {
          return <ScoreCellDiv>{rendered}</ScoreCellDiv>;
        }
        if (!completed && i === selectedScores.length - 1) {
          return (
            <ScoreCellDiv>
              <PulsingDots subtle={false} />
            </ScoreCellDiv>
          );
        }
        return <ScoreCellDiv />;
      },
    });
  });

  // Standalone error column — only visible when at least one sample has an error
  columns.push({
    colId: "error",
    headerName: "Error",
    width: (shape?.errorSize ?? 1) * 16,
    minWidth: 28,
    hide: !shape?.errorSize,
    valueGetter: (params) => params.data?.data?.error ?? "",
    cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
      if (!params.data?.data?.error) return null;
      return (
        <div className={clsx("sample-error", "text-size-small", styles.cell)}>
          <SampleErrorView message={params.data.data.error} />
        </div>
      );
    },
  });

  return columns;
}
