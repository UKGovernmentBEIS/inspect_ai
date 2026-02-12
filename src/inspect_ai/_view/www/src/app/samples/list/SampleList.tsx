import type {
  ColumnResizedEvent,
  IRowNode,
  RowClickedEvent,
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
} from "react";
import { MessageBand } from "../../../components/MessageBand";
import { formatNoDecimal } from "../../../utils/format";
import { SampleListItem } from "../../log-view/tabs/types";
import { EarlyStoppingSummary } from "../../../@types/log";
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
import { buildColumnDefs } from "./columns";
import { SampleFooter } from "./SampleFooter";
import styles from "./SampleList.module.css";

const kSampleHeight = 88;

interface SampleListProps {
  items: SampleListItem[];
  earlyStopping?: EarlyStoppingSummary | null;
  totalItemCount: number;
  running: boolean;
  className?: string | string[];
  listHandle: RefObject<AgGridReact<SampleListItem> | null>;
}

const makeSampleRowId = (id: string | number, epoch: number) =>
  `${id}-${epoch}`.replace(/\s+/g, "_");

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

  // Follow output: auto-scroll to bottom as new items arrive while running
  const followOutputRef = useRef(running);
  const prevItemCountRef = useRef(items.length);

  // When running starts, enable follow output
  useEffect(() => {
    if (running) {
      followOutputRef.current = true;
    }
  }, [running]);

  // When new items arrive while running and following, scroll to bottom
  useEffect(() => {
    if (
      running &&
      followOutputRef.current &&
      items.length > prevItemCountRef.current &&
      listHandle.current?.api
    ) {
      listHandle.current.api.ensureIndexVisible(items.length - 1, "bottom");
    }
    prevItemCountRef.current = items.length;
  }, [items.length, running, listHandle]);

  // Track whether user is at the bottom of the grid
  const handleBodyScroll = useCallback(() => {
    if (!running || !listHandle.current?.api) return;
    const api = listHandle.current.api;
    const vPixel = api.getVerticalPixelRange();
    const totalHeight = api.getDisplayedRowCount() * kSampleHeight;
    const viewportHeight = vPixel.bottom - vPixel.top;
    const atBottom = vPixel.bottom >= totalHeight - viewportHeight * 0.1;
    followOutputRef.current = atBottom;
  }, [running, listHandle]);

  // When eval finishes, scroll to top
  const prevRunningRef = useRef(running);
  useEffect(() => {
    if (!running && prevRunningRef.current && listHandle.current?.api) {
      followOutputRef.current = false;
      setTimeout(() => {
        listHandle.current?.api?.ensureIndexVisible(0, "top");
      }, 100);
    }
    prevRunningRef.current = running;
  }, [running, listHandle]);

  const handleRowClick = useCallback(
    (e: RowClickedEvent<SampleListItem>) => {
      if (e.data && e.node && listHandle.current?.api) {
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
            e.data.data.id,
            e.data.data.epoch,
          );
          if (url) window.open(url, "_blank");
        } else {
          sampleNavigation.showSample(e.data.data.id, e.data.data.epoch);
        }
      }
    },
    [sampleNavigation, listHandle],
  );

  const handleOpenRow = useCallback(
    (rowNode: IRowNode<SampleListItem>, _e: globalThis.KeyboardEvent) => {
      if (rowNode.data) {
        sampleNavigation.showSample(
          rowNode.data.data.id,
          rowNode.data.data.epoch,
        );
      }
    },
    [sampleNavigation],
  );

  const gridContainerRef = useRef<HTMLDivElement>(null);
  const handleKeyDown = useMemo(
    () =>
      createGridKeyboardHandler<SampleListItem>({
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

  const getRowId = useCallback((params: { data: SampleListItem }) => {
    return makeSampleRowId(params.data.data.id, params.data.data.epoch);
  }, []);

  const manuallyResized = useRef(new Set<string>());

  const handleColumnResized = useCallback(
    (event: ColumnResizedEvent<SampleListItem>) => {
      if (
        event.finished &&
        event.source === "uiColumnResized" &&
        event.column
      ) {
        manuallyResized.current.add(event.column.getColId());
        const state = columnDefs
          .filter(
            (c) => c.colId && c.flex && !manuallyResized.current.has(c.colId),
          )
          .map((c) => ({ colId: c.colId!, flex: c.flex }));
        if (state.length > 0) {
          listHandle.current?.api?.applyColumnState({ state });
        }
      }
    },
    [listHandle, columnDefs],
  );

  const sampleCount = items.length;

  const warnings = useMemo(() => {
    const errorCount = items.reduce(
      (prev, item) => (item.data.error ? prev + 1 : prev),
      0,
    );
    const limitCount = items.reduce(
      (prev, item) => (item.data.limit ? prev + 1 : prev),
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
  }, [items, sampleCount, earlyStopping]);

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
        <AgGridReact<SampleListItem>
          ref={listHandle}
          rowData={items}
          columnDefs={columnDefs}
          defaultColDef={{
            filter: false,
            headerTooltipValueGetter: (params) => params.colDef?.headerName,
          }}
          tooltipShowMode="whenTruncated"
          tooltipShowDelay={100}
          animateRows={false}
          rowHeight={kSampleHeight}
          headerHeight={25}
          getRowId={getRowId}
          rowSelection={{ mode: "singleRow", checkboxes: false }}
          onRowClicked={handleRowClick}
          onColumnResized={handleColumnResized}
          theme={themeBalham}
          enableCellTextSelection={true}
          suppressCellFocus={true}
          domLayout="normal"
          onBodyScroll={handleBodyScroll}
          onFirstDataRendered={() => {
            if (running && followOutputRef.current) {
              listHandle.current?.api?.ensureIndexVisible(
                items.length - 1,
                "bottom",
              );
            }
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
