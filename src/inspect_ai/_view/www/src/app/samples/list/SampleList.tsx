import type {
  ColDef,
  ICellRendererParams,
  IRowNode,
  RowClickedEvent,
  SortChangedEvent,
} from "ag-grid-community";
import { themeBalham } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import clsx from "clsx";
import {
  FC,
  memo,
  RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { MessageBand } from "../../../components/MessageBand";
import { PulsingDots } from "../../../components/PulsingDots";
import {
  arrayToString,
  formatNoDecimal,
  inputString,
} from "../../../utils/format";
import { truncateMarkdown } from "../../../utils/markdown";
import {
  ListItem,
  SampleListItem,
  SeparatorListItem,
} from "../../log-view/tabs/types";
import { RenderedText } from "../../content/RenderedText";
import { SamplesDescriptor } from "../descriptor/samplesDescriptor";
import { SampleErrorView } from "../error/SampleErrorView";
import { EarlyStoppingSummary } from "../../../@types/log";
import { ScoreLabel } from "../../../app/types";
import {
  useDocumentTitle,
  useSampleDescriptor,
  useScores,
  useSelectedScores,
} from "../../../state/hooks";
import { useStore } from "../../../state/store";
import { useSampleNavigation } from "../../routing/sampleNavigation";
import "../../shared/agGrid";
import { createGridKeyboardHandler } from "../../shared/gridKeyboardNavigation";
import { SampleFooter } from "./SampleFooter";
import styles from "./SampleList.module.css";

const SeparatorRowRenderer: FC<ICellRendererParams<ListItem>> = ({ data }) => {
  if (!data || data.type !== "separator") return null;
  const separator = data as SeparatorListItem;
  return <div className={styles.separator}>{separator.label}</div>;
};

const kSampleHeight = 88;
const kSeparatorHeight = 32;

interface SampleListProps {
  items: ListItem[];
  earlyStopping?: EarlyStoppingSummary | null;
  totalItemCount: number;
  running: boolean;
  className?: string | string[];
  listHandle: RefObject<AgGridReact<ListItem> | null>;
}

// Helper to safely get sample data from a ListItem
const asSample = (item: ListItem | undefined): SampleListItem | undefined => {
  return item?.type === "sample" ? (item as SampleListItem) : undefined;
};

const makeSampleRowId = (id: string | number, epoch: number) =>
  `${id}-${epoch}`.replace(/\s+/g, "_");

function buildColumnDefs(
  samplesDescriptor: SamplesDescriptor | undefined,
  selectedScores: ScoreLabel[],
  scores: ScoreLabel[],
  epochs: number,
): ColDef<ListItem>[] {
  const shape = samplesDescriptor?.messageShape;
  const normalized = shape?.normalized;
  const raw = shape?.raw;

  // Calculate proportional flex values from normalized shape (min 0.15, scale by 10)
  const inputFlex =
    normalized && normalized.input > 0
      ? Math.max(0.15, normalized.input) * 10
      : 0;
  const targetFlex =
    normalized && normalized.target > 0
      ? Math.max(0.15, normalized.target) * 10
      : 0;
  const answerFlex =
    normalized && normalized.answer > 0
      ? Math.max(0.15, normalized.answer) * 10
      : 0;
  const limitFlex =
    normalized && normalized.limit > 0
      ? Math.max(0.15, normalized.limit) * 10
      : 0;

  // Fixed widths from raw shape (rem to px approximation)
  const idWidth = Math.max(2, Math.min(10, raw?.id || 2)) * 14;
  const hasRetries = normalized && normalized.retries > 0;

  const scoreLabels =
    !selectedScores || selectedScores.length === 0
      ? []
      : scores && scores.length === 1
        ? ["Score"]
        : (selectedScores?.map((s) => s.name) ?? []);

  // Score columns use fixed initial widths (matching old CSS grid `rem` sizing)
  // so the proportional text columns (input/target/answer/limit) fill remaining space.
  const rawScores = raw?.scores ?? [];
  const scoreSizes =
    rawScores.length > 0
      ? rawScores.map((size) => Math.max(3, size))
      : scoreLabels.map(() => 6);
  const scoreWidth = (i: number) => (scoreSizes[i] ?? scoreSizes[0] ?? 6) * 9;

  const columns: ColDef<ListItem>[] = [
    {
      field: "sampleId",
      headerName: "Id",
      width: idWidth,
      minWidth: 28,
      maxWidth: 140,
      hide: false,
      suppressSizeToFit: true,
      valueGetter: (params) => asSample(params.data)?.data?.id,
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data) return null;
        return (
          <div
            className={clsx(
              "sample-id",
              "text-size-base",
              "three-line-clamp",
              styles.cell,
            )}
          >
            {params.data.data.id}
          </div>
        );
      },
    },
    {
      field: "sampleEpoch",
      headerName: "Epoch",
      width: 50,
      minWidth: 28,
      hide: epochs <= 1,
      suppressSizeToFit: true,
      valueGetter: (params) => asSample(params.data)?.sampleEpoch,
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
            {params.data.sampleEpoch}
          </div>
        );
      },
    },
    {
      colId: "input",
      headerName: "Input",
      flex: inputFlex || 1,
      minWidth: 80,
      hide: inputFlex === 0,
      valueGetter: (params) => {
        const sample = asSample(params.data);
        return sample ? inputString(sample.data.input).join(" ") : "";
      },
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data) return null;
        const markdown = truncateMarkdown(
          inputString(params.data.data.input).join(" "),
          250,
        );
        return (
          <div
            className={clsx(
              "sample-input",
              "text-size-base",
              "three-line-clamp",
              styles.cell,
              styles.wrapAnywhere,
            )}
          >
            <RenderedText
              markdown={markdown}
              forceRender={true}
              omitMedia={true}
            />
          </div>
        );
      },
    },
    {
      colId: "target",
      headerName: "Target",
      flex: targetFlex || 1,
      minWidth: 80,
      hide: targetFlex === 0,
      valueGetter: (params) => {
        const sample = asSample(params.data);
        return sample?.data?.target != null
          ? arrayToString(sample.data.target)
          : "";
      },
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data?.data?.target) return null;
        const markdown = truncateMarkdown(
          arrayToString(params.data.data.target),
          250,
        );
        return (
          <div
            className={clsx(
              "sample-target",
              "text-size-base",
              "three-line-clamp",
              styles.cell,
            )}
          >
            <RenderedText
              markdown={markdown}
              className={clsx("no-last-para-padding", styles.noLeft)}
              forceRender={true}
              omitMedia={true}
            />
          </div>
        );
      },
    },
    {
      colId: "answer",
      headerName: "Answer",
      flex: answerFlex || 1,
      minWidth: 80,
      hide: answerFlex === 0,
      valueGetter: (params) => asSample(params.data)?.answer ?? "",
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data) return null;
        const markdown = truncateMarkdown(params.data.answer || "", 250);
        return (
          <div
            className={clsx(
              "sample-answer",
              "text-size-base",
              "three-line-clamp",
              styles.cell,
            )}
          >
            <RenderedText
              markdown={markdown}
              className={clsx("no-last-para-padding", styles.noLeft)}
              forceRender={true}
              omitMedia={true}
            />
          </div>
        );
      },
    },
    {
      colId: "limit",
      headerName: "Limit",
      flex: limitFlex || 0.5,
      minWidth: 28,
      maxWidth: 80,
      hide: limitFlex === 0,
      valueGetter: (params) => asSample(params.data)?.data?.limit,
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data) return null;
        return (
          <div
            className={clsx(
              "sample-limit",
              "text-size-small",
              "three-line-clamp",
              styles.cell,
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
      width: 56,
      minWidth: 28,
      maxWidth: 70,
      hide: !hasRetries,
      suppressSizeToFit: true,
      valueGetter: (params) => asSample(params.data)?.data?.retries,
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
      width: scoreWidth(i),
      minWidth: 28,
      valueGetter: (params) => {
        const sample = asSample(params.data);
        if (!sample?.data || !samplesDescriptor) return undefined;
        return samplesDescriptor.evalDescriptor.score(
          sample.data,
          selectedScores[i],
        )?.value;
      },
      cellRenderer: (params: ICellRendererParams<SampleListItem>) => {
        if (!params.data) return null;
        const { data, completed, scoresRendered } = params.data;
        const renderedScores = scoresRendered ?? [];

        if (data.error) {
          return (
            <div className={clsx("text-size-small", styles.cell, styles.score)}>
              <SampleErrorView message={data.error} />
            </div>
          );
        }
        if (completed && renderedScores[i] !== undefined) {
          return (
            <div className={clsx("text-size-small", styles.cell, styles.score)}>
              {renderedScores[i]}
            </div>
          );
        }
        if (
          !completed &&
          i === renderedScores.length - 1 &&
          (renderedScores.length > 0 ||
            Object.keys(data.scores || {}).length === 0)
        ) {
          return (
            <div className={clsx("text-size-small", styles.cell, styles.score)}>
              <PulsingDots subtle={false} />
            </div>
          );
        }
        return (
          <div className={clsx("text-size-small", styles.cell, styles.score)} />
        );
      },
    });
  });

  return columns;
}

export const SampleList: FC<SampleListProps> = memo((props) => {
  const {
    items,
    earlyStopping,
    totalItemCount,
    running,
    className,
    listHandle,
  } = props;

  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  useEffect(() => {
    listHandle.current?.api?.ensureIndexVisible(0, "top");
  }, [listHandle, selectedLogFile]);

  const sampleNavigation = useSampleNavigation();
  const selectedSampleHandle = useStore(
    (state) => state.log.selectedSampleHandle,
  );

  const selectedLogDetails = useStore((state) => state.log.selectedLogDetails);
  const evalSpec = selectedLogDetails?.eval;
  const epochs = evalSpec?.config?.epochs || 1;
  const { setDocumentTitle } = useDocumentTitle();
  useEffect(() => {
    setDocumentTitle({ evalSpec });
  }, [setDocumentTitle, evalSpec]);

  const prevRunningRef = useRef(running);
  useEffect(() => {
    if (!running && prevRunningRef.current && listHandle.current?.api) {
      setTimeout(() => {
        listHandle.current?.api?.ensureIndexVisible(0, "top");
      }, 100);
    }
    prevRunningRef.current = running;
  }, [running, listHandle]);

  // Hide separators when any column is sorted or when there's only 1 epoch
  // (separators only make sense for grouping multiple epochs per sample)
  const [isSorted, setIsSorted] = useState(false);
  const handleSortChanged = useCallback((e: SortChangedEvent<ListItem>) => {
    const sortedColumns = e.api.getColumnState().filter((col) => col.sort);
    setIsSorted(sortedColumns.length > 0);
  }, []);

  const displayItems = useMemo(() => {
    if (isSorted || epochs <= 1) {
      return items.filter((item) => item.type === "sample");
    }
    return items;
  }, [items, isSorted, epochs]);

  const handleRowClick = useCallback(
    (e: RowClickedEvent<ListItem>) => {
      if (
        e.data &&
        e.data.type === "sample" &&
        e.node &&
        listHandle.current?.api
      ) {
        const sample = e.data as SampleListItem;
        listHandle.current.api.deselectAll();
        e.node.setSelected(true);
        const mouseEvent = e.event as MouseEvent | undefined;
        const openInNewWindow =
          mouseEvent?.metaKey ||
          mouseEvent?.ctrlKey ||
          mouseEvent?.shiftKey ||
          mouseEvent?.button === 1;
        if (openInNewWindow) {
          const url = sampleNavigation.getSampleUrl(
            sample.data.id,
            sample.data.epoch,
          );
          if (url) window.open(url, "_blank");
        } else {
          sampleNavigation.showSample(sample.data.id, sample.data.epoch);
        }
      }
    },
    [sampleNavigation, listHandle],
  );

  const handleOpenRow = useCallback(
    (rowNode: IRowNode<ListItem>, _e: globalThis.KeyboardEvent) => {
      if (rowNode.data && rowNode.data.type === "sample") {
        const sample = rowNode.data as SampleListItem;
        sampleNavigation.showSample(sample.data.id, sample.data.epoch);
      }
    },
    [sampleNavigation],
  );

  const gridContainerRef = useRef<HTMLDivElement>(null);
  const handleKeyDown = useMemo(
    () =>
      createGridKeyboardHandler<ListItem>({
        gridRef: listHandle,
        onOpenRow: handleOpenRow,
      }),
    [listHandle, handleOpenRow],
  );

  useEffect(() => {
    const el = gridContainerRef.current;
    if (!el) return;
    const handler = handleKeyDown as (e: Event) => void;
    el.addEventListener("keydown", handler);
    return () => el.removeEventListener("keydown", handler);
  }, [handleKeyDown]);

  const selectCurrentSample = useCallback(() => {
    if (!listHandle.current?.api || !selectedSampleHandle) {
      return;
    }
    const rowId = makeSampleRowId(
      selectedSampleHandle.id,
      selectedSampleHandle.epoch,
    );
    const node = listHandle.current.api.getRowNode(rowId);
    if (node) {
      listHandle.current.api.deselectAll();
      node.setSelected(true);
      listHandle.current.api.ensureNodeVisible(node, "middle");
    }
  }, [listHandle, selectedSampleHandle]);

  useEffect(() => {
    selectCurrentSample();
  }, [selectedSampleHandle, selectCurrentSample]);

  const selectedScores = useSelectedScores();
  const scores = useScores();
  const samplesDescriptor = useSampleDescriptor();
  const columnDefs = useMemo(
    () => buildColumnDefs(samplesDescriptor, selectedScores, scores, epochs),
    [samplesDescriptor, selectedScores, scores, epochs],
  );

  const getRowId = useCallback((params: { data: ListItem }) => {
    const d = params.data;
    if (d.type === "separator") {
      return `separator-${d.index}`;
    }
    const sample = d as SampleListItem;
    return makeSampleRowId(sample.sampleId, sample.sampleEpoch);
  }, []);

  const isFullWidthRow = useCallback(
    (params: { rowNode: IRowNode<ListItem> }) => {
      return params.rowNode.data?.type === "separator";
    },
    [],
  );

  const getRowHeight = useCallback((params: { data: ListItem | undefined }) => {
    return params.data?.type === "separator" ? kSeparatorHeight : kSampleHeight;
  }, []);

  const sampleItems = useMemo(
    () => items.filter((item) => item.type === "sample"),
    [items],
  );
  const sampleCount = sampleItems.length;

  const warnings = useMemo(() => {
    const errorCount = sampleItems.reduce(
      (prev, item) =>
        typeof item.data === "object" && item.data.error ? prev + 1 : prev,
      0,
    );
    const limitCount = sampleItems.reduce(
      (prev, item) =>
        typeof item.data === "object" && item.data.limit ? prev + 1 : prev,
      0,
    );
    const percentError = sampleCount > 0 ? (errorCount / sampleCount) * 100 : 0;
    const percentLimit = sampleCount > 0 ? (limitCount / sampleCount) * 100 : 0;

    const result: { type: string; msg: string }[] = [];
    if (errorCount > 0) {
      result.push({
        type: "info",
        msg: `INFO: ${errorCount} of ${sampleCount} samples (${formatNoDecimal(percentError)}%) had errors and were not scored.`,
      });
    }
    if (limitCount > 0) {
      result.push({
        type: "info",
        msg: `INFO: ${limitCount} of ${sampleCount} samples (${formatNoDecimal(percentLimit)}%) completed due to exceeding a limit.`,
      });
    }
    if (earlyStopping?.early_stops && earlyStopping?.early_stops?.length > 0) {
      result.push({
        type: "info",
        msg: `Skipped ${earlyStopping.early_stops.length} samples due to early stopping (${earlyStopping.manager}). `,
      });
    }
    return result;
  }, [sampleItems, sampleCount, earlyStopping]);

  return (
    <div className={styles.mainLayout}>
      {warnings.map((warning, index) => (
        <MessageBand
          id={`sample-warning-message-${index}`}
          message={warning.msg}
          type={warning.type as "info" | "warning" | "error"}
          key={`sample-warning-message-${index}`}
        />
      ))}
      <div
        ref={gridContainerRef}
        className={clsx(className, styles.samplesListGrid, "samples-list")}
        style={{
          flex: 1,
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
        }}
        tabIndex={0}
      >
        <AgGridReact<ListItem>
          ref={listHandle}
          rowData={displayItems}
          columnDefs={columnDefs}
          defaultColDef={{
            filter: false,
            headerTooltipValueGetter: (params) => params.colDef?.headerName,
          }}
          tooltipShowMode="whenTruncated"
          tooltipShowDelay={100}
          animateRows={false}
          getRowHeight={getRowHeight}
          headerHeight={25}
          getRowId={getRowId}
          rowSelection={{ mode: "singleRow", checkboxes: false }}
          onRowClicked={handleRowClick}
          onSortChanged={handleSortChanged}
          isFullWidthRow={isFullWidthRow}
          fullWidthCellRenderer={SeparatorRowRenderer}
          theme={themeBalham}
          enableCellTextSelection={true}
          suppressCellFocus={true}
          domLayout="normal"
          onFirstDataRendered={() => {
            selectCurrentSample();
          }}
        />
      </div>
      <SampleFooter
        sampleCount={sampleCount}
        totalSampleCount={totalItemCount}
        running={running}
      />
    </div>
  );
});
