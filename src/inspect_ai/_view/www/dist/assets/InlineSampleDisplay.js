import { u as useStore, N as getSamplePolling, O as resolveSample$1, L as createLogger, j as jsxRuntimeExports, x as debounce, A as ApplicationIcons, P as kDefaultExcludeEvents, Q as useSampleEventUrl, R as Link, S as supportsLinking, T as toFullUrl, U as parsedJson, c as useLogRouteParams, h as useParams, a as useNavigate, H as useLogOrSampleRouteParams, V as useSampleUrlBuilder, W as isVscode, X as kSampleTranscriptTabId, Y as kSampleMessagesTabId, Z as kSampleScoringTabId, _ as kSampleMetdataTabId, $ as kSampleErrorTabId, a0 as kSampleJsonTabId, a1 as estimateSize, E as ErrorPanel } from "./index.js";
import { X as useSampleData, Y as useLogSelection, V as usePrevious, Z as findScrollableParent, _ as scrollRangeToCenter, c as clsx, $ as useStatefulScrollPosition, D as formatNumber, a0 as useVirtuosoState, F as useProperty, a1 as useRafThrottle, a2 as Yr, a3 as ChatView, a4 as resolveMessages, a5 as ChatMessageRow, a6 as MarkdownIt, r as errorType, x as useSampleDescriptor, q as useSelectedScores, w as RenderedText, v as arrayToString, a7 as formatTime, t as inputString, a as formatDateTime, a8 as getScoreDescriptorForValues, o as useEvalDescriptor, R as RenderedContent, i as RecordTree, E as ExpandablePanel, P as PopOver, a9 as useCollapseSampleEvent, aa as useSamplePopover, M as MetaDataGrid, ab as useScrollTrack, G as CopyButton, g as ANSIDisplay, J as JSONPanel, W as usePrismHighlight, ac as toArray, ad as resolveToolInput, ae as ToolCallView, af as substituteToolCallContent, ag as useCollapsedState, ah as useSelectedSampleSummary, ai as messagesFromEvents, e as useDocumentTitle, aj as escapeSelector, T as ToolButton, Q as ActivityBar } from "./ApplicationNavbar.js";
import { b as reactExports } from "./vendor-grid.js";
import { c as useSampleDetailNavigation } from "./sampleNavigation.js";
import "./vendor-prism.js";
import { c as create } from "./vendor-asciinema.js";
const SAMPLE_LIST_KEYS = ["transcript-tree"];
const log$1 = createLogger("useSampleLoader");
let loadGeneration = 0;
function useLoadSample() {
  const sampleData = useSampleData();
  const logSelection = useLogSelection();
  const api = useStore((state) => state.api);
  const sampleActions = useStore((state) => state.sampleActions);
  const clearListPosition = useStore(
    (state) => state.appActions.clearListPosition
  );
  const getSelectedSample = useStore(
    (state) => state.sampleActions.getSelectedSample
  );
  const sampleId = logSelection.sample?.id;
  const sampleEpoch = logSelection.sample?.epoch;
  const sampleCompleted = logSelection.sample?.completed;
  const currentSampleCompleted = sampleCompleted !== void 0 ? sampleCompleted : true;
  const prevCompleted = usePrevious(currentSampleCompleted);
  const prevLogFile = usePrevious(logSelection.logFile);
  const prevSampleId = usePrevious(sampleId);
  const prevSampleNeedsReload = usePrevious(
    sampleData.sampleNeedsReload
  );
  const loadSample = reactExports.useCallback(
    async (logFile, id, epoch, completed) => {
      const currentId = sampleData.selectedSampleIdentifier;
      const isSameSample = currentId?.id === id && currentId?.epoch === epoch && currentId?.logFile === logFile;
      const isLoading = sampleData.status === "loading" || sampleData.status === "streaming";
      if (isSameSample && isLoading) {
        return;
      }
      const thisGeneration = ++loadGeneration;
      for (const key of SAMPLE_LIST_KEYS) {
        clearListPosition(key);
      }
      sampleActions.prepareForSampleLoad(logFile, id, epoch);
      try {
        if (completed !== false) {
          log$1.debug(`LOADING COMPLETED SAMPLE: ${id}-${epoch}`);
          getSamplePolling().stopPolling();
          const sample2 = await api?.get_log_sample(logFile, id, epoch);
          log$1.debug(`LOADED COMPLETED SAMPLE: ${id}-${epoch}`);
          if (thisGeneration !== loadGeneration) {
            log$1.debug(`Discarding stale sample response: ${id}-${epoch}`);
            return;
          }
          if (sample2) {
            const isNewSample = currentId?.id !== id || currentId?.epoch !== epoch || currentId?.logFile !== logFile;
            if (isNewSample) {
              sampleActions.clearCollapsedEvents();
            }
            const migratedSample = resolveSample$1(sample2);
            sampleActions.setSelectedSample(migratedSample, logFile);
            sampleActions.setSampleStatus("ok");
          } else {
            sampleActions.setSampleStatus("error");
            throw new Error(
              "Unable to load sample - an unknown error occurred"
            );
          }
        } else {
          log$1.debug(`PREPARING FOR POLLING RUNNING SAMPLE: ${id}-${epoch}`);
          sampleActions.clearSampleForPolling(logFile, id, epoch);
          getSamplePolling().stopPolling();
        }
      } catch (e) {
        sampleActions.setSampleError(e);
        sampleActions.setSampleStatus("error");
      }
    },
    [
      api,
      clearListPosition,
      sampleActions,
      sampleData.selectedSampleIdentifier,
      sampleData.status
    ]
  );
  reactExports.useEffect(() => {
    if (logSelection.logFile && sampleId !== void 0 && sampleEpoch !== void 0) {
      const identifierMatches = sampleData.selectedSampleIdentifier?.id === sampleId && sampleData.selectedSampleIdentifier?.epoch === sampleEpoch && sampleData.selectedSampleIdentifier?.logFile === logSelection.logFile;
      const hasSampleData = getSelectedSample() !== void 0;
      const isCurrentSampleLoaded = identifierMatches && hasSampleData;
      const isLoading = sampleData.status === "loading" || sampleData.status === "streaming";
      const isError = sampleData.status === "error";
      const logFileChanged = prevLogFile !== void 0 && prevLogFile !== logSelection.logFile;
      const sampleIdChanged = prevSampleId !== void 0 && prevSampleId !== sampleId;
      const completedChanged = prevCompleted !== void 0 && currentSampleCompleted !== prevCompleted;
      const needsReloadChanged = prevSampleNeedsReload !== void 0 && prevSampleNeedsReload !== sampleData.sampleNeedsReload;
      const shouldLoad = !isCurrentSampleLoaded && !isLoading && !isError || logFileChanged || sampleIdChanged || completedChanged || needsReloadChanged;
      if (shouldLoad) {
        void loadSample(
          logSelection.logFile,
          sampleId,
          sampleEpoch,
          sampleCompleted
        );
      }
    }
  }, [
    logSelection.logFile,
    sampleId,
    sampleEpoch,
    sampleCompleted,
    currentSampleCompleted,
    sampleData.selectedSampleIdentifier,
    sampleData.status,
    sampleData.sampleNeedsReload,
    sampleData.getSelectedSample,
    prevLogFile,
    prevSampleId,
    prevCompleted,
    prevSampleNeedsReload,
    loadSample,
    getSelectedSample
  ]);
}
const log = createLogger("useSamplePolling");
function usePollSample() {
  const logSelection = useLogSelection();
  const loadedLog = useStore((state) => state.log.loadedLog);
  const sampleId = logSelection.sample?.id;
  const sampleEpoch = logSelection.sample?.epoch;
  const sampleCompleted = logSelection.sample?.completed;
  reactExports.useEffect(() => {
    if (logSelection.logFile && sampleId !== void 0 && sampleEpoch !== void 0 && sampleCompleted === false && loadedLog) {
      log.debug(`Starting poll for running sample: ${sampleId}-${sampleEpoch}`);
      const sampleSummary = {
        id: sampleId,
        epoch: sampleEpoch
      };
      getSamplePolling().startPolling(logSelection.logFile, sampleSummary);
    }
  }, [logSelection.logFile, sampleId, sampleEpoch, sampleCompleted, loadedLog]);
  reactExports.useEffect(() => {
    return () => {
      getSamplePolling().stopPolling();
    };
  }, []);
}
const ExtendedFindContext = reactExports.createContext(null);
const ExtendedFindProvider = ({
  children
}) => {
  const virtualLists = reactExports.useRef(/* @__PURE__ */ new Map());
  const matchCounters = reactExports.useRef(/* @__PURE__ */ new Map());
  const extendedFindTerm = reactExports.useCallback(
    async (term, direction) => {
      for (const [, searchFn] of virtualLists.current) {
        const found = await new Promise((resolve) => {
          let callbackFired = false;
          const onContentReady = () => {
            if (!callbackFired) {
              callbackFired = true;
              resolve(true);
            }
          };
          searchFn(term, direction, onContentReady).then((found2) => {
            if (!found2 && !callbackFired) {
              callbackFired = true;
              resolve(false);
            }
          }).catch(() => {
            if (!callbackFired) {
              callbackFired = true;
              resolve(false);
            }
          });
        });
        if (found) {
          return true;
        }
      }
      return false;
    },
    []
  );
  const registerVirtualList = reactExports.useCallback(
    (id, searchFn) => {
      virtualLists.current.set(id, searchFn);
      return () => {
        virtualLists.current.delete(id);
      };
    },
    []
  );
  const countAllMatches = reactExports.useCallback((term) => {
    let total = 0;
    for (const [, countFn] of matchCounters.current) {
      total += countFn(term);
    }
    return total;
  }, []);
  const registerMatchCounter = reactExports.useCallback(
    (id, countFn) => {
      matchCounters.current.set(id, countFn);
      return () => {
        matchCounters.current.delete(id);
      };
    },
    []
  );
  const contextValue = {
    extendedFindTerm,
    registerVirtualList,
    countAllMatches,
    registerMatchCounter
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsx(ExtendedFindContext.Provider, { value: contextValue, children });
};
const useExtendedFind = () => {
  const context = reactExports.useContext(ExtendedFindContext);
  if (!context) {
    throw new Error("useSearch must be used within a SearchProvider");
  }
  return context;
};
const findConfig = {
  caseSensitive: false,
  wrapAround: false,
  wholeWord: false,
  searchInFrames: false,
  showDialog: false
};
const FindBand = () => {
  const searchBoxRef = reactExports.useRef(null);
  const storeHideFind = useStore((state) => state.appActions.hideFind);
  const { extendedFindTerm, countAllMatches } = useExtendedFind();
  const lastFoundItem = reactExports.useRef(null);
  const currentSearchTerm = reactExports.useRef("");
  const needsCursorRestoreRef = reactExports.useRef(false);
  const scrollTimeoutRef = reactExports.useRef(null);
  const focusTimeoutRef = reactExports.useRef(null);
  const searchIdRef = reactExports.useRef(0);
  const cachedCount = reactExports.useRef({
    term: "",
    count: 0
  });
  const mutatedPanelsRef = reactExports.useRef(/* @__PURE__ */ new Map());
  const [matchCount, setMatchCount] = reactExports.useState(null);
  const [currentMatchIndex, setCurrentMatchIndex] = reactExports.useState(0);
  const getParentExpandablePanel = reactExports.useCallback(
    (selection) => {
      let node2 = selection.anchorNode;
      while (node2) {
        if (node2 instanceof HTMLElement && node2.hasAttribute("data-expandable-panel")) {
          return node2;
        }
        node2 = node2.parentElement;
      }
      return void 0;
    },
    []
  );
  const handleSearch = reactExports.useCallback(
    async (back = false) => {
      const thisSearchId = ++searchIdRef.current;
      const searchTerm = searchBoxRef.current?.value ?? "";
      if (!searchTerm) {
        setMatchCount(null);
        setCurrentMatchIndex(0);
        return;
      }
      if (currentSearchTerm.current !== searchTerm) {
        lastFoundItem.current = null;
        currentSearchTerm.current = searchTerm;
        setCurrentMatchIndex(0);
      }
      let total;
      if (cachedCount.current.term === searchTerm) {
        total = cachedCount.current.count;
      } else {
        total = countAllMatches(searchTerm);
        cachedCount.current = { term: searchTerm, count: total };
      }
      setMatchCount(total);
      if (total === 0) {
        setCurrentMatchIndex(0);
        return;
      }
      const focusedElement = document.activeElement;
      const selection = window.getSelection();
      let savedRange = null;
      if (selection && selection.rangeCount > 0) {
        savedRange = selection.getRangeAt(0).cloneRange();
      }
      const savedScrollParent = savedRange ? findScrollableParent(savedRange.startContainer.parentElement) : null;
      const savedScrollTop = savedScrollParent?.scrollTop ?? 0;
      const result2 = await findExtendedInDOM(
        searchTerm,
        back,
        lastFoundItem.current,
        extendedFindTerm
      );
      if (searchIdRef.current !== thisSearchId) {
        return;
      }
      if (!result2 && savedRange) {
        const sel = window.getSelection();
        if (sel) {
          sel.removeAllRanges();
          sel.addRange(savedRange);
        }
        if (savedScrollParent) {
          savedScrollParent.scrollTop = savedScrollTop;
        }
      }
      if (result2) {
        const selection2 = window.getSelection();
        if (selection2 && selection2.rangeCount > 0) {
          const range = selection2.getRangeAt(0);
          const parentElement = range.startContainer.parentElement || range.commonAncestorContainer;
          const isNewMatch = !isLastFoundItem(range, lastFoundItem.current);
          lastFoundItem.current = {
            text: range.toString(),
            offset: range.startOffset,
            parentElement
          };
          if (isNewMatch) {
            setCurrentMatchIndex((prev) => {
              if (back) {
                return prev <= 1 ? total : prev - 1;
              } else {
                return prev >= total ? 1 : prev + 1;
              }
            });
          }
          const parentPanel = getParentExpandablePanel(selection2);
          if (parentPanel) {
            if (!mutatedPanelsRef.current.has(parentPanel)) {
              mutatedPanelsRef.current.set(parentPanel, {
                display: parentPanel.style.display,
                maxHeight: parentPanel.style.maxHeight,
                webkitLineClamp: parentPanel.style.webkitLineClamp,
                webkitBoxOrient: parentPanel.style.webkitBoxOrient
              });
            }
            parentPanel.style.display = "block";
            parentPanel.style.maxHeight = "none";
            parentPanel.style.webkitLineClamp = "";
            parentPanel.style.webkitBoxOrient = "";
          }
          if (scrollTimeoutRef.current !== null) {
            window.clearTimeout(scrollTimeoutRef.current);
          }
          scrollTimeoutRef.current = window.setTimeout(() => {
            scrollRangeToCenter(range);
          }, 100);
        }
      }
      focusedElement?.focus();
    },
    [getParentExpandablePanel, extendedFindTerm, countAllMatches]
  );
  reactExports.useEffect(() => {
    focusTimeoutRef.current = window.setTimeout(() => {
      searchBoxRef.current?.focus();
      searchBoxRef.current?.select();
    }, 10);
    const mutatedPanels = mutatedPanelsRef.current;
    const scrollTimeout = scrollTimeoutRef.current;
    const focusTimeout = focusTimeoutRef.current;
    return () => {
      if (scrollTimeout !== null) {
        window.clearTimeout(scrollTimeout);
      }
      if (focusTimeout !== null) {
        window.clearTimeout(focusTimeout);
      }
      mutatedPanels.forEach((originalStyles, panel2) => {
        panel2.style.display = originalStyles.display;
        panel2.style.maxHeight = originalStyles.maxHeight;
        panel2.style.webkitLineClamp = originalStyles.webkitLineClamp;
        panel2.style.webkitBoxOrient = originalStyles.webkitBoxOrient;
      });
      mutatedPanels.clear();
    };
  }, []);
  const handleKeyDown = reactExports.useCallback(
    (e) => {
      if (e.key === "Escape") {
        storeHideFind();
      } else if (e.key === "Enter") {
        void handleSearch(e.shiftKey);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "g") {
        e.preventDefault();
        void handleSearch(e.shiftKey);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        searchBoxRef.current?.focus();
        searchBoxRef.current?.select();
      }
    },
    [storeHideFind, handleSearch]
  );
  const findPrevious = reactExports.useCallback(() => {
    void handleSearch(true);
  }, [handleSearch]);
  const findNext = reactExports.useCallback(() => {
    void handleSearch(false);
  }, [handleSearch]);
  const restoreCursor = reactExports.useCallback(() => {
    if (!needsCursorRestoreRef.current) return;
    needsCursorRestoreRef.current = false;
    const input = searchBoxRef.current;
    if (input) {
      const len = input.value.length;
      input.setSelectionRange(len, len);
    }
  }, []);
  const debouncedSearch = reactExports.useMemo(
    () => debounce(async () => {
      if (!searchBoxRef.current) return;
      await handleSearch(false);
      needsCursorRestoreRef.current = true;
    }, 300),
    [handleSearch]
  );
  const handleInputChange = reactExports.useCallback(() => {
    debouncedSearch();
  }, [debouncedSearch]);
  const handleBeforeInput = reactExports.useCallback(() => {
    const input = searchBoxRef.current;
    if (input) {
      const hasSelection = input.selectionStart !== input.selectionEnd;
      if (!hasSelection) {
        restoreCursor();
      }
    }
  }, [restoreCursor]);
  reactExports.useEffect(() => {
    const handleGlobalKeyDown = (e) => {
      if (e.key === "F3") {
        e.preventDefault();
        void handleSearch(e.shiftKey);
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault();
        e.stopPropagation();
        searchBoxRef.current?.focus();
        searchBoxRef.current?.select();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "g") {
        e.preventDefault();
        e.stopPropagation();
        void handleSearch(e.shiftKey);
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key.length !== 1 && e.key !== "Backspace" && e.key !== "Delete")
        return;
      const input = searchBoxRef.current;
      if (!input) return;
      const hasSelection = input.selectionStart !== input.selectionEnd;
      if (!hasSelection) {
        restoreCursor();
      }
      if (document.activeElement !== input) {
        input.focus();
      }
    };
    document.addEventListener("keydown", handleGlobalKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleGlobalKeyDown, true);
    };
  }, [handleSearch, restoreCursor]);
  const matchCountLabel = reactExports.useMemo(() => {
    if (matchCount === null) return null;
    if (matchCount === 0) return "No results";
    return `${currentMatchIndex} of ${matchCount}`;
  }, [matchCount, currentMatchIndex]);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { "data-unsearchable": "true", className: clsx("findBand"), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "input",
      {
        type: "text",
        ref: searchBoxRef,
        placeholder: "Find",
        onKeyDown: handleKeyDown,
        onBeforeInput: handleBeforeInput,
        onChange: handleInputChange
      }
    ),
    matchCountLabel !== null && /* @__PURE__ */ jsxRuntimeExports.jsx(
      "span",
      {
        className: clsx(
          "findBand-match-count",
          matchCount === 0 && "findBand-no-results"
        ),
        children: matchCountLabel
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "button",
      {
        type: "button",
        title: "Previous match",
        className: "btn next",
        onClick: findPrevious,
        children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: ApplicationIcons.arrows.up })
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "button",
      {
        type: "button",
        title: "Next match",
        className: "btn prev",
        onClick: findNext,
        children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: ApplicationIcons.arrows.down })
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "button",
      {
        type: "button",
        title: "Close",
        className: "btn close",
        onClick: storeHideFind,
        children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: ApplicationIcons.close })
      }
    )
  ] });
};
function windowFind(searchTerm, back) {
  return window.find(
    searchTerm,
    findConfig.caseSensitive,
    back,
    findConfig.wrapAround,
    findConfig.wholeWord,
    findConfig.searchInFrames,
    findConfig.showDialog
  );
}
function positionSelectionForWrap(back) {
  if (!back) return;
  const sel = window.getSelection();
  if (sel) {
    const range = document.createRange();
    range.selectNodeContents(document.body);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
  }
}
async function findExtendedInDOM(searchTerm, back, lastFoundItem, extendedFindTerm) {
  let result2 = false;
  let hasTriedExtendedSearch = false;
  let extendedSearchSucceeded = false;
  const maxAttempts = 25;
  for (let attempts = 0; attempts < maxAttempts; attempts++) {
    result2 = windowFind(searchTerm, back);
    if (result2) {
      const selection = window.getSelection();
      if (selection && selection.rangeCount > 0) {
        const range = selection.getRangeAt(0);
        const isUnsearchable = inUnsearchableElement(range);
        const isSameAsLast = isLastFoundItem(range, lastFoundItem);
        if (!isUnsearchable && !isSameAsLast) {
          break;
        }
        if (isSameAsLast) {
          if (!hasTriedExtendedSearch) {
            hasTriedExtendedSearch = true;
            window.getSelection()?.removeAllRanges();
            const foundInVirtual = await extendedFindTerm(
              searchTerm,
              back ? "backward" : "forward"
            );
            if (foundInVirtual) {
              extendedSearchSucceeded = true;
              continue;
            }
          }
          if (extendedSearchSucceeded) {
            const sel = window.getSelection();
            if (sel?.rangeCount) {
              sel.getRangeAt(0).collapse(!back);
            }
          } else {
            window.getSelection()?.removeAllRanges();
            positionSelectionForWrap(back);
          }
          result2 = windowFind(searchTerm, back);
          if (result2) {
            const sel = window.getSelection();
            if (sel && sel.rangeCount > 0) {
              const r = sel.getRangeAt(0);
              if (inUnsearchableElement(r)) {
                continue;
              }
            }
          }
          break;
        }
      }
    } else if (!hasTriedExtendedSearch) {
      hasTriedExtendedSearch = true;
      window.getSelection()?.removeAllRanges();
      const foundInVirtual = await extendedFindTerm(
        searchTerm,
        back ? "backward" : "forward"
      );
      if (foundInVirtual) {
        extendedSearchSucceeded = true;
        continue;
      }
      positionSelectionForWrap(back);
      result2 = windowFind(searchTerm, back);
      if (result2) {
        const sel = window.getSelection();
        if (sel && sel.rangeCount > 0) {
          const r = sel.getRangeAt(0);
          if (inUnsearchableElement(r)) {
            continue;
          }
        }
      }
      break;
    } else {
      break;
    }
  }
  if (result2) {
    const sel = window.getSelection();
    if (sel?.rangeCount && inUnsearchableElement(sel.getRangeAt(0))) {
      sel.removeAllRanges();
      result2 = false;
    }
  }
  return result2;
}
function isLastFoundItem(range, lastFoundItem) {
  if (!lastFoundItem) return false;
  const currentText = range.toString();
  const currentOffset = range.startOffset;
  const currentParentElement = range.startContainer.parentElement || range.commonAncestorContainer;
  return currentText === lastFoundItem.text && currentOffset === lastFoundItem.offset && currentParentElement === lastFoundItem.parentElement;
}
function inUnsearchableElement(range) {
  let element = selectionParentElement(range);
  let isUnsearchable = false;
  while (element) {
    if (element.hasAttribute("data-unsearchable") || getComputedStyle(element).userSelect === "none") {
      isUnsearchable = true;
      break;
    }
    element = element.parentElement;
  }
  return isUnsearchable;
}
function selectionParentElement(range) {
  let element = null;
  if (range.startContainer.nodeType === Node.ELEMENT_NODE) {
    element = range.startContainer;
  } else {
    element = range.startContainer.parentElement;
  }
  if (!element && range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE) {
    element = range.commonAncestorContainer;
  } else if (!element && range.commonAncestorContainer.parentElement) {
    element = range.commonAncestorContainer.parentElement;
  }
  return element;
}
const tabs = "_tabs_1rv6h_1";
const tabContents = "_tabContents_1rv6h_5";
const scrollable = "_scrollable_1rv6h_11";
const tab$1 = "_tab_1rv6h_1";
const tabItem = "_tabItem_1rv6h_25";
const tabIcon = "_tabIcon_1rv6h_29";
const tabTools = "_tabTools_1rv6h_33";
const tabStyle = "_tabStyle_1rv6h_43";
const moduleStyles = {
  tabs,
  tabContents,
  scrollable,
  tab: tab$1,
  tabItem,
  tabIcon,
  tabTools,
  tabStyle
};
const TabSet = ({
  id,
  type = "tabs",
  className,
  tabPanelsClassName,
  tabControlsClassName,
  tools: tools2,
  tabsRef,
  children
}) => {
  const validTabs = flattenChildren(children);
  if (validTabs.length === 0) return null;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(reactExports.Fragment, { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "ul",
      {
        ref: tabsRef,
        id,
        className: clsx(
          "nav",
          `nav-${type}`,
          type === "tabs" ? moduleStyles.tabStyle : void 0,
          className,
          moduleStyles.tabs
        ),
        role: "tablist",
        "aria-orientation": "horizontal",
        children: [
          validTabs.map((tab2, index) => /* @__PURE__ */ jsxRuntimeExports.jsx(
            Tab,
            {
              index,
              type,
              tab: tab2,
              className: clsx(tabControlsClassName)
            },
            tab2.props.id
          )),
          tools2 && /* @__PURE__ */ jsxRuntimeExports.jsx(TabTools, { tools: tools2 })
        ]
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(TabPanels, { id, tabs: validTabs, className: tabPanelsClassName })
  ] });
};
const Tab = ({ type = "tabs", tab: tab2, index, className }) => {
  const tabId = tab2.props.id || computeTabId("tabset", index);
  const tabContentsId = computeTabContentsId(tab2.props.id);
  const isActive = tab2.props.selected;
  return /* @__PURE__ */ jsxRuntimeExports.jsx("li", { role: "presentation", className: clsx("nav-item", moduleStyles.tabItem), children: /* @__PURE__ */ jsxRuntimeExports.jsxs(
    "button",
    {
      id: tabId,
      className: clsx(
        "nav-link",
        className,
        isActive && "active",
        type === "pills" ? moduleStyles.pill : moduleStyles.tab,
        "text-size-small",
        "text-style-label"
      ),
      type: "button",
      role: "tab",
      "aria-controls": tabContentsId,
      "aria-selected": isActive,
      onClick: tab2.props.onSelected,
      children: [
        tab2.props.icon && /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx(tab2.props.icon, moduleStyles.tabIcon) }),
        tab2.props.title
      ]
    }
  ) });
};
const TabPanels = ({ id, tabs: tabs2, className }) => /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("tab-content", className), id: `${id}-content`, children: tabs2.map((tab2, index) => /* @__PURE__ */ jsxRuntimeExports.jsx(TabPanel, { ...tab2.props, index }, tab2.props.id)) });
const TabPanel = ({
  id,
  selected: selected2,
  style,
  scrollable: scrollable2 = true,
  scrollRef,
  className,
  children
}) => {
  const tabContentsId = computeTabContentsId(id);
  const panelRef = reactExports.useRef(null);
  const tabContentsRef = scrollRef || panelRef;
  useStatefulScrollPosition(tabContentsRef, tabContentsId, 1e3, scrollable2);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    "div",
    {
      id: tabContentsId,
      ref: tabContentsRef,
      className: clsx(
        "tab-pane",
        selected2 && "show active",
        className,
        moduleStyles.tabContents,
        scrollable2 && moduleStyles.scrollable
      ),
      style,
      children: selected2 ? children : null
    }
  );
};
const TabTools = ({ tools: tools2 }) => /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("tab-tools", moduleStyles.tabTools), children: tools2 });
const computeTabId = (id, index) => `${id}-${index}`;
const computeTabContentsId = (id) => `${id}-contents`;
const flattenChildren = (children) => {
  return reactExports.Children.toArray(children).flatMap((child) => {
    if (reactExports.isValidElement(child)) {
      const element = child;
      if (element.type === reactExports.Fragment) {
        return flattenChildren(element.props.children);
      }
      return element;
    }
    return [];
  });
};
const dropdownContainer = "_dropdownContainer_h3ljc_1";
const toolButton = "_toolButton_h3ljc_6";
const chevron = "_chevron_h3ljc_10";
const backdrop = "_backdrop_h3ljc_24";
const dropdownMenu = "_dropdownMenu_h3ljc_33";
const dropdownItem = "_dropdownItem_h3ljc_47";
const styles$A = {
  dropdownContainer,
  toolButton,
  chevron,
  backdrop,
  dropdownMenu,
  dropdownItem
};
const ToolDropdownButton = reactExports.forwardRef(({ label: label2, icon: icon2, className, items, ...rest }, ref) => {
  const [isOpen, setIsOpen] = reactExports.useState(false);
  const handleItemClick = (fn) => {
    fn();
    setIsOpen(false);
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$A.dropdownContainer, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "button",
      {
        ref,
        type: "button",
        className: clsx("btn", "btn-tools", styles$A.toolButton, className),
        onClick: () => setIsOpen(!isOpen),
        ...rest,
        children: [
          icon2 && /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: `${icon2}` }),
          label2,
          /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx("bi-chevron-down", styles$A.chevron) })
        ]
      }
    ),
    isOpen && /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$A.backdrop, onClick: () => setIsOpen(false) }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$A.dropdownMenu, children: Object.entries(items).map(([itemLabel, fn]) => /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          type: "button",
          className: styles$A.dropdownItem,
          onClick: () => handleItemClick(fn),
          children: itemLabel
        },
        itemLabel
      )) })
    ] })
  ] });
});
ToolDropdownButton.displayName = "ToolDropdownButton";
const CardHeader = ({
  id,
  icon: icon2,
  label: label2,
  className,
  children
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(
    "div",
    {
      className: clsx("card-header-container", "text-style-label", className),
      id: id || "",
      children: [
        icon2 ? /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx("card-header-icon", icon2) }) : /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "card-header-icon" }),
        label2 ? label2 : "",
        " ",
        children
      ]
    }
  );
};
const CardBody = ({
  id,
  children,
  className,
  padded: padded2 = true
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    "div",
    {
      className: clsx(
        "card-body",
        className,
        !padded2 ? "card-no-padding" : void 0
      ),
      id: id || "",
      children
    }
  );
};
const Card = ({ id, children, className }) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("card", className), id, children });
};
const panel$2 = "_panel_twp3v_1";
const container$7 = "_container_twp3v_7";
const styles$z = {
  panel: panel$2,
  container: container$7
};
const NoContentsPanel = ({ text }) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$z.panel), children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$z.container, "text-size-smaller"), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: ApplicationIcons.noSamples }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: text })
  ] }) });
};
const printHtml = (html, css) => {
  const printWindow = window.open("", "", "height=600,width=800");
  if (printWindow !== null) {
    printWindow.document.write("<html><head><title>Print</title>");
    printWindow.document.write(`
          <link rel="stylesheet" crossorigin="" href="./assets/index.css">
          <style>
            @media print {
              ${css}
            }
          </style>
        `);
    printWindow.document.write("</head><body>");
    printWindow.document.write(html);
    printWindow.document.write("</body></html>");
    printWindow.document.close();
    printWindow.onload = function() {
      printWindow.focus();
      printWindow.print();
      printWindow.close();
    };
  } else {
    console.error("Print window failed to open.");
  }
};
const printHeadingHtml = () => {
  const taskEl = document.getElementById("task-title");
  const modelEl = document.getElementById("task-model");
  const timeEl = document.getElementById("task-created");
  if (!taskEl || !modelEl || !timeEl) {
    throw new Error(
      "Failed to compute heading HTML. The task, model, or time element can't be found."
    );
  }
  const task = taskEl.innerText;
  const model2 = modelEl.innerText;
  const time = timeEl.innerText;
  const headingHtml = `
<div style="display: grid; grid-template-columns: repeat(3, 1fr); column-gap: 0.5em; margin-bottom: 2em; justify-content: space-between; border-bottom: solid 1px silver;">
<div style="font-weight: 600">${task}</div>
<div style="text-align: center;">${model2}</div>
<div style="text-align: right;">${time}</div>
</div>`;
  return headingHtml;
};
const messagesToStr = (messages2, options) => {
  const opts = {};
  return messages2.map((msg) => messageToStr(msg, opts)).filter((str) => str !== null).join("\n");
};
const messageToStr = (message2, options) => {
  if (options.excludeSystem && message2.role === "system") {
    return null;
  }
  const content = betterContentText(
    message2.content,
    options.excludeToolUsage || false,
    options.excludeReasoning || false
  );
  if (!options.excludeToolUsage && message2.role === "assistant" && message2.tool_calls) {
    const assistantMsg = message2;
    let entry = `${message2.role.toUpperCase()}:
${content}
`;
    if (assistantMsg.tool_calls) {
      for (const tool2 of assistantMsg.tool_calls) {
        const funcName = tool2.function;
        const args = tool2.arguments;
        if (typeof args === "object" && args !== null) {
          const argsText = Object.entries(args).map(([k, v]) => `${k}: ${v}`).join("\n");
          entry += `
Tool Call: ${funcName}
Arguments:
${argsText}
`;
        } else {
          entry += `
Tool Call: ${funcName}
Arguments: ${args}
`;
        }
      }
    }
    return entry;
  }
  if (message2.role === "tool") {
    if (options.excludeToolUsage) {
      return null;
    }
    const toolMsg = message2;
    const funcName = toolMsg.function || "unknown";
    const errorPart = toolMsg.error ? `

Error in tool call '${funcName}':
${toolMsg.error.message}
` : "";
    return `${message2.role.toUpperCase()}:
${content}${errorPart}
`;
  }
  return `${message2.role.toUpperCase()}:
${content}
`;
};
const textFromContent = (content, excludeToolUsage, excludeReasoning) => {
  switch (content.type) {
    case "text":
      return content.text;
    case "reasoning": {
      const reasoningContent = content;
      if (excludeReasoning) {
        return null;
      }
      const reasoning = reasoningContent.redacted ? reasoningContent.summary : reasoningContent.reasoning;
      if (!reasoning) {
        return null;
      }
      return `
<think>${reasoning}</think>`;
    }
    case "tool_use": {
      if (excludeToolUsage) {
        return null;
      }
      const toolUse = content;
      const errorStr = toolUse.error ? ` ${toolUse.error}` : "";
      return `
Tool Use: ${toolUse.name}(${toolUse.arguments}) -> ${toolUse.result}${errorStr}`;
    }
    case "image":
    case "audio":
    case "video":
    case "data":
    case "document":
      return `<${content.type} />`;
    default:
      return null;
  }
};
const betterContentText = (content, excludeToolUsage, excludeReasoning) => {
  if (typeof content === "string") {
    return content;
  }
  const allText = content.map((c) => textFromContent(c, excludeToolUsage, excludeReasoning)).filter((text) => text !== null);
  return allText.join("\n");
};
const wrapper$1 = "_wrapper_sq96g_1";
const col2$1 = "_col2_sq96g_8";
const col1_3$1 = "_col1_3_sq96g_12";
const col3$1 = "_col3_sq96g_16";
const separator$4 = "_separator_sq96g_20";
const padded$1 = "_padded_sq96g_26";
const styles$y = {
  wrapper: wrapper$1,
  col2: col2$1,
  col1_3: col1_3$1,
  col3: col3$1,
  separator: separator$4,
  padded: padded$1
};
const ModelUsagePanel = ({ usage, className }) => {
  if (!usage) {
    return null;
  }
  const rows = [];
  if (usage.reasoning_tokens) {
    rows.push({
      label: "Reasoning",
      value: usage.reasoning_tokens,
      secondary: false,
      bordered: true
    });
    rows.push({
      label: "---",
      value: void 0,
      secondary: false,
      padded: true
    });
  }
  rows.push({
    label: "input",
    value: usage.input_tokens,
    secondary: false
  });
  if (usage.input_tokens_cache_read) {
    rows.push({
      label: "cache_read",
      value: usage.input_tokens_cache_read,
      secondary: true
    });
  }
  if (usage.input_tokens_cache_write) {
    rows.push({
      label: "cache_write",
      value: usage.input_tokens_cache_write,
      secondary: true
    });
  }
  rows.push({
    label: "Output",
    value: usage.output_tokens,
    secondary: false,
    bordered: true
  });
  rows.push({
    label: "---",
    value: void 0,
    secondary: false
  });
  rows.push({
    label: "Total",
    value: usage.total_tokens,
    secondary: false
  });
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-size-small", styles$y.wrapper, className), children: rows.map((row2, idx) => {
    if (row2.label === "---") {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(
        "div",
        {
          className: clsx(
            styles$y.separator,
            row2.padded ? styles$y.padded : void 0
          )
        },
        `$usage-sep-${idx}`
      );
    } else {
      return /* @__PURE__ */ jsxRuntimeExports.jsxs(reactExports.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            className: clsx(
              "text-style-label",
              "text-style-secondary",
              row2.secondary ? styles$y.col2 : styles$y.col1_3
            ),
            children: row2.label
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$y.col3, children: row2.value ? formatNumber(row2.value) : "" })
      ] }, `$usage-row-${idx}`);
    }
  }) });
};
const table = "_table_z217i_1";
const tableTokens = "_tableTokens_z217i_5";
const tableH = "_tableH_z217i_9";
const model = "_model_z217i_14";
const cellContents = "_cellContents_z217i_18";
const styles$x = {
  table,
  tableTokens,
  tableH,
  model,
  cellContents
};
const TokenTable = ({ className, children }) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    "table",
    {
      className: clsx(
        "table",
        "table-sm",
        "text-size-smaller",
        styles$x.table,
        className
      ),
      children
    }
  );
};
const TokenHeader = () => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("thead", { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("tr", { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("td", {}),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "td",
        {
          colSpan: 3,
          className: clsx(
            "card-subheading",
            styles$x.tableTokens,
            "text-size-small",
            "text-style-label",
            "text-style-secondary"
          ),
          align: "center",
          children: "Tokens"
        }
      )
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("tr", { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "th",
        {
          className: clsx(
            styles$x.tableH,
            "text-sixe-small",
            "text-style-label",
            "text-style-secondary"
          ),
          children: "Model"
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "th",
        {
          className: clsx(
            styles$x.tableH,
            "text-sixe-small",
            "text-style-label",
            "text-style-secondary"
          ),
          children: "Usage"
        }
      )
    ] })
  ] });
};
const TokenRow = ({ model: model2, usage }) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("tr", { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$x.model, styles$x.cellContents), children: model2 }) }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("td", { children: /* @__PURE__ */ jsxRuntimeExports.jsx(ModelUsagePanel, { usage, className: clsx(styles$x.cellContents) }) })
  ] });
};
const ModelTokenTable = ({
  model_usage,
  className
}) => {
  if (!model_usage) {
    return null;
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(TokenTable, { className, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(TokenHeader, {}),
    /* @__PURE__ */ jsxRuntimeExports.jsx("tbody", { children: Object.keys(model_usage).map((key) => {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(TokenRow, { model: key, usage: model_usage[key] }, key);
    }) })
  ] });
};
const container$6 = "_container_4p85e_2";
const dotsContainer = "_dotsContainer_4p85e_8";
const small = "_small_4p85e_15";
const medium = "_medium_4p85e_19";
const large = "_large_4p85e_24";
const dot = "_dot_4p85e_8";
const subtle = "_subtle_4p85e_36";
const primary = "_primary_4p85e_40";
const visuallyHidden = "_visuallyHidden_4p85e_59";
const styles$w = {
  container: container$6,
  dotsContainer,
  small,
  medium,
  large,
  dot,
  subtle,
  primary,
  visuallyHidden
};
const PulsingDots = ({
  text = "Loading...",
  dotsCount = 3,
  subtle: subtle2 = true,
  size = "small",
  className
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(
    "div",
    {
      className: clsx(
        styles$w.container,
        size === "small" ? styles$w.small : size === "medium" ? styles$w.medium : styles$w.large,
        className
      ),
      role: "status",
      children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$w.dotsContainer, children: [...Array(dotsCount)].map((_, index) => /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            className: clsx(
              styles$w.dot,
              subtle2 ? styles$w.subtle : styles$w.primary
            ),
            style: { animationDelay: `${index * 0.2}s` }
          },
          index
        )) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: styles$w.visuallyHidden, children: text })
      ]
    }
  );
};
const progressContainer = "_progressContainer_1cjjr_1";
const styles$v = {
  progressContainer
};
const LiveVirtualList = ({
  id,
  listHandle,
  className,
  data,
  renderRow,
  scrollRef,
  live,
  showProgress,
  initialTopMostItemIndex,
  offsetTop,
  components,
  itemSearchText
}) => {
  const { getRestoreState, isScrolling, visibleRange, setVisibleRange } = useVirtuosoState(listHandle, `live-virtual-list-${id}`);
  const { registerVirtualList, registerMatchCounter } = useExtendedFind();
  const pendingSearchCallback = reactExports.useRef(null);
  const [isCurrentlyScrolling, setIsCurrentlyScrolling] = reactExports.useState(false);
  const [followOutput, setFollowOutput] = useProperty(
    id,
    "follow",
    {
      defaultValue: null
    }
  );
  const isAutoScrollingRef = reactExports.useRef(false);
  reactExports.useEffect(() => {
    if (followOutput === null) {
      setFollowOutput(!!live);
    }
  }, [followOutput, live, setFollowOutput]);
  const prevLive = usePrevious(live);
  reactExports.useEffect(() => {
    if (!live && prevLive && followOutput && scrollRef?.current) {
      setFollowOutput(false);
      setTimeout(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTo({ top: 0, behavior: "instant" });
        }
      }, 100);
    }
  }, [live, followOutput, prevLive, scrollRef, setFollowOutput]);
  const handleScroll = useRafThrottle(() => {
    if (isAutoScrollingRef.current) return;
    if (!live) return;
    if (scrollRef?.current && listHandle.current) {
      const parent = scrollRef.current;
      const isAtBottom = parent.scrollHeight - parent.scrollTop <= parent.clientHeight + 30;
      if (isAtBottom && !followOutput) {
        setFollowOutput(true);
      } else if (!isAtBottom && followOutput) {
        setFollowOutput(false);
      }
    }
  }, [setFollowOutput, followOutput, live]);
  const heightChanged = reactExports.useCallback(
    (height) => {
      requestAnimationFrame(() => {
        if (followOutput && live && scrollRef?.current) {
          isAutoScrollingRef.current = true;
          listHandle.current?.scrollTo({ top: height });
          requestAnimationFrame(() => {
            isAutoScrollingRef.current = false;
          });
        }
      });
    },
    [followOutput, live, scrollRef, listHandle]
  );
  const forceUpdate = reactExports.useCallback(() => forceRender({}), []);
  reactExports.useEffect(() => {
    const timer = setTimeout(() => {
      forceUpdate();
    }, 0);
    return () => clearTimeout(timer);
  }, [forceUpdate]);
  const [, forceRender] = reactExports.useState({});
  const defaultItemSearchText = reactExports.useCallback((item) => {
    try {
      return JSON.stringify(item);
    } catch {
      return "";
    }
  }, []);
  const searchInText = reactExports.useCallback(
    (text, searchTerm) => {
      const lowerText = text.toLowerCase();
      const prepared = prepareSearchTerm(searchTerm);
      if (lowerText.includes(prepared.simple)) {
        return true;
      }
      if (prepared.unquoted && lowerText.includes(prepared.unquoted)) {
        return true;
      }
      if (prepared.jsonEscaped && lowerText.includes(prepared.jsonEscaped)) {
        return true;
      }
      return false;
    },
    []
  );
  const searchInItem = reactExports.useCallback(
    (item, searchTerm) => {
      const getSearchText = itemSearchText ?? defaultItemSearchText;
      const texts = getSearchText(item);
      const textArray = Array.isArray(texts) ? texts : [texts];
      return textArray.some((text) => searchInText(text, searchTerm));
    },
    [itemSearchText, defaultItemSearchText, searchInText]
  );
  const scrollToMatch = reactExports.useCallback(
    (index, onContentReady) => {
      pendingSearchCallback.current = onContentReady;
      listHandle.current?.scrollToIndex({
        index,
        behavior: "auto",
        align: "center"
      });
      setTimeout(() => {
        if (pendingSearchCallback.current === onContentReady) {
          pendingSearchCallback.current = null;
          onContentReady();
        }
      }, 200);
    },
    [listHandle]
  );
  const searchInData = reactExports.useCallback(
    async (term, direction, onContentReady) => {
      if (!data.length || !term) return false;
      const isForward = direction === "forward";
      const currentIndex = isForward ? visibleRange.endIndex : visibleRange.startIndex;
      const len = data.length;
      for (let offset = 1; offset < len; offset++) {
        const i = isForward ? (currentIndex + offset) % len : (currentIndex - offset + len) % len;
        if (i >= visibleRange.startIndex && i <= visibleRange.endIndex)
          continue;
        if (searchInItem(data[i], term)) {
          scrollToMatch(i, onContentReady);
          return true;
        }
      }
      return false;
    },
    [
      data,
      searchInItem,
      visibleRange.endIndex,
      visibleRange.startIndex,
      scrollToMatch
    ]
  );
  const countMatchesInData = reactExports.useCallback(
    (term) => {
      if (!term || !data.length) return 0;
      const lower = term.toLowerCase();
      let total = 0;
      const getSearchText = itemSearchText ?? defaultItemSearchText;
      for (const item of data) {
        const texts = getSearchText(item);
        const textArray = Array.isArray(texts) ? texts : [texts];
        for (const text of textArray) {
          const lowerText = text.toLowerCase();
          let pos = 0;
          while ((pos = lowerText.indexOf(lower, pos)) !== -1) {
            total++;
            pos += lower.length;
          }
        }
      }
      return total;
    },
    [data, itemSearchText, defaultItemSearchText]
  );
  reactExports.useEffect(() => {
    const unregisterSearch = registerVirtualList(id, searchInData);
    const unregisterCount = registerMatchCounter(id, countMatchesInData);
    return () => {
      unregisterSearch();
      unregisterCount();
    };
  }, [
    id,
    registerVirtualList,
    registerMatchCounter,
    searchInData,
    countMatchesInData
  ]);
  const Footer = () => {
    return showProgress ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$v.progressContainer), children: /* @__PURE__ */ jsxRuntimeExports.jsx(PulsingDots, { subtle: false, size: "medium" }) }) : void 0;
  };
  reactExports.useEffect(() => {
    const parent = scrollRef?.current;
    if (parent) {
      parent.addEventListener("scroll", handleScroll);
      return () => parent.removeEventListener("scroll", handleScroll);
    }
  }, [scrollRef, handleScroll]);
  const hasScrolled = reactExports.useRef(false);
  reactExports.useEffect(() => {
    if (initialTopMostItemIndex !== void 0 && listHandle.current) {
      const timer = setTimeout(() => {
        listHandle.current?.scrollToIndex({
          index: initialTopMostItemIndex,
          align: "start",
          behavior: !hasScrolled.current ? "auto" : "smooth",
          offset: offsetTop ? -offsetTop : void 0
        });
        hasScrolled.current = true;
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [initialTopMostItemIndex, listHandle, offsetTop]);
  reactExports.useEffect(() => {
    if (!isCurrentlyScrolling && pendingSearchCallback.current) {
      setTimeout(() => {
        const callback = pendingSearchCallback.current;
        pendingSearchCallback.current = null;
        callback?.();
      }, 100);
    }
  }, [isCurrentlyScrolling]);
  const handleScrollingChange = reactExports.useCallback(
    (scrolling) => {
      setIsCurrentlyScrolling(scrolling);
      isScrolling(scrolling);
    },
    [isScrolling]
  );
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    Yr,
    {
      ref: listHandle,
      customScrollParent: scrollRef?.current ? scrollRef.current : void 0,
      style: { height: "100%", width: "100%" },
      data,
      defaultItemHeight: 500,
      itemContent: renderRow,
      increaseViewportBy: { top: 1e3, bottom: 1e3 },
      overscan: { main: 5, reverse: 5 },
      className: clsx("transcript", className),
      isScrolling: handleScrollingChange,
      rangeChanged: (range) => {
        setVisibleRange(range);
      },
      skipAnimationFrameInResizeObserver: true,
      restoreStateFrom: getRestoreState(),
      totalListHeightChanged: heightChanged,
      components: {
        Footer,
        ...components
      }
    }
  );
};
const prepareSearchTerm = (term) => {
  const lower = term.toLowerCase();
  if (!term.includes('"') && !term.includes(":")) {
    return { simple: lower };
  }
  return {
    simple: lower,
    // Remove quotes
    unquoted: lower.replace(/"/g, ""),
    // Escape quotes for JSON
    jsonEscaped: lower.replace(/"/g, '\\"')
  };
};
const styles$u = {};
const messageSearchText = (resolved) => {
  const texts = [];
  texts.push(...extractContentText$1(resolved.message.content));
  if (resolved.message.role === "assistant" && "tool_calls" in resolved.message && resolved.message.tool_calls) {
    for (const toolCall of resolved.message.tool_calls) {
      if (toolCall.function) {
        texts.push(toolCall.function);
      }
      if (toolCall.arguments) {
        texts.push(JSON.stringify(toolCall.arguments));
      }
    }
  }
  for (const toolMsg of resolved.toolMessages) {
    if (toolMsg.function) {
      texts.push(toolMsg.function);
    }
    texts.push(...extractContentText$1(toolMsg.content));
    if (toolMsg.error?.message) {
      texts.push(toolMsg.error.message);
    }
  }
  return texts;
};
const extractContentText$1 = (content) => {
  if (typeof content === "string") {
    return [content];
  }
  const texts = [];
  for (const item of content) {
    switch (item.type) {
      case "text":
        texts.push(item.text);
        break;
      case "reasoning": {
        const reasoning = item;
        if (reasoning.reasoning) {
          texts.push(reasoning.reasoning);
        } else if (reasoning.summary) {
          texts.push(reasoning.summary);
        }
        break;
      }
      case "tool_use": {
        const toolUse = item;
        if (toolUse.name) {
          texts.push(toolUse.name);
        }
        if (toolUse.arguments) {
          texts.push(JSON.stringify(toolUse.arguments));
        }
        break;
      }
    }
  }
  return texts;
};
const ChatViewVirtualList = reactExports.memo(
  ({
    id,
    messages: messages2,
    initialMessageId,
    topOffset,
    className,
    toolCallStyle,
    indented,
    numbered = true,
    scrollRef,
    running,
    allowLinking = true
  }) => {
    const useVirtuoso = running || messages2.length > 200;
    const listHandle = reactExports.useRef(null);
    const setNativeFind = useStore((state) => state.appActions.setNativeFind);
    reactExports.useEffect(() => {
      setNativeFind(!useVirtuoso);
    }, [setNativeFind, useVirtuoso]);
    reactExports.useEffect(() => {
      const handleKeyDown = (event) => {
        if (event.metaKey || event.ctrlKey) {
          if (event.key === "ArrowUp") {
            if (useVirtuoso) {
              listHandle.current?.scrollToIndex({ index: 0, align: "center" });
            } else {
              scrollRef?.current?.scrollTo({ top: 0, behavior: "instant" });
            }
            event.preventDefault();
          } else if (event.key === "ArrowDown") {
            if (useVirtuoso) {
              listHandle.current?.scrollToIndex({
                index: Math.min(messages2.length - 5, 0),
                align: "center"
              });
              setTimeout(() => {
                listHandle.current?.scrollToIndex({
                  index: messages2.length - 1,
                  align: "end"
                });
              }, 250);
            } else {
              scrollRef?.current?.scrollTo({
                top: scrollRef.current.scrollHeight,
                behavior: "instant"
              });
            }
            event.preventDefault();
          }
        }
      };
      const scrollElement = scrollRef?.current;
      if (scrollElement) {
        scrollElement.addEventListener("keydown", handleKeyDown);
        if (!scrollElement.hasAttribute("tabIndex")) {
          scrollElement.setAttribute("tabIndex", "0");
        }
        return () => {
          scrollElement.removeEventListener("keydown", handleKeyDown);
        };
      }
    }, [scrollRef, messages2, useVirtuoso]);
    if (!useVirtuoso) {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(
        ChatView,
        {
          id,
          messages: messages2,
          allowLinking,
          indented,
          numbered,
          toolCallStyle,
          className
        }
      );
    } else {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(
        ChatViewVirtualListComponent,
        {
          id,
          listHandle,
          className,
          scrollRef,
          messages: messages2,
          initialMessageId,
          topOffset,
          toolCallStyle,
          indented,
          numbered,
          running,
          allowLinking
        }
      );
    }
  }
);
const ChatViewVirtualListComponent = reactExports.memo(
  ({
    id,
    listHandle,
    messages: messages2,
    initialMessageId,
    topOffset,
    className,
    toolCallStyle,
    indented,
    numbered = true,
    scrollRef,
    running,
    allowLinking = true
  }) => {
    const collapsedMessages = reactExports.useMemo(() => {
      return resolveMessages(messages2);
    }, [messages2]);
    const initialMessageIndex = reactExports.useMemo(() => {
      if (initialMessageId === null || initialMessageId === void 0) {
        return void 0;
      }
      const index = collapsedMessages.findIndex((message2) => {
        const messageId = message2.message.id === initialMessageId;
        if (messageId) {
          return true;
        }
        if (message2.toolMessages.find((tm) => tm.id === initialMessageId)) {
          return true;
        }
      });
      return index !== -1 ? index : void 0;
    }, [initialMessageId, collapsedMessages]);
    const renderRow = reactExports.useCallback(
      (index, item) => {
        const number = collapsedMessages.length > 1 && numbered ? index + 1 : void 0;
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          ChatMessageRow,
          {
            parentName: id || "chat-virtual-list",
            number,
            resolvedMessage: item,
            indented,
            toolCallStyle,
            highlightUserMessage: true,
            allowLinking
          }
        );
      },
      [
        collapsedMessages.length,
        numbered,
        id,
        indented,
        toolCallStyle,
        allowLinking
      ]
    );
    const Item = ({
      children,
      ...props
    }) => {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(
        "div",
        {
          className: clsx(styles$u.item),
          "data-index": props["data-index"],
          "data-item-group-index": props["data-item-group-index"],
          "data-item-index": props["data-item-index"],
          "data-known-size": props["data-known-size"],
          style: props.style,
          children
        }
      );
    };
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      LiveVirtualList,
      {
        id: "chat-virtual-list",
        listHandle,
        className,
        scrollRef,
        data: collapsedMessages,
        renderRow,
        initialTopMostItemIndex: initialMessageIndex,
        offsetTop: topOffset,
        live: running,
        showProgress: running,
        components: { Item },
        itemSearchText: messageSearchText
      }
    );
  }
);
const tabPanel = "_tabPanel_6o9gh_1";
const tabControls = "_tabControls_6o9gh_5";
const fullWidth$1 = "_fullWidth_6o9gh_12";
const padded = "_padded_6o9gh_25";
const error$1 = "_error_6o9gh_30";
const ansi = "_ansi_6o9gh_34";
const noTop = "_noTop_6o9gh_38";
const chat = "_chat_6o9gh_50";
const transcriptContainer = "_transcriptContainer_6o9gh_58";
const styles$t = {
  tabPanel,
  tabControls,
  fullWidth: fullWidth$1,
  padded,
  error: error$1,
  ansi,
  noTop,
  chat,
  transcriptContainer
};
function truncateMarkdown(markdown, maxLength = 250, ellipsis = "...") {
  if (!markdown || markdown.length <= maxLength) {
    return markdown;
  }
  if (markdown.trim().length === 0) {
    return markdown.slice(0, maxLength);
  }
  if (ellipsis.length >= maxLength) {
    return markdown.slice(0, maxLength);
  }
  if (!hasMarkdownSyntax(markdown)) {
    return simpleMarkdownTruncate(markdown, maxLength, ellipsis);
  }
  const md = new MarkdownIt({
    html: true,
    breaks: true
  });
  const tokens = md.parse(markdown, {});
  let accumulated = "";
  let lastSafePoint = "";
  let isTruncated = false;
  for (const token of tokens) {
    const tokenContent = getTokenContent(token);
    const potentialLength = accumulated.length + tokenContent.length;
    if (potentialLength > maxLength - ellipsis.length) {
      const remainingSpace = maxLength - ellipsis.length - accumulated.length;
      if (remainingSpace > 0 && tokenContent.length > 0) {
        const truncatedToken = truncateAtWordBoundary(
          tokenContent,
          remainingSpace
        );
        if (truncatedToken.length > 0) {
          accumulated += truncatedToken;
        }
      }
      isTruncated = true;
      break;
    }
    accumulated += tokenContent;
    if (isCompleteSyntax(token)) {
      lastSafePoint = accumulated;
    }
  }
  const finalText = lastSafePoint.length > maxLength * 0.5 ? lastSafePoint : accumulated;
  if (isTruncated && finalText.length > 0) {
    return finalText.trimEnd() + ellipsis;
  }
  return finalText;
}
function hasMarkdownSyntax(text) {
  const markdownPatterns = [
    /\[.*?\]\(.*?\)/,
    // Links
    /!\[.*?\]\(.*?\)/,
    // Images
    /`[^`]+`/,
    // Inline code
    /```[\s\S]*?```/,
    // Code blocks
    /\*{1,2}[^*]+\*{1,2}/,
    // Bold/italic
    /_{1,2}[^_]+_{1,2}/,
    // Bold/italic
    /\$[^$]+\$/,
    // LaTeX
    /^#{1,6}\s/m,
    // Headers
    /^\s*[-*+]\s/m
    // Lists
  ];
  return markdownPatterns.some((pattern) => pattern.test(text));
}
function getTokenContent(token) {
  if (token.type === "inline" && token.children) {
    return token.children.map((child) => {
      if (child.content) return child.content;
      if (child.type === "softbreak") return "\n";
      if (child.type === "hardbreak") return "\n";
      return "";
    }).join("");
  }
  if (token.content) {
    return token.content;
  }
  if (token.type === "code_block" || token.type === "fence") {
    return token.content || "";
  }
  if (token.type === "html_block") {
    return token.content || "";
  }
  if (token.type === "softbreak" || token.type === "hardbreak") {
    return "\n";
  }
  return "";
}
function isCompleteSyntax(token) {
  const completeTypes = [
    "paragraph_close",
    "heading_close",
    "blockquote_close",
    "list_item_close",
    "ordered_list_close",
    "bullet_list_close",
    "code_block",
    "fence",
    "hr",
    "html_block"
  ];
  return completeTypes.includes(token.type);
}
function truncateAtWordBoundary(text, maxLength) {
  if (text.length <= maxLength) {
    return text;
  }
  let lastSpace = -1;
  for (let i = maxLength - 1; i >= 0; i--) {
    if (/\s/.test(text[i])) {
      lastSpace = i;
      break;
    }
  }
  if (lastSpace > 0) {
    return text.slice(0, lastSpace);
  }
  for (let i = maxLength - 1; i >= 0; i--) {
    if (/[.!?,;:\-—]/.test(text[i])) {
      return text.slice(0, i + 1);
    }
  }
  const substr = text.slice(0, maxLength);
  const markdownPatterns = [
    /\[([^\]]*)?$/,
    // Incomplete link
    /!\[([^\]]*)?$/,
    // Incomplete image
    /`[^`]*$/,
    // Incomplete inline code
    /\*{1,2}[^*]*$/,
    // Incomplete bold/italic
    /_{1,2}[^_]*$/,
    // Incomplete bold/italic
    /\$[^$]*$/
    // Incomplete LaTeX
  ];
  for (const pattern of markdownPatterns) {
    const match = substr.match(pattern);
    if (match && match.index) {
      return substr.slice(0, match.index);
    }
  }
  return substr;
}
function simpleMarkdownTruncate(markdown, maxLength = 250, ellipsis = "...") {
  if (!markdown || markdown.length <= maxLength) {
    return markdown;
  }
  const targetLength = maxLength - ellipsis.length;
  const truncated = markdown.slice(0, targetLength);
  const lastSpace = truncated.lastIndexOf(" ");
  if (lastSpace > 0) {
    return truncated.slice(0, lastSpace) + ellipsis;
  }
  return truncated + ellipsis;
}
const kBaseFontSize = 0.9;
const ScaleBaseFont = (scale) => {
  return `${kBaseFontSize + scale}rem`;
};
const FontSize = {
  smaller: ScaleBaseFont(-0.1)
};
const TextStyle = {
  secondary: {
    color: "var(--bs-secondary)"
  }
};
const ApplicationStyles = {
  moreButton: {
    maxHeight: "1.8em",
    fontSize: FontSize.smaller,
    padding: "0 0.2em 0 0.2em",
    ...TextStyle.secondary
  },
  threeLineClamp: {
    display: "-webkit-box",
    WebkitLineClamp: "3",
    WebkitBoxOrient: "vertical",
    overflow: "hidden"
  },
  lineClamp: (len) => {
    return {
      display: "-webkit-box",
      WebkitLineClamp: `${len}`,
      WebkitBoxOrient: "vertical",
      overflow: "hidden"
    };
  },
  wrapText: () => {
    return {
      whiteSpace: "nowrap",
      textOverflow: "ellipsis",
      overflow: "hidden"
    };
  },
  scoreFills: {
    green: {
      backgroundColor: "var(--bs-success)",
      borderColor: "var(--bs-success)",
      color: "var(--bs-body-bg)"
    },
    red: {
      backgroundColor: "var(--bs-danger)",
      borderColor: "var(--bs-danger)",
      color: "var(--bs-body-bg)"
    },
    orange: {
      backgroundColor: "var(--bs-orange)",
      borderColor: "var(--bs-orange)",
      color: "var(--bs-body-bg)"
    }
  }
};
const body = "_body_x9ww7_1";
const safe = "_safe_x9ww7_9";
const iconSmall = "_iconSmall_x9ww7_13";
const message = "_message_x9ww7_19";
const styles$s = {
  body,
  safe,
  iconSmall,
  message
};
const SampleErrorView = ({
  message: message2,
  align
}) => {
  align = align || "center";
  const type = errorType(message2);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(
    "div",
    {
      className: clsx(
        styles$s.body,
        isCanceledError(type) ? styles$s.safe : void 0
      ),
      children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx(ApplicationIcons.error, styles$s.iconSmall) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$s.message, style: ApplicationStyles.lineClamp(2), children: type })
      ]
    }
  );
};
const isCanceledError = (type) => {
  return type === "CancelledError";
};
const target = "_target_10p8e_1";
const answer = "_answer_10p8e_5";
const grid$2 = "_grid_10p8e_9";
const centerLabel = "_centerLabel_10p8e_16";
const centerValue = "_centerValue_10p8e_21";
const wrap$1 = "_wrap_10p8e_26";
const titled = "_titled_10p8e_30";
const value = "_value_10p8e_34";
const invalidationBanner = "_invalidationBanner_10p8e_40";
const invalidationIcon = "_invalidationIcon_10p8e_50";
const invalidationContent = "_invalidationContent_10p8e_56";
const invalidationTitle = "_invalidationTitle_10p8e_63";
const invalidationDetails = "_invalidationDetails_10p8e_68";
const invalidationReason = "_invalidationReason_10p8e_76";
const styles$r = {
  target,
  answer,
  grid: grid$2,
  centerLabel,
  centerValue,
  wrap: wrap$1,
  titled,
  value,
  invalidationBanner,
  invalidationIcon,
  invalidationContent,
  invalidationTitle,
  invalidationDetails,
  invalidationReason
};
const kMaxCellTextLength = 256;
function isEvalSample(sample2) {
  return "store" in sample2;
}
const resolveSample = (sample2, sampleDescriptor) => {
  const input = inputString(sample2.input);
  if (isEvalSample(sample2) && sample2.choices && sample2.choices.length > 0) {
    input.push("");
    input.push(
      ...sample2.choices.map((choice, index) => {
        return `${String.fromCharCode(65 + index)}) ${choice}`;
      })
    );
  }
  const target2 = sample2.target;
  const answer2 = sample2 && sampleDescriptor ? sampleDescriptor.selectedScorerDescriptor(sample2)?.answer() : void 0;
  const limit = isEvalSample(sample2) ? sample2.limit?.type : void 0;
  const working_time = isEvalSample(sample2) ? sample2.working_time : void 0;
  const total_time = isEvalSample(sample2) ? sample2.total_time : void 0;
  const error2 = isEvalSample(sample2) ? sample2.error?.message : void 0;
  const retries = isEvalSample(sample2) ? sample2.error_retries?.length : sample2.retries;
  return {
    id: sample2.id,
    input,
    target: target2,
    answer: answer2,
    limit,
    retries,
    working_time,
    total_time,
    error: error2
  };
};
const SampleSummaryView = ({
  parent_id,
  sample: sample2
}) => {
  const sampleDescriptor = useSampleDescriptor();
  const selectedScores = useSelectedScores();
  if (!sampleDescriptor) {
    return void 0;
  }
  const fields = resolveSample(sample2, sampleDescriptor);
  const shape = sampleDescriptor?.messageShape;
  const limitSize = shape?.limitSize ?? 0;
  const retrySize = shape?.retriesSize ?? 0;
  const idSize = shape?.idSize ?? 2;
  const columns = [];
  columns.push({
    label: "Id",
    value: fields.id,
    size: `${idSize}em`
  });
  columns.push({
    label: "Input",
    value: /* @__PURE__ */ jsxRuntimeExports.jsx(
      RenderedText,
      {
        markdown: truncateMarkdown(fields.input.join(" "), kMaxCellTextLength)
      }
    ),
    size: `minmax(auto, 5fr)`
  });
  if (fields.target) {
    columns.push({
      label: "Target",
      value: /* @__PURE__ */ jsxRuntimeExports.jsx(
        RenderedText,
        {
          markdown: truncateMarkdown(
            arrayToString(fields?.target || "none"),
            kMaxCellTextLength
          ),
          className: clsx("no-last-para-padding", styles$r.target)
        }
      ),
      size: `minmax(auto, 3fr)`,
      clamp: true
    });
  }
  if (fields.answer) {
    columns.push({
      label: "Answer",
      value: sample2 ? /* @__PURE__ */ jsxRuntimeExports.jsx(
        RenderedText,
        {
          markdown: truncateMarkdown(fields.answer || "", kMaxCellTextLength),
          className: clsx("no-last-para-padding", styles$r.answer)
        }
      ) : "",
      size: `minmax(auto, 5fr)`,
      clamp: true
    });
  }
  const toolTip = (working_time) => {
    if (working_time === void 0 || working_time === null) {
      return void 0;
    }
    return `Working time: ${formatTime(working_time)}`;
  };
  if (fields.total_time) {
    columns.push({
      label: "Time",
      value: formatTime(fields.total_time),
      size: `fit-content(10rem)`,
      center: true,
      title: toolTip(fields.working_time)
    });
  }
  if (fields?.limit && limitSize > 0) {
    columns.push({
      label: "Limit",
      value: fields.limit,
      size: `${limitSize}em`,
      center: true
    });
  }
  if (fields?.retries && retrySize > 0) {
    columns.push({
      label: "Retries",
      value: fields.retries,
      size: `${retrySize}em`,
      center: true
    });
  }
  if (selectedScores && selectedScores.length > 0) {
    const scoreColumns = selectedScores.map((scoreLabel) => ({
      label: selectedScores.length === 1 ? "Score" : scoreLabel.name,
      value: sampleDescriptor?.evalDescriptor.score(sample2, scoreLabel)?.render() || "",
      size: "fit-content(15em)",
      center: true
    })).filter((col) => col.value !== "");
    columns.push(...scoreColumns);
  }
  if (fields.error) {
    columns.push({
      label: "Error",
      value: /* @__PURE__ */ jsxRuntimeExports.jsx(SampleErrorView, { message: fields.error }),
      size: `${shape?.errorSize ?? 1}em`,
      center: true
    });
  }
  const invalidation = isEvalSample(sample2) ? sample2.invalidation : void 0;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { id: `sample-heading-${parent_id}`, children: [
    invalidation && /* @__PURE__ */ jsxRuntimeExports.jsx(InvalidationBanner, { invalidation }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        className: clsx(styles$r.grid, "text-size-base"),
        style: {
          gridTemplateColumns: `${columns.map((col) => {
            return col.size;
          }).join(" ")}`
        },
        children: [
          columns.map((col, idx) => {
            return /* @__PURE__ */ jsxRuntimeExports.jsx(
              "div",
              {
                className: clsx(
                  "text-style-label",
                  "text-style-secondary",
                  "text-size-smallest",
                  col.title ? styles$r.titled : void 0,
                  col.center ? styles$r.centerLabel : void 0
                ),
                title: col.title,
                "data-unsearchable": true,
                children: col.label
              },
              `sample-summ-lbl-${idx}`
            );
          }),
          columns.map((col, idx) => {
            return /* @__PURE__ */ jsxRuntimeExports.jsx(
              "div",
              {
                className: clsx(
                  styles$r.value,
                  styles$r.wrap,
                  col.clamp ? "three-line-clamp" : void 0,
                  col.center ? styles$r.centerValue : void 0
                ),
                "data-unsearchable": true,
                children: col.value
              },
              `sample-summ-val-${idx}`
            );
          })
        ]
      }
    )
  ] });
};
const InvalidationBanner = ({
  invalidation
}) => {
  const formatTimestamp = (timestamp) => {
    try {
      return formatDateTime(new Date(timestamp));
    } catch {
      return timestamp;
    }
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$r.invalidationBanner, children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$r.invalidationIcon, children: "⚠" }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$r.invalidationContent, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$r.invalidationTitle, children: "Sample Invalidated" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$r.invalidationDetails, children: [
        invalidation.author && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
          "By: ",
          invalidation.author
        ] }),
        invalidation.timestamp && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
          "On: ",
          formatTimestamp(invalidation.timestamp)
        ] }),
        invalidation.reason && /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: styles$r.invalidationReason, children: [
          "Reason: ",
          invalidation.reason
        ] })
      ] })
    ] })
  ] });
};
const EmptyPanel = ({ children }) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "empty-panel", children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "container", children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children }) }) });
};
const SampleScores = ({ sample: sample2, scorer }) => {
  const scoreData = sample2.scores?.[scorer];
  if (!scoreData) {
    return void 0;
  }
  const scorerDescriptor = getScoreDescriptorForValues(
    [scoreData.value],
    [typeof scoreData.value]
  );
  return scorerDescriptor?.render(scoreData.value);
};
const container$5 = "_container_kwhbh_1";
const cell = "_cell_kwhbh_9";
const fullWidth = "_fullWidth_kwhbh_13";
const separator$3 = "_separator_kwhbh_25";
const separatorPadded = "_separatorPadded_kwhbh_30";
const headerSep = "_headerSep_kwhbh_35";
const styles$q = {
  container: container$5,
  cell,
  fullWidth,
  separator: separator$3,
  separatorPadded,
  headerSep
};
const SampleScoresGrid = ({
  evalSample,
  className,
  scrollRef
}) => {
  const evalDescriptor = useEvalDescriptor();
  if (!evalDescriptor) {
    return /* @__PURE__ */ jsxRuntimeExports.jsx(EmptyPanel, { children: "No Sample Selected" });
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(className, styles$q.container), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        className: clsx(
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary"
        ),
        children: "Scorer"
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        className: clsx(
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary"
        ),
        children: "Answer"
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        className: clsx(
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary"
        ),
        children: "Score"
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        className: clsx(
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary"
        ),
        children: "Explanation"
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      "div",
      {
        className: clsx(styles$q.separator, styles$q.fullWidth, styles$q.headerSep)
      }
    ),
    Object.keys(evalSample.scores || {}).map((scorer) => {
      if (!evalSample.scores) {
        return void 0;
      }
      const scoreData = evalSample.scores[scorer];
      const explanation2 = scoreData.explanation || "(No Explanation)";
      const answer2 = scoreData.answer;
      let metadata2 = scoreData.metadata || {};
      return /* @__PURE__ */ jsxRuntimeExports.jsxs(reactExports.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-size-base", styles$q.cell), children: scorer }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$q.cell, "text-size-base"), children: answer2 }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$q.cell, "text-size-base"), children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          SampleScores,
          {
            sample: evalSample,
            scorer
          }
        ) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-size-base", styles$q.cell), children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          RenderedContent,
          {
            id: `${scorer}-explanation`,
            entry: {
              name: "Explanation",
              value: explanation2
            }
          }
        ) }),
        Object.keys(metadata2).length > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs(reactExports.Fragment, { children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "div",
            {
              className: clsx(
                "text-size-smaller",
                "text-style-label",
                "text-style-secondary",
                styles$q.fullWidth
              ),
              children: "Metadata"
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$q.fullWidth), children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            RecordTree,
            {
              id: `${scorer}-metadataa`,
              scrollRef,
              record: metadata2,
              defaultExpandLevel: 0
            }
          ) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "div",
            {
              className: clsx(
                styles$q.separator,
                styles$q.separatorPadded,
                styles$q.fullWidth
              )
            }
          )
        ] }, `${scorer}-metadata`) : void 0
      ] }, `${scorer}-row`);
    })
  ] });
};
const wordBreak = "_wordBreak_las07_9";
const scoreCard = "_scoreCard_las07_50";
const scores = "_scores_las07_54";
const styles$p = {
  wordBreak,
  scoreCard,
  scores
};
const SampleScoresView = ({
  sample: sample2,
  className,
  scrollRef
}) => {
  const evalDescriptor = useEvalDescriptor();
  if (!evalDescriptor) {
    return void 0;
  }
  if (!sample2) {
    return void 0;
  }
  const scoreInput = inputString(sample2.input);
  if (sample2.choices && sample2.choices.length > 0) {
    scoreInput.push("");
    scoreInput.push(
      ...sample2.choices.map((choice, index) => {
        return `${String.fromCharCode(65 + index)}) ${choice}`;
      })
    );
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    "div",
    {
      className: clsx(
        "container-fluid",
        className,
        "font-size-base",
        styles$p.container
      ),
      children: /* @__PURE__ */ jsxRuntimeExports.jsx(Card, { className: clsx(styles$p.scoreCard), children: /* @__PURE__ */ jsxRuntimeExports.jsxs(CardBody, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            className: clsx(
              "text-size-small",
              "text-style-label",
              "text-style-secondary"
            ),
            children: "Input"
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          ExpandablePanel,
          {
            lines: 10,
            id: `sample-score-${sample2.id}-${sample2.epoch}`,
            collapse: true,
            children: /* @__PURE__ */ jsxRuntimeExports.jsx(
              RenderedText,
              {
                markdown: scoreInput.join("\n"),
                className: clsx(styles$p.wordBreak, "text-size-base")
              }
            )
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          SampleScoresGrid,
          {
            evalSample: sample2,
            className: clsx(styles$p.scores),
            scrollRef
          }
        )
      ] }) })
    }
  );
};
const eventTypes = {
  sample_init: "Sample Init",
  sample_limit: "Sample Limit",
  sandbox: "Sandbox",
  state: "State",
  store: "Store",
  model: "Model",
  tool: "Tool",
  approval: "Approval",
  input: "Input",
  score: "Score",
  score_edit: "Score Edit",
  error: "Error",
  logger: "Logger",
  compaction: "Compaction",
  info: "Info",
  subtask: "Subtask"
};
const useTranscriptFilter = () => {
  const filtered = useStore((state) => state.sample.eventFilter.filteredTypes);
  const setFilteredEventTypes = useStore(
    (state) => state.sampleActions.setFilteredEventTypes
  );
  const filterEventType = reactExports.useCallback(
    (type, isFiltered) => {
      const newFiltered = new Set(filtered);
      if (isFiltered) {
        newFiltered.delete(type);
      } else {
        newFiltered.add(type);
      }
      setFilteredEventTypes(Array.from(newFiltered));
    },
    [filtered, setFilteredEventTypes]
  );
  const setDebugFilter = reactExports.useCallback(() => {
    setFilteredEventTypes([]);
  }, [setFilteredEventTypes]);
  const setDefaultFilter = reactExports.useCallback(() => {
    setFilteredEventTypes([...kDefaultExcludeEvents]);
  }, [setFilteredEventTypes]);
  const isDefaultFilter = reactExports.useMemo(() => {
    return filtered.length === kDefaultExcludeEvents.length && [...filtered].every((type) => kDefaultExcludeEvents.includes(type));
  }, [filtered]);
  const isDebugFilter = reactExports.useMemo(() => {
    return filtered.length === 0;
  }, [filtered]);
  const arrangedEventTypes = reactExports.useCallback((columns = 1) => {
    const keys = Object.keys(eventTypes);
    const sortedKeys = keys.sort((a, b) => {
      const aIsDefault = kDefaultExcludeEvents.includes(a);
      const bIsDefault = kDefaultExcludeEvents.includes(b);
      if (aIsDefault && !bIsDefault) return 1;
      if (!aIsDefault && bIsDefault) return -1;
      return eventTypes[a].localeCompare(eventTypes[b]);
    });
    if (columns === 1) {
      return sortedKeys;
    }
    const itemsPerColumn = Math.ceil(sortedKeys.length / columns);
    const columnArrays = [];
    for (let col = 0; col < columns; col++) {
      const start = col * itemsPerColumn;
      const end = Math.min(start + itemsPerColumn, sortedKeys.length);
      columnArrays.push(sortedKeys.slice(start, end));
    }
    const arrangedKeys = [];
    const maxItemsInColumn = Math.max(...columnArrays.map((col) => col.length));
    for (let row2 = 0; row2 < maxItemsInColumn; row2++) {
      for (let col = 0; col < columns; col++) {
        if (row2 < columnArrays[col].length) {
          arrangedKeys.push(columnArrays[col][row2]);
        }
      }
    }
    return arrangedKeys;
  }, []);
  return {
    filtered,
    isDefaultFilter,
    isDebugFilter,
    setDefaultFilter,
    setDebugFilter,
    filterEventType,
    eventTypes,
    arrangedEventTypes
  };
};
const grid$1 = "_grid_1ml4j_1";
const row = "_row_1ml4j_8";
const links = "_links_1ml4j_22";
const selected$1 = "_selected_1ml4j_40";
const styles$o = {
  grid: grid$1,
  row,
  links,
  selected: selected$1
};
const TranscriptFilterPopover = ({
  showing,
  positionEl,
  setShowing
}) => {
  const {
    isDefaultFilter,
    isDebugFilter,
    setDefaultFilter,
    setDebugFilter,
    filterEventType,
    eventTypes: eventTypes2,
    filtered,
    arrangedEventTypes
  } = useTranscriptFilter();
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(
    PopOver,
    {
      id: `transcript-filter-popover`,
      positionEl,
      isOpen: showing,
      setIsOpen: setShowing,
      placement: "bottom-end",
      hoverDelay: -1,
      children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$o.links, "text-size-smaller"), children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "a",
            {
              className: clsx(
                styles$o.link,
                isDefaultFilter ? styles$o.selected : void 0
              ),
              onClick: () => setDefaultFilter(),
              children: "Default"
            }
          ),
          "|",
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "a",
            {
              className: clsx(
                styles$o.link,
                isDebugFilter ? styles$o.selected : void 0
              ),
              onClick: () => setDebugFilter(),
              children: "Debug"
            }
          )
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$o.grid, "text-size-smaller"), children: arrangedEventTypes(2).map((eventType) => {
          return /* @__PURE__ */ jsxRuntimeExports.jsxs(
            "div",
            {
              className: clsx(styles$o.row),
              onClick: () => {
                filterEventType(eventType, filtered.includes(eventType));
              },
              children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx(
                  "input",
                  {
                    type: "checkbox",
                    checked: !filtered.includes(eventType),
                    onChange: (e) => {
                      filterEventType(eventType, e.target.checked);
                    }
                  }
                ),
                eventTypes2[eventType]
              ]
            },
            eventType
          );
        }) })
      ]
    }
  );
};
const StickyScroll = ({
  children,
  scrollRef,
  offsetTop = 0,
  zIndex = 100,
  className = "",
  stickyClassName = "is-sticky",
  onStickyChange
}) => {
  const wrapperRef = reactExports.useRef(null);
  const contentRef = reactExports.useRef(null);
  const [isSticky, setIsSticky] = reactExports.useState(false);
  const [dimensions, setDimensions] = reactExports.useState({
    width: 0,
    height: 0,
    left: 0,
    stickyTop: 0
    // Store the position where the element should stick
  });
  reactExports.useEffect(() => {
    const wrapper2 = wrapperRef.current;
    const content = contentRef.current;
    const scrollContainer = scrollRef.current;
    if (!wrapper2 || !content || !scrollContainer) {
      return;
    }
    const sentinel = document.createElement("div");
    sentinel.style.position = "absolute";
    sentinel.style.top = "0px";
    sentinel.style.left = "0";
    sentinel.style.width = "1px";
    sentinel.style.height = "1px";
    sentinel.style.pointerEvents = "none";
    wrapper2.prepend(sentinel);
    const widthTracker = document.createElement("div");
    widthTracker.style.position = "absolute";
    widthTracker.style.top = "0";
    widthTracker.style.left = "0";
    widthTracker.style.width = "100%";
    widthTracker.style.height = "0";
    widthTracker.style.pointerEvents = "none";
    widthTracker.style.visibility = "hidden";
    wrapper2.prepend(widthTracker);
    const updateDimensions = () => {
      if (wrapper2 && scrollContainer) {
        const contentRect = content.getBoundingClientRect();
        const containerRect = scrollContainer.getBoundingClientRect();
        const trackerRect = widthTracker.getBoundingClientRect();
        const stickyTop = containerRect.top + offsetTop;
        setDimensions({
          // Use the width tracker to get the right width that respects
          // the parent container's current width, rather than the content's width
          width: trackerRect.width,
          height: contentRect.height,
          left: trackerRect.left,
          stickyTop
        });
      }
    };
    updateDimensions();
    const resizeObserver = new ResizeObserver(() => {
      requestAnimationFrame(() => {
        updateDimensions();
        if (isSticky) {
          handleScroll();
        }
      });
    });
    resizeObserver.observe(wrapper2);
    resizeObserver.observe(scrollContainer);
    resizeObserver.observe(content);
    const handleScroll = () => {
      const sentinelRect = sentinel.getBoundingClientRect();
      const containerRect = scrollContainer.getBoundingClientRect();
      const shouldBeSticky = sentinelRect.top < containerRect.top + offsetTop;
      if (shouldBeSticky !== isSticky) {
        updateDimensions();
        setIsSticky(shouldBeSticky);
        if (onStickyChange) {
          onStickyChange(shouldBeSticky);
        }
      }
    };
    scrollContainer.addEventListener("scroll", handleScroll);
    handleScroll();
    return () => {
      resizeObserver.disconnect();
      scrollContainer.removeEventListener("scroll", handleScroll);
      if (sentinel.parentNode) {
        sentinel.parentNode.removeChild(sentinel);
      }
      if (widthTracker.parentNode) {
        widthTracker.parentNode.removeChild(widthTracker);
      }
    };
  }, [scrollRef, offsetTop, onStickyChange, isSticky]);
  const wrapperStyle = {
    position: "relative",
    height: isSticky ? `${dimensions.height}px` : "auto"
    // Don't constrain width - let it flow naturally with the content
  };
  const contentStyle = isSticky ? {
    position: "fixed",
    top: `${dimensions.stickyTop}px`,
    left: `${dimensions.left}px`,
    width: `${dimensions.width}px`,
    // Keep explicit width to prevent expanding to 100%
    maxHeight: `calc(100vh - ${dimensions.stickyTop}px)`,
    zIndex
  } : {};
  const contentClassName = isSticky && stickyClassName ? `${className} ${stickyClassName}`.trim() : className;
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { ref: wrapperRef, style: wrapperStyle, children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { ref: contentRef, className: contentClassName, style: contentStyle, children }) });
};
const STEP = "step";
const ACTION_BEGIN = "begin";
const SPAN_BEGIN = "span_begin";
const SPAN_END = "span_end";
const TOOL = "tool";
const STORE = "store";
const STATE = "state";
const TYPE_TOOL = "tool";
const TYPE_SUBTASK = "subtask";
const TYPE_SOLVER = "solver";
const TYPE_SOLVERS = "solvers";
const TYPE_AGENT = "agent";
const TYPE_HANDOFF = "handoff";
const TYPE_SCORERS = "scorers";
const TYPE_SCORER = "scorer";
const hasSpans = (events) => {
  return events.some((event) => event.event === SPAN_BEGIN);
};
const kTranscriptCollapseScope = "transcript-collapse";
const kTranscriptOutlineCollapseScope = "transcript-outline";
const kCollapsibleEventTypes = [
  STEP,
  SPAN_BEGIN,
  TYPE_TOOL,
  TYPE_SUBTASK
];
class EventNode {
  id;
  event;
  children = [];
  depth;
  constructor(id, event, depth) {
    this.id = id;
    this.event = event;
    this.depth = depth;
  }
}
const flatTree = (eventNodes, collapsed2, visitors, parentNode) => {
  const result2 = [];
  for (const node2 of eventNodes) {
    if (visitors && visitors.length > 0) {
      let pendingNodes = [{ ...node2 }];
      for (const visitor of visitors) {
        const allResults = [];
        for (const pendingNode of pendingNodes) {
          const visitorResult = visitor.visit(pendingNode);
          if (parentNode) {
            parentNode.children = visitorResult;
          }
          allResults.push(...visitorResult);
        }
        pendingNodes = allResults;
      }
      for (const pendingNode of pendingNodes) {
        const children = flatTree(
          pendingNode.children,
          collapsed2,
          visitors,
          pendingNode
        );
        pendingNode.children = children;
        result2.push(pendingNode);
        if (collapsed2 === null || collapsed2[pendingNode.id] !== true) {
          result2.push(...children);
        }
      }
      for (const visitor of visitors) {
        if (visitor.flush) {
          const finalNodes = visitor.flush();
          result2.push(...finalNodes);
        }
      }
    } else {
      result2.push(node2);
      const children = flatTree(node2.children, collapsed2, visitors, node2);
      if (collapsed2 === null || collapsed2[node2.id] !== true) {
        result2.push(...children);
      }
    }
  }
  return result2;
};
const parsePackageName = (name) => {
  if (name.includes("/")) {
    const [packageName, moduleName] = name.split("/", 2);
    return { package: packageName, module: moduleName };
  }
  return { package: "", module: name };
};
const kSandboxSignalName = "53787D8A-D3FC-426D-B383-9F880B70E4AA";
const fixupEventStream = (events, filterPending = true) => {
  const collapsed2 = processPendingEvents(events, filterPending);
  const fixedUp = collapseSampleInit(collapsed2);
  return groupSandboxEvents(fixedUp);
};
const processPendingEvents = (events, filter) => {
  return filter ? events.filter((e) => !e.pending) : events.reduce((acc, event) => {
    if (!event.pending) {
      acc.push(event);
    } else {
      const lastIndex = acc.length - 1;
      if (lastIndex >= 0 && acc[lastIndex].pending && acc[lastIndex].event === event.event) {
        acc[lastIndex] = event;
      } else {
        acc.push(event);
      }
    }
    return acc;
  }, []);
};
const collapseSampleInit = (events) => {
  const hasSpans2 = events.some((e) => {
    return e.event === "span_begin" || e.event === "span_end";
  });
  if (hasSpans2) {
    return events;
  }
  const hasInitStep = events.findIndex((e) => {
    return e.event === "step" && e.name === "init";
  }) !== -1;
  if (hasInitStep) {
    return events;
  }
  const initEventIndex = events.findIndex((e) => {
    return e.event === "sample_init";
  });
  const initEvent = events[initEventIndex];
  if (!initEvent) {
    return events;
  }
  const fixedUp = [...events];
  fixedUp.splice(initEventIndex, 0, {
    timestamp: initEvent.timestamp,
    event: "step",
    action: "begin",
    type: null,
    name: "sample_init",
    pending: false,
    working_start: 0,
    span_id: initEvent.span_id,
    uuid: null,
    metadata: null
  });
  fixedUp.splice(initEventIndex + 2, 0, {
    timestamp: initEvent.timestamp,
    event: "step",
    action: "end",
    type: null,
    name: "sample_init",
    pending: false,
    working_start: 0,
    span_id: initEvent.span_id,
    uuid: null,
    metadata: null
  });
  return fixedUp;
};
const groupSandboxEvents = (events) => {
  const result2 = [];
  const pendingSandboxEvents = [];
  const useSpans = hasSpans(events);
  const pushPendingSandboxEvents = () => {
    const timestamp = pendingSandboxEvents[pendingSandboxEvents.length - 1].timestamp;
    if (useSpans) {
      result2.push(createSpanBegin(kSandboxSignalName, timestamp, null));
    } else {
      result2.push(createStepEvent(kSandboxSignalName, timestamp, "begin"));
    }
    result2.push(...pendingSandboxEvents);
    if (useSpans) {
      result2.push(createSpanEnd(kSandboxSignalName, timestamp));
    } else {
      result2.push(createStepEvent(kSandboxSignalName, timestamp, "end"));
    }
    pendingSandboxEvents.length = 0;
  };
  for (const event of events) {
    if (event.event === "sandbox") {
      pendingSandboxEvents.push(event);
      continue;
    }
    if (pendingSandboxEvents.length > 0) {
      pushPendingSandboxEvents();
    }
    result2.push(event);
  }
  if (pendingSandboxEvents.length > 0) {
    pushPendingSandboxEvents();
  }
  return result2;
};
const createStepEvent = (name, timestamp, action) => ({
  timestamp,
  event: "step",
  action,
  type: null,
  name,
  pending: false,
  working_start: 0,
  span_id: null,
  uuid: null,
  metadata: null
});
const createSpanBegin = (name, timestamp, parent_id) => {
  return {
    name,
    id: `${name}-begin`,
    span_id: name,
    parent_id,
    timestamp,
    event: "span_begin",
    type: null,
    pending: false,
    working_start: 0,
    uuid: null,
    metadata: null
  };
};
const createSpanEnd = (name, timestamp) => {
  return {
    id: `${name}-end`,
    timestamp,
    event: "span_end",
    pending: false,
    working_start: 0,
    span_id: name,
    uuid: null,
    metadata: null
  };
};
const eventRow = "_eventRow_1j0jk_1";
const selected = "_selected_1j0jk_8";
const toggle = "_toggle_1j0jk_12";
const eventLink = "_eventLink_1j0jk_17";
const label$1 = "_label_1j0jk_28";
const icon = "_icon_1j0jk_34";
const progress$2 = "_progress_1j0jk_38";
const popover = "_popover_1j0jk_42";
const styles$n = {
  eventRow,
  selected,
  toggle,
  eventLink,
  label: label$1,
  icon,
  progress: progress$2,
  popover
};
const OutlineRow = ({
  node: node2,
  collapseScope,
  running,
  selected: selected2
}) => {
  const [collapsed2, setCollapsed] = useCollapseSampleEvent(
    collapseScope,
    node2.id
  );
  const icon2 = iconForNode(node2);
  const toggle2 = toggleIcon(node2, collapsed2);
  const popoverId = `${node2.id}-popover`;
  const { isShowing, setShowing } = useSamplePopover(popoverId);
  const ref = reactExports.useRef(null);
  const sampleEventUrl = useSampleEventUrl(node2.id);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        className: clsx(
          styles$n.eventRow,
          "text-size-smaller",
          selected2 ? styles$n.selected : ""
        ),
        style: { paddingLeft: `${node2.depth * 0.4}em` },
        "data-unsearchable": true,
        children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "div",
            {
              className: clsx(styles$n.toggle),
              onClick: () => {
                setCollapsed(!collapsed2);
              },
              children: toggle2 ? /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx(toggle2) }) : void 0
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$n.label), "data-depth": node2.depth, children: [
            icon2 ? /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx(icon2, styles$n.icon) }) : void 0,
            sampleEventUrl ? /* @__PURE__ */ jsxRuntimeExports.jsx(
              Link,
              {
                to: sampleEventUrl,
                className: clsx(styles$n.eventLink),
                ref,
                children: parsePackageName(labelForNode(node2)).module
              }
            ) : /* @__PURE__ */ jsxRuntimeExports.jsx("span", { ref, children: parsePackageName(labelForNode(node2)).module }),
            running ? /* @__PURE__ */ jsxRuntimeExports.jsx(
              PulsingDots,
              {
                size: "small",
                className: clsx(styles$n.progress),
                subtle: false
              }
            ) : void 0
          ] })
        ]
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      PopOver,
      {
        id: `${node2.id}-popover`,
        positionEl: ref.current,
        isOpen: isShowing,
        setIsOpen: setShowing,
        className: clsx(styles$n.popper),
        placement: "auto-end",
        children: summarizeNode(node2)
      }
    )
  ] });
};
const toggleIcon = (node2, collapsed2) => {
  if (node2.children.length > 0) {
    return collapsed2 ? ApplicationIcons.chevron.right : ApplicationIcons.chevron.down;
  }
};
const iconForNode = (node2) => {
  switch (node2.event.event) {
    case "sample_limit":
      return ApplicationIcons.limits.custom;
    case "score":
      return ApplicationIcons.scorer;
    case "error":
      return ApplicationIcons.error;
  }
};
const labelForNode = (node2) => {
  if (node2.event.event === "span_begin") {
    switch (node2.event.type) {
      case "solver":
        return node2.event.name;
      case "tool":
        return node2.event.name;
      default: {
        if (node2.event.name === kSandboxSignalName) {
          return "sandbox events";
        }
        return node2.event.name;
      }
    }
  } else {
    switch (node2.event.event) {
      case "subtask":
        return node2.event.name;
      case "approval":
        switch (node2.event.decision) {
          case "approve":
            return "approved";
          case "reject":
            return "rejected";
          case "escalate":
            return "escalated";
          case "modify":
            return "modified";
          case "terminate":
            return "terminated";
          default:
            return node2.event.decision;
        }
      case "model":
        return `model${node2.event.role ? ` (${node2.event.role})` : ""}`;
      case "score":
        return "scoring";
      case "step":
        if (node2.event.name === kSandboxSignalName) {
          return "sandbox events";
        }
        return node2.event.name;
      default:
        return node2.event.event;
    }
  }
};
const summarizeNode = (node2) => {
  let entries = {};
  switch (node2.event.event) {
    case "sample_init":
      entries = {
        sample_id: node2.event.sample.id,
        sandbox: node2.event.sample.sandbox?.type,
        started: formatDateTime(new Date(node2.event.timestamp)),
        working_start: formatTime(node2.event.working_start)
      };
      break;
    case "sample_limit":
      entries = {
        type: node2.event.type,
        message: node2.event.message,
        limit: node2.event.limit,
        started: formatDateTime(new Date(node2.event.timestamp)),
        working_start: formatTime(node2.event.working_start)
      };
      break;
    case "score":
      entries = {
        answer: node2.event.score.answer,
        score: node2.event.score.value,
        started: formatDateTime(new Date(node2.event.timestamp)),
        working_start: formatTime(node2.event.working_start)
      };
      break;
    case "span_begin":
      entries = {
        name: node2.event.name,
        started: formatDateTime(new Date(node2.event.timestamp)),
        working_start: formatTime(node2.event.working_start)
      };
      break;
    default:
      entries = {
        started: formatDateTime(new Date(node2.event.timestamp)),
        working_start: formatTime(node2.event.working_start)
      };
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    MetaDataGrid,
    {
      entries,
      size: "mini",
      className: clsx(styles$n.popover, "text-size-smallest")
    }
  );
};
const styles$m = {};
const kTurnType = "turn";
const kTurnsType = "turns";
const kCollapsedScoring = "scorings";
const removeNodeVisitor = (event) => {
  return {
    visit: (node2) => {
      if (node2.event.event === event) {
        return [];
      }
      return [node2];
    }
  };
};
const removeStepSpanNameVisitor = (name) => {
  return {
    visit: (node2) => {
      if ((node2.event.event === "step" || node2.event.event === "span_begin") && node2.event.name === name) {
        return [];
      }
      return [node2];
    }
  };
};
const noScorerChildren = () => {
  let inScorers = false;
  let inScorer = false;
  let currentDepth = -1;
  return {
    visit: (node2) => {
      if (node2.event.event === "span_begin" && node2.event.type === TYPE_SCORERS) {
        inScorers = true;
        return [node2];
      }
      if ((node2.event.event === "step" || node2.event.event === "span_begin") && node2.event.type === TYPE_SCORER) {
        inScorer = true;
        currentDepth = node2.depth;
        return [node2];
      }
      if (inScorers && inScorer && node2.depth === currentDepth + 1) {
        return [];
      }
      return [node2];
    }
  };
};
const makeTurns = (eventNodes) => {
  const results = [];
  let modelNode = null;
  const toolNodes = [];
  let turnCount = 1;
  const makeTurn = (force) => {
    if (modelNode !== null && (force || toolNodes.length > 0)) {
      const turnNode = new EventNode(
        modelNode.id,
        {
          id: modelNode.id,
          event: "span_begin",
          type: kTurnType,
          name: `turn ${turnCount++}`,
          pending: false,
          working_start: modelNode.event.working_start,
          timestamp: modelNode.event.timestamp,
          parent_id: null,
          span_id: modelNode.event.span_id,
          uuid: null,
          metadata: null
        },
        modelNode.depth
      );
      turnNode.children = [modelNode, ...toolNodes];
      results.push(turnNode);
    }
    modelNode = null;
    toolNodes.length = 0;
  };
  for (const node2 of eventNodes) {
    if (node2.event.event === "model") {
      if (modelNode !== null && toolNodes.length === 0) {
        makeTurn(true);
      } else {
        makeTurn();
        modelNode = node2;
      }
    } else if (node2.event.event === "tool") {
      toolNodes.push(node2);
    } else {
      makeTurn();
      results.push(node2);
    }
  }
  makeTurn();
  return results;
};
const collapseTurns = (eventNodes) => {
  const results = [];
  const collecting = [];
  const collect = () => {
    if (collecting.length > 0) {
      const numberOfTurns = collecting.length;
      const firstTurn = collecting[0];
      const turnNode = new EventNode(
        firstTurn.id,
        {
          ...firstTurn.event,
          name: `${numberOfTurns} ${numberOfTurns === 1 ? "turn" : "turns"}`,
          type: kTurnsType
        },
        firstTurn.depth
      );
      results.push(turnNode);
      collecting.length = 0;
    }
  };
  for (const node2 of eventNodes) {
    if (node2.event.event === "span_begin" && node2.event.type === kTurnType) {
      if (collecting.length > 0 && collecting[0].depth !== node2.depth) {
        collect();
      }
      collecting.push(node2);
    } else {
      collect();
      results.push(node2);
    }
  }
  collect();
  return results;
};
const collapseScoring = (eventNodes) => {
  const results = [];
  const collecting = [];
  const collect = () => {
    if (collecting.length > 0) {
      const firstScore = collecting[0];
      const turnNode = new EventNode(
        firstScore.id,
        {
          ...firstScore.event,
          name: "scoring",
          type: kCollapsedScoring
        },
        firstScore.depth
      );
      results.push(turnNode);
      collecting.length = 0;
    }
  };
  for (const node2 of eventNodes) {
    if (node2.event.event === "score") {
      collecting.push(node2);
    } else {
      collect();
      results.push(node2);
    }
  }
  collect();
  return results;
};
const kFramesToStabilize = 10;
const EventPaddingNode = {
  id: "padding",
  event: {
    event: "info",
    source: "",
    data: "",
    timestamp: "",
    pending: false,
    working_start: 0,
    span_id: null,
    uuid: null,
    metadata: null
  },
  depth: 0,
  children: []
};
const TranscriptOutline = ({
  eventNodes,
  filteredNodes,
  defaultCollapsedIds,
  running,
  className,
  scrollRef,
  style
}) => {
  const id = "transcript-tree";
  const listHandle = reactExports.useRef(null);
  const { getRestoreState } = useVirtuosoState(listHandle, id);
  const collapsedEvents = useStore((state) => state.sample.collapsedEvents);
  const setCollapsedEvents = useStore(
    (state) => state.sampleActions.setCollapsedEvents
  );
  const selectedOutlineId = useStore((state) => state.sample.selectedOutlineId);
  const setSelectedOutlineId = useStore(
    (state) => state.sampleActions.setSelectedOutlineId
  );
  const sampleDetailNavigation = useSampleDetailNavigation();
  const isProgrammaticScrolling = reactExports.useRef(false);
  const lastScrollPosition = reactExports.useRef(null);
  const stableFrameCount = reactExports.useRef(0);
  reactExports.useEffect(() => {
    if (sampleDetailNavigation.event) {
      isProgrammaticScrolling.current = true;
      lastScrollPosition.current = null;
      stableFrameCount.current = 0;
      setSelectedOutlineId(sampleDetailNavigation.event);
      const checkScrollStabilized = () => {
        if (!isProgrammaticScrolling.current) return;
        const currentPosition = scrollRef?.current?.scrollTop ?? null;
        if (currentPosition === lastScrollPosition.current) {
          stableFrameCount.current++;
          if (stableFrameCount.current >= kFramesToStabilize) {
            isProgrammaticScrolling.current = false;
            return;
          }
        } else {
          stableFrameCount.current = 0;
          lastScrollPosition.current = currentPosition;
        }
        requestAnimationFrame(checkScrollStabilized);
      };
      requestAnimationFrame(checkScrollStabilized);
    }
  }, [sampleDetailNavigation.event, setSelectedOutlineId, scrollRef]);
  const outlineNodeList = reactExports.useMemo(() => {
    return collapseScoring(collapseTurns(makeTurns(filteredNodes)));
  }, [filteredNodes]);
  const allNodesList = reactExports.useMemo(() => {
    return flatTree(eventNodes, null);
  }, [eventNodes]);
  const elementIds = allNodesList.map((node2) => node2.id);
  const findNearestOutlineAbove = reactExports.useCallback(
    (targetId) => {
      const targetIndex = allNodesList.findIndex(
        (node2) => node2.id === targetId
      );
      if (targetIndex === -1) return null;
      const outlineIds = new Set(outlineNodeList.map((node2) => node2.id));
      for (let i = targetIndex; i >= 0; i--) {
        if (outlineIds.has(allNodesList[i].id)) {
          return allNodesList[i];
        }
      }
      return null;
    },
    [allNodesList, outlineNodeList]
  );
  useScrollTrack(
    elementIds,
    (id2) => {
      if (!isProgrammaticScrolling.current) {
        const parentNode = findNearestOutlineAbove(id2);
        if (parentNode) {
          setSelectedOutlineId(parentNode.id);
        }
      }
    },
    scrollRef
  );
  reactExports.useEffect(() => {
    if (!collapsedEvents && Object.keys(defaultCollapsedIds).length > 0) {
      setCollapsedEvents(kTranscriptOutlineCollapseScope, defaultCollapsedIds);
    }
  }, [defaultCollapsedIds, collapsedEvents, setCollapsedEvents]);
  const renderRow = reactExports.useCallback(
    (index, node2) => {
      if (node2 === EventPaddingNode) {
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            className: clsx(styles$m.eventPadding),
            style: { height: "2em" }
          },
          node2.id
        );
      } else {
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          OutlineRow,
          {
            collapseScope: kTranscriptOutlineCollapseScope,
            node: node2,
            running: running && index === outlineNodeList.length - 1,
            selected: selectedOutlineId ? selectedOutlineId === node2.id : index === 0
          },
          node2.id
        );
      }
    },
    [outlineNodeList, running, selectedOutlineId]
  );
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    Yr,
    {
      ref: listHandle,
      customScrollParent: scrollRef?.current ? scrollRef.current : void 0,
      id,
      style: { ...style },
      data: [...outlineNodeList, EventPaddingNode],
      defaultItemHeight: 50,
      itemContent: renderRow,
      atBottomThreshold: 30,
      increaseViewportBy: { top: 300, bottom: 300 },
      overscan: {
        main: 10,
        reverse: 10
      },
      className: clsx(className, "transcript-outline"),
      skipAnimationFrameInResizeObserver: true,
      restoreStateFrom: getRestoreState(),
      tabIndex: 0
    }
  );
};
const container$4 = "_container_17sux_1";
const collapsed = "_collapsed_17sux_9";
const treeContainer = "_treeContainer_17sux_13";
const listContainer = "_listContainer_17sux_25";
const outline = "_outline_17sux_29";
const outlineToggle = "_outlineToggle_17sux_33";
const styles$l = {
  container: container$4,
  collapsed,
  treeContainer,
  listContainer,
  outline,
  outlineToggle
};
const title$1 = "_title_19l1b_1";
const contents = "_contents_19l1b_8";
const styles$k = {
  title: title$1,
  contents
};
const EventRow = ({
  title: title2,
  icon: icon2,
  className,
  children
}) => {
  const contentEl = title2 ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx("text-size-small", styles$k.title, className), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: icon2 || ApplicationIcons.metadata }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-style-label"), children: title2 }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children })
  ] }) : "";
  const card2 = /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("card", styles$k.contents), children: contentEl });
  return card2;
};
const sampleLimitTitles = {
  custom: "Custom Limit Exceeded",
  time: "Time Limit Exceeded",
  message: "Message Limit Exceeded",
  token: "Token Limit Exceeded",
  operator: "Operator Canceled",
  working: "Execution Time Limit Exceeded",
  cost: "Cost Limit Exceeded"
};
const approvalDecisionLabels = {
  approve: "Approved",
  reject: "Rejected",
  terminate: "Terminated",
  escalate: "Escalated",
  modify: "Modified"
};
const eventTitle = (event) => {
  switch (event.event) {
    case "model":
      return event.role ? `Model Call (${event.role}): ${event.model}` : `Model Call: ${event.model}`;
    case "tool": {
      let title2 = event.view?.title || event.function;
      if (event.view?.title) {
        title2 = title2.replace(
          /\{\{(\w+)\}\}/g,
          (match, key) => Object.hasOwn(event.arguments, key) ? String(event.arguments[key]) : match
        );
      }
      return `Tool: ${title2}`;
    }
    case "error":
      return "Error";
    case "logger":
      return event.message.level;
    case "info":
      return "Info" + (event.source ? ": " + event.source : "");
    case "compaction": {
      const source = event.source && event.source !== "inspect" ? event.source : "";
      return "Compaction" + source;
    }
    case "step":
      if (event.name === kSandboxSignalName) return "Sandbox Events";
      if (event.name === "init") return "Init";
      if (event.name === "sample_init") return "Sample Init";
      return event.type ? `${event.type}: ${event.name}` : `Step: ${event.name}`;
    case "subtask":
      return event.type === "fork" ? `Fork: ${event.name}` : `Subtask: ${event.name}`;
    case "span_begin":
      if (event.span_id === kSandboxSignalName) return "Sandbox Events";
      if (event.name === "init") return "Init";
      if (event.name === "sample_init") return "Sample Init";
      return event.type ? `${event.type}: ${event.name}` : `Step: ${event.name}`;
    case "score":
      return (event.intermediate ? "Intermediate " : "") + "Score";
    case "score_edit":
      return "Edit Score";
    case "sample_init":
      return "Sample";
    case "sample_limit":
      return sampleLimitTitles[event.type] ?? event.type;
    case "input":
      return "Input";
    case "approval":
      return approvalDecisionLabels[event.decision] ?? event.decision;
    case "sandbox":
      return `Sandbox: ${event.action}`;
    default:
      return "";
  }
};
const formatTiming = (timestamp, working_start) => {
  if (working_start) {
    return `${formatDateTime(new Date(timestamp))}
@ working time: ${formatTime(working_start)}`;
  } else {
    return formatDateTime(new Date(timestamp));
  }
};
const formatTitle = (title2, total_tokens, working_start) => {
  const subItems = [];
  if (total_tokens) {
    subItems.push(`${formatNumber(total_tokens)} tokens`);
  }
  if (working_start) {
    subItems.push(`${formatTime(working_start)}`);
  }
  const subtitle = subItems.length > 0 ? ` (${subItems.join(", ")})` : "";
  return `${title2}${subtitle}`;
};
const ApprovalEventView = ({
  eventNode,
  className
}) => {
  const event = eventNode.event;
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    EventRow,
    {
      title: eventTitle(event),
      icon: decisionIcon(event.decision),
      className,
      children: event.explanation || ""
    }
  );
};
const decisionIcon = (decision) => {
  switch (decision) {
    case "approve":
      return ApplicationIcons.approvals.approve;
    case "reject":
      return ApplicationIcons.approvals.reject;
    case "terminate":
      return ApplicationIcons.approvals.terminate;
    case "escalate":
      return ApplicationIcons.approvals.escalate;
    case "modify":
      return ApplicationIcons.approvals.modify;
    default:
      return ApplicationIcons.approve;
  }
};
const tab = "_tab_1je38_1";
const styles$j = {
  tab
};
const EventNav = ({
  target: target2,
  title: title2,
  selectedNav,
  setSelectedNav
}) => {
  const active = target2 === selectedNav;
  const handleClick = reactExports.useCallback(() => {
    setSelectedNav(target2);
  }, [setSelectedNav, target2]);
  return /* @__PURE__ */ jsxRuntimeExports.jsx("li", { className: "nav-item", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
    "button",
    {
      type: "button",
      role: "tab",
      "aria-controls": target2,
      "aria-selected": active,
      className: clsx(
        "nav-link",
        active ? "active " : "",
        "text-style-label",
        "text-size-small",
        styles$j.tab
      ),
      onClick: handleClick,
      children: title2
    }
  ) });
};
const navs$1 = "_navs_1vm6p_1";
const styles$i = {
  navs: navs$1
};
const EventNavs = ({
  navs: navs2,
  selectedNav,
  setSelectedNav
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    "ul",
    {
      className: clsx("nav", "nav-pills", styles$i.navs),
      role: "tablist",
      "aria-orientation": "horizontal",
      children: navs2.map((nav) => {
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          EventNav,
          {
            target: nav.target,
            title: nav.title,
            selectedNav,
            setSelectedNav
          },
          nav.title
        );
      })
    }
  );
};
const StickyScrollContext = reactExports.createContext(
  null
);
const StickyScrollProvider = StickyScrollContext.Provider;
const useStickyScrollContainer = () => reactExports.useContext(StickyScrollContext);
const scrollListenerMap = /* @__PURE__ */ new Map();
function updateStickyState(container2, elements) {
  const containerRect = container2?.getBoundingClientRect();
  const containerTop = containerRect?.top ?? 0;
  const stickyTop = parseFloat(
    getComputedStyle(document.body).getPropertyValue(
      "--inspect-event-panel-sticky-top"
    )
  ) || 0;
  elements.forEach((el) => {
    const rect = el.getBoundingClientRect();
    const relativeTop = rect.top - containerTop;
    const isStuck = relativeTop <= stickyTop + 1 && relativeTop >= stickyTop - 1;
    el.toggleAttribute("data-useStickyObserver-stuck", isStuck);
  });
}
function getScrollListener(container2) {
  let entry = scrollListenerMap.get(container2);
  if (!entry) {
    const elements = /* @__PURE__ */ new Set();
    let rafId = null;
    const handleScroll = () => {
      if (rafId === null) {
        rafId = requestAnimationFrame(() => {
          updateStickyState(container2, elements);
          rafId = null;
        });
      }
    };
    const scrollTarget = container2 || window;
    scrollTarget.addEventListener("scroll", handleScroll, { passive: true });
    window.addEventListener("resize", handleScroll, { passive: true });
    const cleanup = () => {
      scrollTarget.removeEventListener("scroll", handleScroll);
      window.removeEventListener("resize", handleScroll);
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
      }
    };
    entry = { elements, cleanup };
    scrollListenerMap.set(container2, entry);
  }
  return entry;
}
function useStickyObserver() {
  const ref = reactExports.useRef(null);
  const scrollContainerRef = useStickyScrollContainer();
  const [container2, setContainer] = reactExports.useState(null);
  reactExports.useEffect(() => {
    const checkContainer = () => {
      const newContainer = scrollContainerRef?.current ?? null;
      if (newContainer !== container2) {
        setContainer(newContainer);
      }
    };
    checkContainer();
    const timeoutId = setTimeout(checkContainer, 0);
    return () => clearTimeout(timeoutId);
  }, [scrollContainerRef, container2]);
  reactExports.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (scrollContainerRef && !container2) {
      return;
    }
    const { elements, cleanup } = getScrollListener(container2);
    elements.add(el);
    updateStickyState(container2, elements);
    return () => {
      elements.delete(el);
      el.removeAttribute("data-useStickyObserver-stuck");
      if (elements.size === 0) {
        cleanup();
        scrollListenerMap.delete(container2);
      }
    };
  }, [container2, scrollContainerRef]);
  return ref;
}
const stickyWrapper = "_stickyWrapper_1yfru_1";
const label = "_label_1yfru_22";
const navs = "_navs_1yfru_27";
const turnLabel = "_turnLabel_1yfru_33";
const card = "_card_1yfru_39";
const cardContent = "_cardContent_1yfru_47";
const hidden = "_hidden_1yfru_52";
const copyLink = "_copyLink_1yfru_60";
const hover = "_hover_1yfru_68";
const root = "_root_1yfru_72";
const bottomDongle = "_bottomDongle_1yfru_77";
const dongleIcon = "_dongleIcon_1yfru_94";
const styles$h = {
  stickyWrapper,
  label,
  navs,
  turnLabel,
  card,
  cardContent,
  hidden,
  copyLink,
  hover,
  root,
  bottomDongle,
  dongleIcon
};
const EventPanel = ({
  eventNodeId,
  depth,
  className,
  title: title2,
  subTitle,
  text,
  icon: icon2,
  children,
  childIds,
  collapsibleContent,
  collapseControl = "top",
  turnLabel: turnLabel2
}) => {
  const [collapsed2, setCollapsed] = useCollapseSampleEvent(
    kTranscriptCollapseScope,
    eventNodeId
  );
  const isCollapsible = (childIds || []).length > 0 || collapsibleContent;
  const useBottomDongle = isCollapsible && collapseControl === "bottom";
  const sampleEventUrl = useSampleEventUrl(eventNodeId);
  const url = supportsLinking() && sampleEventUrl ? toFullUrl(sampleEventUrl) : void 0;
  const pillId = (index) => {
    return `${eventNodeId}-nav-pill-${index}`;
  };
  const filteredArrChildren = (Array.isArray(children) ? children : [children]).filter((child) => !!child);
  const defaultPill = filteredArrChildren.findIndex((node2) => {
    return hasDataDefault(node2) && node2.props["data-default"];
  });
  const defaultPillId = defaultPill !== -1 ? pillId(defaultPill) : pillId(0);
  const [selectedNav, setSelectedNav] = useProperty(
    eventNodeId,
    "selectedNav",
    {
      defaultValue: defaultPillId
    }
  );
  const stickyRef = useStickyObserver();
  const gridColumns = [];
  if (isCollapsible && !useBottomDongle) {
    gridColumns.push("minmax(0, max-content)");
  }
  if (icon2) {
    gridColumns.push("max-content");
  }
  gridColumns.push("minmax(0, max-content)");
  if (url) {
    gridColumns.push("minmax(0, max-content)");
  }
  gridColumns.push("auto");
  gridColumns.push("minmax(0, max-content)");
  gridColumns.push("minmax(0, max-content)");
  const toggleCollapse = reactExports.useCallback(() => {
    setCollapsed(!collapsed2);
  }, [setCollapsed, collapsed2]);
  const [mouseOver, setMouseOver] = reactExports.useState(false);
  const titleEl = title2 || icon2 || filteredArrChildren.length > 1 ? /* @__PURE__ */ jsxRuntimeExports.jsxs(
    "div",
    {
      title: subTitle,
      className: clsx(
        "text-size-small",
        mouseOver ? styles$h.hover : "",
        turnLabel2 ? styles$h.stickyWrapper : ""
      ),
      ref: turnLabel2 ? stickyRef : null,
      style: {
        display: "grid",
        gridTemplateColumns: gridColumns.join(" "),
        columnGap: "0.3em",
        cursor: isCollapsible && !useBottomDongle ? "pointer" : void 0
      },
      onMouseEnter: () => setMouseOver(true),
      onMouseLeave: () => setMouseOver(false),
      children: [
        isCollapsible && !useBottomDongle ? /* @__PURE__ */ jsxRuntimeExports.jsx(
          "i",
          {
            onClick: toggleCollapse,
            className: collapsed2 ? ApplicationIcons.chevron.right : ApplicationIcons.chevron.down
          }
        ) : "",
        icon2 ? /* @__PURE__ */ jsxRuntimeExports.jsx(
          "i",
          {
            className: clsx(
              icon2 || ApplicationIcons.metadata,
              "text-style-secondary"
            ),
            onClick: toggleCollapse
          }
        ) : "",
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            className: clsx("text-style-secondary", "text-style-label"),
            onClick: toggleCollapse,
            children: title2
          }
        ),
        url ? /* @__PURE__ */ jsxRuntimeExports.jsx(
          CopyButton,
          {
            value: url,
            icon: ApplicationIcons.link,
            className: clsx(styles$h.copyLink)
          }
        ) : "",
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { onClick: toggleCollapse }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            className: clsx("text-style-secondary", styles$h.label),
            onClick: toggleCollapse,
            children: collapsed2 ? text : ""
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$h.navs, children: [
          isCollapsible && collapsibleContent && collapsed2 ? "" : filteredArrChildren && filteredArrChildren.length > 1 ? /* @__PURE__ */ jsxRuntimeExports.jsx(
            EventNavs,
            {
              navs: filteredArrChildren.map((child, index) => {
                const defaultTitle = `Tab ${index}`;
                const title22 = child && reactExports.isValidElement(child) ? child.props["data-name"] || defaultTitle : defaultTitle;
                return {
                  id: `eventpanel-${eventNodeId}-${index}`,
                  title: title22,
                  target: pillId(index)
                };
              }),
              selectedNav,
              setSelectedNav
            }
          ) : "",
          turnLabel2 && /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: clsx(styles$h.turnLabel), children: turnLabel2 })
        ] })
      ]
    }
  ) : "";
  const card2 = /* @__PURE__ */ jsxRuntimeExports.jsxs(
    "div",
    {
      id: `event-panel-${eventNodeId}`,
      className: clsx(
        className,
        styles$h.card,
        depth === 0 ? styles$h.root : void 0
      ),
      children: [
        titleEl,
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            className: clsx(
              "tab-content",
              styles$h.cardContent,
              isCollapsible && collapsed2 && collapsibleContent ? styles$h.hidden : void 0
            ),
            children: filteredArrChildren?.map((child, index) => {
              const id = pillId(index);
              const isSelected = id === selectedNav;
              if (!isSelected) {
                return null;
              }
              return /* @__PURE__ */ jsxRuntimeExports.jsx(
                "div",
                {
                  id,
                  className: clsx("tab-pane", "show", isSelected ? "active" : ""),
                  children: child
                },
                `children-${id}-${index}`
              );
            })
          }
        ),
        isCollapsible && useBottomDongle ? /* @__PURE__ */ jsxRuntimeExports.jsxs(
          "div",
          {
            className: clsx(styles$h.bottomDongle, "text-size-smallest"),
            onClick: toggleCollapse,
            children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx(
                "i",
                {
                  className: clsx(
                    collapsed2 ? ApplicationIcons.chevron.right : ApplicationIcons.chevron.down,
                    styles$h.dongleIcon
                  )
                }
              ),
              "transcript (",
              childIds?.length,
              " ",
              childIds?.length === 1 ? "event" : "events",
              ")"
            ]
          }
        ) : void 0
      ]
    }
  );
  return card2;
};
function hasDataDefault(node2) {
  return reactExports.isValidElement(node2) && node2.props !== null && typeof node2.props === "object" && "data-default" in node2.props;
}
const ErrorEventView = ({
  eventNode,
  className
}) => {
  const event = eventNode.event;
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      title: formatTitle(eventTitle(event), void 0, event.working_start),
      className,
      subTitle: formatDateTime(new Date(event.timestamp)),
      icon: ApplicationIcons.error,
      children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        ANSIDisplay,
        {
          output: event.error.traceback_ansi,
          style: {
            fontSize: "clamp(0.3rem, 1.1vw, 0.8rem)",
            margin: "0.5em 0"
          }
        }
      )
    }
  );
};
const panel$1 = "_panel_vz394_1";
const styles$g = {
  panel: panel$1
};
const InfoEventView = ({
  eventNode,
  className
}) => {
  const event = eventNode.event;
  const panels = [];
  if (typeof event.data === "string") {
    panels.push(
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        RenderedText,
        {
          markdown: event.data,
          className: clsx(styles$g.panel, "text-size-base"),
          omitMath: true
        }
      )
    );
  } else {
    panels.push(/* @__PURE__ */ jsxRuntimeExports.jsx(JSONPanel, { data: event.data, className: styles$g.panel }));
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      title: formatTitle(eventTitle(event), void 0, event.working_start),
      className,
      subTitle: formatDateTime(new Date(event.timestamp)),
      icon: ApplicationIcons.info,
      children: panels
    }
  );
};
const InputEventView = ({
  eventNode,
  className
}) => {
  const event = eventNode.event;
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      title: formatTitle(eventTitle(event), void 0, event.working_start),
      className,
      subTitle: formatDateTime(new Date(event.timestamp)),
      icon: ApplicationIcons.input,
      children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        ANSIDisplay,
        {
          output: event.input_ansi,
          style: { fontSize: "clamp(0.4rem, 1.15vw, 0.9rem)" }
        }
      )
    }
  );
};
const grid = "_grid_159mg_1";
const wrap = "_wrap_159mg_12";
const styles$f = {
  grid,
  wrap
};
const LoggerEventView = ({
  eventNode,
  className
}) => {
  const event = eventNode.event;
  const obj = parsedJson(event.message.message);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    EventRow,
    {
      className,
      title: eventTitle(event),
      icon: ApplicationIcons.logging[event.message.level.toLowerCase()],
      children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx("text-size-base", styles$f.grid), children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-size-smaller"), children: obj !== void 0 && obj !== null ? /* @__PURE__ */ jsxRuntimeExports.jsx(MetaDataGrid, { entries: obj }) : /* @__PURE__ */ jsxRuntimeExports.jsx(
          ExpandablePanel,
          {
            id: `event-message-${event.uuid}`,
            collapse: true,
            className: clsx(styles$f.wrap),
            children: event.message.message
          }
        ) }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx("text-size-smaller", "text-style-secondary"), children: [
          event.message.filename,
          ":",
          event.message.lineno
        ] })
      ] })
    }
  );
};
const container$3 = "_container_1ww70_1";
const titleRow = "_titleRow_1ww70_5";
const title = "_title_1ww70_5";
const styles$e = {
  container: container$3,
  titleRow,
  title
};
const EventSection = ({
  title: title2,
  children,
  copyContent,
  className
}) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$e.container, className), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$e.titleRow), children: /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        className: clsx("text-size-small", "text-style-label", styles$e.title),
        children: [
          title2,
          copyContent ? /* @__PURE__ */ jsxRuntimeExports.jsx(CopyButton, { value: copyContent, ariaLabel: "Copy to clipboard" }) : null
        ]
      }
    ) }),
    children
  ] });
};
const container$2 = "_container_1hidt_1";
const all = "_all_1hidt_6";
const tableSelection = "_tableSelection_1hidt_12";
const codePre = "_codePre_1hidt_22";
const code$1 = "_code_1hidt_22";
const progress$1 = "_progress_1hidt_34";
const error = "_error_1hidt_38";
const toolConfig = "_toolConfig_1hidt_54";
const toolChoice = "_toolChoice_1hidt_62";
const traceback = "_traceback_1hidt_71";
const styles$d = {
  container: container$2,
  all,
  tableSelection,
  codePre,
  code: code$1,
  progress: progress$1,
  error,
  toolConfig,
  toolChoice,
  traceback
};
const wrapper = "_wrapper_cv5sf_1";
const col2 = "_col2_cv5sf_8";
const col1_3 = "_col1_3_cv5sf_12";
const col3 = "_col3_cv5sf_16";
const separator$2 = "_separator_cv5sf_20";
const topMargin = "_topMargin_cv5sf_26";
const styles$c = {
  wrapper,
  col2,
  col1_3,
  col3,
  separator: separator$2,
  topMargin
};
const EventTimingPanel = ({
  timestamp,
  completed,
  working_start,
  working_time
}) => {
  const rows = [
    {
      label: "Clock Time",
      value: void 0,
      secondary: false
    },
    {
      label: "---",
      value: void 0,
      secondary: false
    }
  ];
  if (!completed) {
    rows.push({
      label: "Timestamp",
      value: formatDateTime(new Date(timestamp))
    });
  } else {
    rows.push({
      label: "Start",
      value: /* @__PURE__ */ jsxRuntimeExports.jsx("span", { title: timestamp, children: formatDateTime(new Date(timestamp)) })
    });
    rows.push({
      label: "End",
      value: /* @__PURE__ */ jsxRuntimeExports.jsx("span", { title: completed, children: formatDateTime(new Date(completed)) })
    });
  }
  if (working_start || working_time) {
    rows.push({
      label: "Working Time",
      value: void 0,
      secondary: false,
      topMargin: true
    });
    rows.push({
      label: "---",
      value: void 0,
      secondary: false
    });
    if (working_start) {
      rows.push({
        label: "Start",
        value: formatTime(working_start)
      });
    }
    if (working_time) {
      rows.push({
        label: "Duration",
        value: formatTime(working_time)
      });
    }
    if (working_start && working_time) {
      rows.push({
        label: "End",
        value: formatTime(
          Math.round(working_start * 10) / 10 + Math.round(working_time * 10) / 10
        )
      });
    }
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-size-small", styles$c.wrapper), children: rows.map((row2, idx) => {
    if (row2.label === "---") {
      return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$c.separator }, `$usage-sep-${idx}`);
    } else {
      return /* @__PURE__ */ jsxRuntimeExports.jsxs(reactExports.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            className: clsx(
              "text-style-label",
              "text-style-secondary",
              row2.secondary ? styles$c.col2 : styles$c.col1_3,
              row2.topMargin ? styles$c.topMargin : void 0
            ),
            children: row2.label
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$c.col3, children: row2.value ? row2.value : "" })
      ] }, `$usage-row-${idx}`);
    }
  }) });
};
const ModelEventView = ({
  eventNode,
  showToolCalls,
  className,
  context
}) => {
  const event = eventNode.event;
  const totalUsage = event.output.usage?.total_tokens;
  const callTime = event.output.time;
  const outputMessages = event.output.choices?.map((choice) => {
    return { ...choice.message };
  }) ?? [];
  if (outputMessages.length > 0) {
    outputMessages[outputMessages.length - 1].timestamp = event.completed;
  }
  const inputMessages = event.input.map((msg) => ({ ...msg }));
  if (inputMessages.length > 0) {
    inputMessages[inputMessages.length - 1].timestamp = event.timestamp;
  }
  const entries = { ...event.config };
  delete entries["max_connections"];
  const userMessages = [];
  let offset = void 0;
  const lastMessage = inputMessages.at(-1);
  if (lastMessage?.role === "assistant") {
    userMessages.push(lastMessage);
    offset = -1;
  }
  for (const msg of inputMessages.slice(offset).reverse()) {
    if (msg.role === "user" && !msg.tool_call_id || msg.role === "system" || // If the client doesn't support tool events, then tools messages are allowed to be displayed
    // in this view, since no tool events will be shown. This pretty much happens for bridged agents
    // where tool events aren't captured.
    context?.hasToolEvents === false && msg.role === "tool") {
      userMessages.unshift(msg);
    } else {
      break;
    }
  }
  const panelTitle = eventTitle(event);
  const turnLabel2 = context?.turnInfo ? `turn ${context.turnInfo.turnNumber}/${context.turnInfo.totalTurns}` : void 0;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      className,
      title: formatTitle(panelTitle, totalUsage, callTime),
      subTitle: formatTiming(event.timestamp, event.working_start),
      icon: ApplicationIcons.model,
      turnLabel: turnLabel2,
      children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { "data-name": "Summary", className: styles$d.container, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            ChatView,
            {
              id: `${eventNode.id}-model-output`,
              messages: [...userMessages, ...outputMessages],
              numbered: false,
              toolCallStyle: showToolCalls ? "complete" : "omit",
              resolveToolCallsIntoPreviousMessage: context?.hasToolEvents !== false,
              allowLinking: false
            }
          ),
          event.error ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$d.error, children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: ApplicationIcons.error, "aria-hidden": "true" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              ANSIDisplay,
              {
                output: event.error,
                style: {
                  fontSize: "clamp(0.3rem, 1.1vw, 0.8rem)"
                }
              }
            )
          ] }) : event.pending ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$d.progress), children: /* @__PURE__ */ jsxRuntimeExports.jsx(PulsingDots, { subtle: false, size: "medium" }) }) : void 0
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { "data-name": "All", className: styles$d.container, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles$d.all, children: [
            Object.keys(entries).length > 0 && /* @__PURE__ */ jsxRuntimeExports.jsx(
              EventSection,
              {
                title: "Configuration",
                className: styles$d.tableSelection,
                children: /* @__PURE__ */ jsxRuntimeExports.jsx(MetaDataGrid, { entries, plain: true })
              }
            ),
            /* @__PURE__ */ jsxRuntimeExports.jsx(EventSection, { title: "Usage", className: styles$d.tableSelection, children: event.output.usage !== null ? /* @__PURE__ */ jsxRuntimeExports.jsx(ModelUsagePanel, { usage: event.output.usage }) : void 0 }),
            /* @__PURE__ */ jsxRuntimeExports.jsx(EventSection, { title: "Timing", className: styles$d.tableSelection, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
              EventTimingPanel,
              {
                timestamp: event.timestamp,
                completed: event.completed,
                working_start: event.working_start,
                working_time: event.working_time
              }
            ) })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(EventSection, { title: "Messages", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            ChatView,
            {
              id: `${eventNode.id}-model-input-full`,
              messages: [...inputMessages, ...outputMessages],
              resolveToolCallsIntoPreviousMessage: context?.hasToolEvents !== false,
              allowLinking: false
            }
          ) })
        ] }),
        event.tools.length > 1 && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { "data-name": "Tools", className: styles$d.container, children: /* @__PURE__ */ jsxRuntimeExports.jsx(ToolsConfig, { tools: event.tools, toolChoice: event.tool_choice }) }),
        event.call ? /* @__PURE__ */ jsxRuntimeExports.jsx(
          APIView,
          {
            "data-name": "API",
            call: event.call,
            error: event.error,
            className: styles$d.container
          }
        ) : "",
        event.traceback_ansi && /* @__PURE__ */ jsxRuntimeExports.jsx("div", { "data-name": "Error", className: styles$d.container, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          ANSIDisplay,
          {
            output: event.traceback_ansi,
            className: styles$d.traceback
          }
        ) })
      ]
    }
  );
};
const APIView = ({ call, error: error2, className }) => {
  const requestCode = reactExports.useMemo(() => {
    return call?.request ? JSON.stringify(call.request, void 0, 2) : "";
  }, [call?.request]);
  const responseCode = reactExports.useMemo(() => {
    return call?.response ? JSON.stringify(call.response, void 0, 2) : null;
  }, [call?.response]);
  if (!call) {
    return null;
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(className), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(EventSection, { title: "Request", copyContent: requestCode, children: requestCode ? /* @__PURE__ */ jsxRuntimeExports.jsx(APICodeCell, { sourceCode: requestCode }) : "None" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx(EventSection, { title: "Response", copyContent: responseCode ?? "", children: responseCode ? /* @__PURE__ */ jsxRuntimeExports.jsx(APICodeCell, { sourceCode: responseCode }) : error2 ? "None" : /* @__PURE__ */ jsxRuntimeExports.jsx(PulsingDots, { subtle: false, size: "medium" }) })
  ] });
};
const APICodeCell = ({ id, sourceCode }) => {
  const sourceCodeRef = reactExports.useRef(null);
  usePrismHighlight(sourceCodeRef, sourceCode?.length ?? 0);
  if (!sourceCode) {
    return null;
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { ref: sourceCodeRef, className: clsx("model-call"), children: /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: clsx(styles$d.codePre), children: /* @__PURE__ */ jsxRuntimeExports.jsx(
    "code",
    {
      id,
      className: clsx("language-json", styles$d.code, "text-size-small"),
      children: sourceCode
    }
  ) }) });
};
const ToolsConfig = ({ tools: tools2, toolChoice: toolChoice2 }) => {
  const toolEls = tools2.map((tool2, idx) => {
    return /* @__PURE__ */ jsxRuntimeExports.jsxs(reactExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-style-label", "text-style-secondary"), children: tool2.name }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: tool2.description })
    ] }, `${tool2.name}-${idx}`);
  });
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$d.toolConfig, "text-size-small"), children: toolEls }),
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$d.toolChoice, "text-size-small"), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-style-label", "text-style-secondary"), children: "Tool Choice" }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: /* @__PURE__ */ jsxRuntimeExports.jsx(ToolChoiceView, { toolChoice: toolChoice2 }) })
    ] })
  ] });
};
const ToolChoiceView = ({ toolChoice: toolChoice2 }) => {
  if (typeof toolChoice2 === "string") {
    return toolChoice2;
  } else {
    return /* @__PURE__ */ jsxRuntimeExports.jsxs("code", { children: [
      "`$",
      toolChoice2.name,
      "()`"
    ] });
  }
};
const noMargin = "_noMargin_1a3fk_1";
const code = "_code_1a3fk_5";
const sample = "_sample_1a3fk_10";
const section$1 = "_section_1a3fk_14";
const metadata = "_metadata_1a3fk_21";
const styles$b = {
  noMargin,
  code,
  sample,
  section: section$1,
  metadata
};
const SampleInitEventView = ({
  eventNode,
  className
}) => {
  const event = eventNode.event;
  const stateObj = event.state;
  const sections = [];
  if (event.sample.files && Object.keys(event.sample.files).length > 0) {
    sections.push(
      /* @__PURE__ */ jsxRuntimeExports.jsx(EventSection, { title: "Files", children: Object.keys(event.sample.files).map((file) => {
        return /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: styles$b.noMargin, children: file }, `sample-init-file-${file}`);
      }) }, `event-${eventNode.id}`)
    );
  }
  if (event.sample.setup) {
    sections.push(
      /* @__PURE__ */ jsxRuntimeExports.jsx(EventSection, { title: "Setup", children: /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: styles$b.code, children: /* @__PURE__ */ jsxRuntimeExports.jsx("code", { className: "sourceCode", children: event.sample.setup }) }) }, `${eventNode.id}-section-setup`)
    );
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      className,
      title: formatTitle(eventTitle(event), void 0, event.working_start),
      icon: ApplicationIcons.sample,
      subTitle: formatDateTime(new Date(event.timestamp)),
      children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { "data-name": "Sample", className: styles$b.sample, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            ChatView,
            {
              messages: stateObj["messages"],
              allowLinking: false
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
            event.sample.choices ? event.sample.choices.map((choice, index) => {
              return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
                String.fromCharCode(65 + index),
                ") ",
                choice
              ] }, `$choice-{choice}`);
            }) : "",
            sections.length > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$b.section, children: sections }) : "",
            event.sample.target ? /* @__PURE__ */ jsxRuntimeExports.jsx(EventSection, { title: "Target", children: toArray(event.sample.target).map((target2) => {
              return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-size-base"), children: target2 }, target2);
            }) }) : void 0
          ] })
        ] }),
        event.sample.metadata && Object.keys(event.sample.metadata).length > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx(
          MetaDataGrid,
          {
            "data-name": "Metadata",
            className: styles$b.metadata,
            entries: event.sample.metadata
          }
        ) : ""
      ]
    }
  );
};
const SampleLimitEventView = ({
  eventNode,
  className
}) => {
  const resolve_icon = (type) => {
    switch (type) {
      case "custom":
        return ApplicationIcons.limits.custom;
      case "time":
        return ApplicationIcons.limits.time;
      case "message":
        return ApplicationIcons.limits.messages;
      case "token":
        return ApplicationIcons.limits.tokens;
      case "operator":
        return ApplicationIcons.limits.operator;
      case "working":
        return ApplicationIcons.limits.execution;
      case "cost":
        return ApplicationIcons.limits.cost;
    }
  };
  const icon2 = resolve_icon(eventNode.event.type);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      title: formatTitle(
        eventTitle(eventNode.event),
        void 0,
        eventNode.event.working_start
      ),
      subTitle: formatDateTime(new Date(eventNode.event.timestamp)),
      icon: icon2,
      className,
      children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-size-smaller"), children: eventNode.event.message })
    }
  );
};
const twoColumn = "_twoColumn_1irga_9";
const exec = "_exec_1irga_15";
const result = "_result_1irga_19";
const fileLabel = "_fileLabel_1irga_23";
const wrapPre = "_wrapPre_1irga_28";
const styles$a = {
  twoColumn,
  exec,
  result,
  fileLabel,
  wrapPre
};
const SandboxEventView = ({
  eventNode,
  className
}) => {
  const event = eventNode.event;
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      className,
      title: formatTitle(eventTitle(event), void 0, event.working_start),
      icon: ApplicationIcons.sandbox,
      subTitle: formatTiming(event.timestamp, event.working_start),
      children: event.action === "exec" ? /* @__PURE__ */ jsxRuntimeExports.jsx(ExecView, { id: `${eventNode.id}-exec`, event }) : event.action === "read_file" ? /* @__PURE__ */ jsxRuntimeExports.jsx(ReadFileView, { id: `${eventNode.id}-read-file`, event }) : /* @__PURE__ */ jsxRuntimeExports.jsx(WriteFileView, { id: `${eventNode.id}-write-file`, event })
    }
  );
};
const ExecView = ({ id, event }) => {
  if (event.cmd === null) {
    return void 0;
  }
  const cmd = event.cmd;
  const options = event.options;
  const input = event.input;
  const result2 = event.result;
  const output = event.output ? event.output.trim() : void 0;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$a.exec), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(EventSection, { title: `Command`, children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$a.twoColumn), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: clsx(styles$a.wrapPre), children: cmd }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: clsx(styles$a.wrapPre), children: input !== null ? input?.trim() : void 0 }),
      options !== null && Object.keys(options).length > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx(EventSection, { title: `Options`, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        MetaDataGrid,
        {
          entries: options,
          plain: true
        }
      ) }) : void 0
    ] }) }),
    output || result2 !== null && result2 !== 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs(EventSection, { title: `Result`, children: [
      output ? /* @__PURE__ */ jsxRuntimeExports.jsx(ExpandablePanel, { id: `${id}-output`, collapse: false, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
        RenderedContent,
        {
          id: `${id}-output-content`,
          entry: { name: "sandbox_output", value: output }
        }
      ) }) : void 0,
      result2 !== 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$a.result, "text-size-base"), children: [
        "(exited with code ",
        result2,
        ")"
      ] }) : void 0
    ] }) : void 0
  ] });
};
const ReadFileView = ({ id, event }) => {
  if (event.file === null) {
    return void 0;
  }
  const file = event.file;
  const output = event.output;
  return /* @__PURE__ */ jsxRuntimeExports.jsx(FileView, { id, file, contents: output?.trim() });
};
const WriteFileView = ({ id, event }) => {
  if (event.file === null) {
    return void 0;
  }
  const file = event.file;
  const input = event.input;
  return /* @__PURE__ */ jsxRuntimeExports.jsx(FileView, { id, file, contents: input?.trim() });
};
const FileView = ({ id, file, contents: contents2 }) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(EventSection, { title: "File", children: /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: clsx(styles$a.fileLabel), children: file }) }),
    contents2 ? /* @__PURE__ */ jsxRuntimeExports.jsx(EventSection, { title: "Contents", children: /* @__PURE__ */ jsxRuntimeExports.jsx(ExpandablePanel, { id: `${id}-file`, collapse: false, children: /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { children: contents2 }) }) }) : void 0
  ] });
};
const explanation = "_explanation_1k2k0_1";
const wrappingContent$1 = "_wrappingContent_1k2k0_8";
const separator$1 = "_separator_1k2k0_13";
const styles$9 = {
  explanation,
  wrappingContent: wrappingContent$1,
  separator: separator$1
};
const ScoreEventView = ({
  eventNode,
  className
}) => {
  const event = eventNode.event;
  const resolvedTarget = event.target ? Array.isArray(event.target) ? event.target.join("\n") : event.target : void 0;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      title: formatTitle(eventTitle(event), void 0, event.working_start),
      className: clsx(className, "text-size-small"),
      subTitle: formatDateTime(new Date(event.timestamp)),
      icon: ApplicationIcons.scorer,
      collapsibleContent: true,
      children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { "data-name": "Explanation", className: clsx(styles$9.explanation), children: [
          event.target ? /* @__PURE__ */ jsxRuntimeExports.jsxs(reactExports.Fragment, { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$9.separator) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-style-label", children: "Target" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: /* @__PURE__ */ jsxRuntimeExports.jsx(RenderedText, { markdown: resolvedTarget || "" }) })
          ] }) : "",
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$9.separator) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-style-label", children: "Answer" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$9.wrappingContent), children: /* @__PURE__ */ jsxRuntimeExports.jsx(RenderedText, { markdown: event.score.answer || "" }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$9.separator) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-style-label", children: "Explanation" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$9.wrappingContent), children: /* @__PURE__ */ jsxRuntimeExports.jsx(RenderedText, { markdown: event.score.explanation || "" }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$9.separator) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-style-label", children: "Score" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: renderScore(event.score.value) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$9.separator) })
        ] }),
        event.score.metadata ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { "data-name": "Metadata", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          RecordTree,
          {
            id: `${eventNode.id}-score-metadata`,
            record: event.score.metadata,
            className: styles$9.metadataTree,
            defaultExpandLevel: 0
          }
        ) }) : void 0
      ]
    }
  );
};
const renderScore = (value2) => {
  if (Array.isArray(value2)) {
    return value2.join(" ");
  } else if (typeof value2 === "object") {
    return /* @__PURE__ */ jsxRuntimeExports.jsx(MetaDataGrid, { entries: value2 });
  } else {
    return value2;
  }
};
function cloneRegExp(re) {
  var _a;
  const regexMatch = /^\/(.*)\/([gimyu]*)$/.exec(re.toString());
  if (!regexMatch) {
    throw new Error("Invalid RegExp");
  }
  return new RegExp((_a = regexMatch[1]) !== null && _a !== void 0 ? _a : "", regexMatch[2]);
}
function clone(arg) {
  if (typeof arg !== "object") {
    return arg;
  }
  if (arg === null) {
    return null;
  }
  if (Array.isArray(arg)) {
    return arg.map(clone);
  }
  if (arg instanceof Date) {
    return new Date(arg.getTime());
  }
  if (arg instanceof RegExp) {
    return cloneRegExp(arg);
  }
  const cloned = {};
  for (const name in arg) {
    if (Object.prototype.hasOwnProperty.call(arg, name)) {
      cloned[name] = clone(arg[name]);
    }
  }
  return cloned;
}
function assertNonEmptyArray(arr, message2) {
  if (arr.length === 0) {
    throw new Error("Expected a non-empty array");
  }
}
function assertArrayHasAtLeast2(arr, message2) {
  if (arr.length < 2) {
    throw new Error("Expected an array with at least 2 items");
  }
}
const lastNonEmpty = (arr) => arr[arr.length - 1];
class Context {
  setResult(result2) {
    this.result = result2;
    this.hasResult = true;
    return this;
  }
  exit() {
    this.exiting = true;
    return this;
  }
  push(child, name) {
    child.parent = this;
    if (typeof name !== "undefined") {
      child.childName = name;
    }
    child.root = this.root || this;
    child.options = child.options || this.options;
    if (!this.children) {
      this.children = [child];
      this.nextAfterChildren = this.next || null;
      this.next = child;
    } else {
      assertNonEmptyArray(this.children);
      lastNonEmpty(this.children).next = child;
      this.children.push(child);
    }
    child.next = this;
    return this;
  }
}
class DiffContext extends Context {
  constructor(left, right) {
    super();
    this.left = left;
    this.right = right;
    this.pipe = "diff";
  }
  prepareDeltaResult(result2) {
    var _a, _b, _c, _d;
    if (typeof result2 === "object") {
      if (((_a = this.options) === null || _a === void 0 ? void 0 : _a.omitRemovedValues) && Array.isArray(result2) && result2.length > 1 && (result2.length === 2 || // modified
      result2[2] === 0 || // deleted
      result2[2] === 3)) {
        result2[0] = 0;
      }
      if ((_b = this.options) === null || _b === void 0 ? void 0 : _b.cloneDiffValues) {
        const clone$1 = typeof ((_c = this.options) === null || _c === void 0 ? void 0 : _c.cloneDiffValues) === "function" ? (_d = this.options) === null || _d === void 0 ? void 0 : _d.cloneDiffValues : clone;
        if (typeof result2[0] === "object") {
          result2[0] = clone$1(result2[0]);
        }
        if (typeof result2[1] === "object") {
          result2[1] = clone$1(result2[1]);
        }
      }
    }
    return result2;
  }
  setResult(result2) {
    this.prepareDeltaResult(result2);
    return super.setResult(result2);
  }
}
class PatchContext extends Context {
  constructor(left, delta) {
    super();
    this.left = left;
    this.delta = delta;
    this.pipe = "patch";
  }
}
class ReverseContext extends Context {
  constructor(delta) {
    super();
    this.delta = delta;
    this.pipe = "reverse";
  }
}
class Pipe {
  constructor(name) {
    this.name = name;
    this.filters = [];
  }
  process(input) {
    if (!this.processor) {
      throw new Error("add this pipe to a processor before using it");
    }
    const debug = this.debug;
    const length = this.filters.length;
    const context = input;
    for (let index = 0; index < length; index++) {
      const filter = this.filters[index];
      if (!filter)
        continue;
      if (debug) {
        this.log(`filter: ${filter.filterName}`);
      }
      filter(context);
      if (typeof context === "object" && context.exiting) {
        context.exiting = false;
        break;
      }
    }
    if (!context.next && this.resultCheck) {
      this.resultCheck(context);
    }
  }
  log(msg) {
    console.log(`[jsondiffpatch] ${this.name} pipe, ${msg}`);
  }
  append(...args) {
    this.filters.push(...args);
    return this;
  }
  prepend(...args) {
    this.filters.unshift(...args);
    return this;
  }
  indexOf(filterName) {
    if (!filterName) {
      throw new Error("a filter name is required");
    }
    for (let index = 0; index < this.filters.length; index++) {
      const filter = this.filters[index];
      if ((filter === null || filter === void 0 ? void 0 : filter.filterName) === filterName) {
        return index;
      }
    }
    throw new Error(`filter not found: ${filterName}`);
  }
  list() {
    return this.filters.map((f) => f.filterName);
  }
  after(filterName, ...params) {
    const index = this.indexOf(filterName);
    this.filters.splice(index + 1, 0, ...params);
    return this;
  }
  before(filterName, ...params) {
    const index = this.indexOf(filterName);
    this.filters.splice(index, 0, ...params);
    return this;
  }
  replace(filterName, ...params) {
    const index = this.indexOf(filterName);
    this.filters.splice(index, 1, ...params);
    return this;
  }
  remove(filterName) {
    const index = this.indexOf(filterName);
    this.filters.splice(index, 1);
    return this;
  }
  clear() {
    this.filters.length = 0;
    return this;
  }
  shouldHaveResult(should) {
    if (should === false) {
      this.resultCheck = null;
      return this;
    }
    if (this.resultCheck) {
      return this;
    }
    this.resultCheck = (context) => {
      if (!context.hasResult) {
        console.log(context);
        const error2 = new Error(`${this.name} failed`);
        error2.noResult = true;
        throw error2;
      }
    };
    return this;
  }
}
class Processor {
  constructor(options) {
    this.selfOptions = options || {};
    this.pipes = {};
  }
  options(options) {
    if (options) {
      this.selfOptions = options;
    }
    return this.selfOptions;
  }
  pipe(name, pipeArg) {
    let pipe = pipeArg;
    if (typeof name === "string") {
      if (typeof pipe === "undefined") {
        return this.pipes[name];
      }
      this.pipes[name] = pipe;
    }
    if (name && name.name) {
      pipe = name;
      if (pipe.processor === this) {
        return pipe;
      }
      this.pipes[pipe.name] = pipe;
    }
    if (!pipe) {
      throw new Error(`pipe is not defined: ${name}`);
    }
    pipe.processor = this;
    return pipe;
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  process(input, pipe) {
    let context = input;
    context.options = this.options();
    let nextPipe = pipe || input.pipe || "default";
    let lastPipe = void 0;
    while (nextPipe) {
      if (typeof context.nextAfterChildren !== "undefined") {
        context.next = context.nextAfterChildren;
        context.nextAfterChildren = null;
      }
      if (typeof nextPipe === "string") {
        nextPipe = this.pipe(nextPipe);
      }
      nextPipe.process(context);
      lastPipe = nextPipe;
      nextPipe = null;
      if (context) {
        if (context.next) {
          context = context.next;
          nextPipe = context.pipe || lastPipe;
        }
      }
    }
    return context.hasResult ? context.result : void 0;
  }
}
const defaultMatch = (array1, array2, index1, index2) => array1[index1] === array2[index2];
const lengthMatrix = (array1, array2, match, context) => {
  var _a, _b, _c;
  const len1 = array1.length;
  const len2 = array2.length;
  let x;
  let y;
  const matrix = new Array(len1 + 1);
  for (x = 0; x < len1 + 1; x++) {
    const matrixNewRow = new Array(len2 + 1);
    for (y = 0; y < len2 + 1; y++) {
      matrixNewRow[y] = 0;
    }
    matrix[x] = matrixNewRow;
  }
  matrix.match = match;
  for (x = 1; x < len1 + 1; x++) {
    const matrixRowX = matrix[x];
    if (matrixRowX === void 0) {
      throw new Error("LCS matrix row is undefined");
    }
    const matrixRowBeforeX = matrix[x - 1];
    if (matrixRowBeforeX === void 0) {
      throw new Error("LCS matrix row is undefined");
    }
    for (y = 1; y < len2 + 1; y++) {
      if (match(array1, array2, x - 1, y - 1, context)) {
        matrixRowX[y] = ((_a = matrixRowBeforeX[y - 1]) !== null && _a !== void 0 ? _a : 0) + 1;
      } else {
        matrixRowX[y] = Math.max((_b = matrixRowBeforeX[y]) !== null && _b !== void 0 ? _b : 0, (_c = matrixRowX[y - 1]) !== null && _c !== void 0 ? _c : 0);
      }
    }
  }
  return matrix;
};
const backtrack = (matrix, array1, array2, context) => {
  let index1 = array1.length;
  let index2 = array2.length;
  const subsequence = {
    sequence: [],
    indices1: [],
    indices2: []
  };
  while (index1 !== 0 && index2 !== 0) {
    if (matrix.match === void 0) {
      throw new Error("LCS matrix match function is undefined");
    }
    const sameLetter = matrix.match(array1, array2, index1 - 1, index2 - 1, context);
    if (sameLetter) {
      subsequence.sequence.unshift(array1[index1 - 1]);
      subsequence.indices1.unshift(index1 - 1);
      subsequence.indices2.unshift(index2 - 1);
      --index1;
      --index2;
    } else {
      const matrixRowIndex1 = matrix[index1];
      if (matrixRowIndex1 === void 0) {
        throw new Error("LCS matrix row is undefined");
      }
      const valueAtMatrixAbove = matrixRowIndex1[index2 - 1];
      if (valueAtMatrixAbove === void 0) {
        throw new Error("LCS matrix value is undefined");
      }
      const matrixRowBeforeIndex1 = matrix[index1 - 1];
      if (matrixRowBeforeIndex1 === void 0) {
        throw new Error("LCS matrix row is undefined");
      }
      const valueAtMatrixLeft = matrixRowBeforeIndex1[index2];
      if (valueAtMatrixLeft === void 0) {
        throw new Error("LCS matrix value is undefined");
      }
      if (valueAtMatrixAbove > valueAtMatrixLeft) {
        --index2;
      } else {
        --index1;
      }
    }
  }
  return subsequence;
};
const get = (array1, array2, match, context) => {
  const innerContext = context || {};
  const matrix = lengthMatrix(array1, array2, match || defaultMatch, innerContext);
  return backtrack(matrix, array1, array2, innerContext);
};
const lcs = {
  get
};
const ARRAY_MOVE = 3;
function arraysHaveMatchByRef(array1, array2, len1, len2) {
  for (let index1 = 0; index1 < len1; index1++) {
    const val1 = array1[index1];
    for (let index2 = 0; index2 < len2; index2++) {
      const val2 = array2[index2];
      if (index1 !== index2 && val1 === val2) {
        return true;
      }
    }
  }
  return false;
}
function matchItems(array1, array2, index1, index2, context) {
  const value1 = array1[index1];
  const value2 = array2[index2];
  if (value1 === value2) {
    return true;
  }
  if (typeof value1 !== "object" || typeof value2 !== "object") {
    return false;
  }
  const objectHash = context.objectHash;
  if (!objectHash) {
    return context.matchByPosition && index1 === index2;
  }
  context.hashCache1 = context.hashCache1 || [];
  let hash1 = context.hashCache1[index1];
  if (typeof hash1 === "undefined") {
    context.hashCache1[index1] = hash1 = objectHash(value1, index1);
  }
  if (typeof hash1 === "undefined") {
    return false;
  }
  context.hashCache2 = context.hashCache2 || [];
  let hash2 = context.hashCache2[index2];
  if (typeof hash2 === "undefined") {
    context.hashCache2[index2] = hash2 = objectHash(value2, index2);
  }
  if (typeof hash2 === "undefined") {
    return false;
  }
  return hash1 === hash2;
}
const diffFilter$3 = function arraysDiffFilter(context) {
  var _a, _b, _c, _d, _e;
  if (!context.leftIsArray) {
    return;
  }
  const matchContext = {
    objectHash: (_a = context.options) === null || _a === void 0 ? void 0 : _a.objectHash,
    matchByPosition: (_b = context.options) === null || _b === void 0 ? void 0 : _b.matchByPosition
  };
  let commonHead = 0;
  let commonTail = 0;
  let index;
  let index1;
  let index2;
  const array1 = context.left;
  const array2 = context.right;
  const len1 = array1.length;
  const len2 = array2.length;
  let child;
  if (len1 > 0 && len2 > 0 && !matchContext.objectHash && typeof matchContext.matchByPosition !== "boolean") {
    matchContext.matchByPosition = !arraysHaveMatchByRef(array1, array2, len1, len2);
  }
  while (commonHead < len1 && commonHead < len2 && matchItems(array1, array2, commonHead, commonHead, matchContext)) {
    index = commonHead;
    child = new DiffContext(array1[index], array2[index]);
    context.push(child, index);
    commonHead++;
  }
  while (commonTail + commonHead < len1 && commonTail + commonHead < len2 && matchItems(array1, array2, len1 - 1 - commonTail, len2 - 1 - commonTail, matchContext)) {
    index1 = len1 - 1 - commonTail;
    index2 = len2 - 1 - commonTail;
    child = new DiffContext(array1[index1], array2[index2]);
    context.push(child, index2);
    commonTail++;
  }
  let result2;
  if (commonHead + commonTail === len1) {
    if (len1 === len2) {
      context.setResult(void 0).exit();
      return;
    }
    result2 = result2 || {
      _t: "a"
    };
    for (index = commonHead; index < len2 - commonTail; index++) {
      result2[index] = [array2[index]];
      context.prepareDeltaResult(result2[index]);
    }
    context.setResult(result2).exit();
    return;
  }
  if (commonHead + commonTail === len2) {
    result2 = result2 || {
      _t: "a"
    };
    for (index = commonHead; index < len1 - commonTail; index++) {
      const key = `_${index}`;
      result2[key] = [array1[index], 0, 0];
      context.prepareDeltaResult(result2[key]);
    }
    context.setResult(result2).exit();
    return;
  }
  matchContext.hashCache1 = void 0;
  matchContext.hashCache2 = void 0;
  const trimmed1 = array1.slice(commonHead, len1 - commonTail);
  const trimmed2 = array2.slice(commonHead, len2 - commonTail);
  const seq = lcs.get(trimmed1, trimmed2, matchItems, matchContext);
  const removedItems = [];
  result2 = result2 || {
    _t: "a"
  };
  for (index = commonHead; index < len1 - commonTail; index++) {
    if (seq.indices1.indexOf(index - commonHead) < 0) {
      const key = `_${index}`;
      result2[key] = [array1[index], 0, 0];
      context.prepareDeltaResult(result2[key]);
      removedItems.push(index);
    }
  }
  let detectMove = true;
  if (((_c = context.options) === null || _c === void 0 ? void 0 : _c.arrays) && context.options.arrays.detectMove === false) {
    detectMove = false;
  }
  let includeValueOnMove = false;
  if ((_e = (_d = context.options) === null || _d === void 0 ? void 0 : _d.arrays) === null || _e === void 0 ? void 0 : _e.includeValueOnMove) {
    includeValueOnMove = true;
  }
  const removedItemsLength = removedItems.length;
  for (index = commonHead; index < len2 - commonTail; index++) {
    const indexOnArray2 = seq.indices2.indexOf(index - commonHead);
    if (indexOnArray2 < 0) {
      let isMove = false;
      if (detectMove && removedItemsLength > 0) {
        for (let removeItemIndex1 = 0; removeItemIndex1 < removedItemsLength; removeItemIndex1++) {
          index1 = removedItems[removeItemIndex1];
          const resultItem = index1 === void 0 ? void 0 : result2[`_${index1}`];
          if (index1 !== void 0 && resultItem && matchItems(trimmed1, trimmed2, index1 - commonHead, index - commonHead, matchContext)) {
            resultItem.splice(1, 2, index, ARRAY_MOVE);
            resultItem.splice(1, 2, index, ARRAY_MOVE);
            if (!includeValueOnMove) {
              resultItem[0] = "";
            }
            index2 = index;
            child = new DiffContext(array1[index1], array2[index2]);
            context.push(child, index2);
            removedItems.splice(removeItemIndex1, 1);
            isMove = true;
            break;
          }
        }
      }
      if (!isMove) {
        result2[index] = [array2[index]];
        context.prepareDeltaResult(result2[index]);
      }
    } else {
      if (seq.indices1[indexOnArray2] === void 0) {
        throw new Error(`Invalid indexOnArray2: ${indexOnArray2}, seq.indices1: ${seq.indices1}`);
      }
      index1 = seq.indices1[indexOnArray2] + commonHead;
      if (seq.indices2[indexOnArray2] === void 0) {
        throw new Error(`Invalid indexOnArray2: ${indexOnArray2}, seq.indices2: ${seq.indices2}`);
      }
      index2 = seq.indices2[indexOnArray2] + commonHead;
      child = new DiffContext(array1[index1], array2[index2]);
      context.push(child, index2);
    }
  }
  context.setResult(result2).exit();
};
diffFilter$3.filterName = "arrays";
const compare = {
  numerically(a, b) {
    return a - b;
  },
  numericallyBy(name) {
    return (a, b) => a[name] - b[name];
  }
};
const patchFilter$3 = function nestedPatchFilter(context) {
  var _a;
  if (!context.nested) {
    return;
  }
  const nestedDelta = context.delta;
  if (nestedDelta._t !== "a") {
    return;
  }
  let index;
  let index1;
  const delta = nestedDelta;
  const array = context.left;
  let toRemove = [];
  let toInsert = [];
  const toModify = [];
  for (index in delta) {
    if (index !== "_t") {
      if (index[0] === "_") {
        const removedOrMovedIndex = index;
        if (delta[removedOrMovedIndex] !== void 0 && (delta[removedOrMovedIndex][2] === 0 || delta[removedOrMovedIndex][2] === ARRAY_MOVE)) {
          toRemove.push(Number.parseInt(index.slice(1), 10));
        } else {
          throw new Error(`only removal or move can be applied at original array indices, invalid diff type: ${(_a = delta[removedOrMovedIndex]) === null || _a === void 0 ? void 0 : _a[2]}`);
        }
      } else {
        const numberIndex = index;
        if (delta[numberIndex].length === 1) {
          toInsert.push({
            index: Number.parseInt(numberIndex, 10),
            value: delta[numberIndex][0]
          });
        } else {
          toModify.push({
            index: Number.parseInt(numberIndex, 10),
            delta: delta[numberIndex]
          });
        }
      }
    }
  }
  toRemove = toRemove.sort(compare.numerically);
  for (index = toRemove.length - 1; index >= 0; index--) {
    index1 = toRemove[index];
    if (index1 === void 0)
      continue;
    const indexDiff = delta[`_${index1}`];
    const removedValue = array.splice(index1, 1)[0];
    if ((indexDiff === null || indexDiff === void 0 ? void 0 : indexDiff[2]) === ARRAY_MOVE) {
      toInsert.push({
        index: indexDiff[1],
        value: removedValue
      });
    }
  }
  toInsert = toInsert.sort(compare.numericallyBy("index"));
  const toInsertLength = toInsert.length;
  for (index = 0; index < toInsertLength; index++) {
    const insertion = toInsert[index];
    if (insertion === void 0)
      continue;
    array.splice(insertion.index, 0, insertion.value);
  }
  const toModifyLength = toModify.length;
  if (toModifyLength > 0) {
    for (index = 0; index < toModifyLength; index++) {
      const modification = toModify[index];
      if (modification === void 0)
        continue;
      const child = new PatchContext(array[modification.index], modification.delta);
      context.push(child, modification.index);
    }
  }
  if (!context.children) {
    context.setResult(array).exit();
    return;
  }
  context.exit();
};
patchFilter$3.filterName = "arrays";
const collectChildrenPatchFilter$1 = function collectChildrenPatchFilter(context) {
  if (!context || !context.children) {
    return;
  }
  const deltaWithChildren = context.delta;
  if (deltaWithChildren._t !== "a") {
    return;
  }
  const array = context.left;
  const length = context.children.length;
  for (let index = 0; index < length; index++) {
    const child = context.children[index];
    if (child === void 0)
      continue;
    const arrayIndex = child.childName;
    array[arrayIndex] = child.result;
  }
  context.setResult(array).exit();
};
collectChildrenPatchFilter$1.filterName = "arraysCollectChildren";
const reverseFilter$3 = function arraysReverseFilter(context) {
  if (!context.nested) {
    const nonNestedDelta = context.delta;
    if (nonNestedDelta[2] === ARRAY_MOVE) {
      const arrayMoveDelta = nonNestedDelta;
      context.newName = `_${arrayMoveDelta[1]}`;
      context.setResult([
        arrayMoveDelta[0],
        Number.parseInt(context.childName.substring(1), 10),
        ARRAY_MOVE
      ]).exit();
    }
    return;
  }
  const nestedDelta = context.delta;
  if (nestedDelta._t !== "a") {
    return;
  }
  const arrayDelta = nestedDelta;
  for (const name in arrayDelta) {
    if (name === "_t") {
      continue;
    }
    const child = new ReverseContext(arrayDelta[name]);
    context.push(child, name);
  }
  context.exit();
};
reverseFilter$3.filterName = "arrays";
const reverseArrayDeltaIndex = (delta, index, itemDelta) => {
  if (typeof index === "string" && index[0] === "_") {
    return Number.parseInt(index.substring(1), 10);
  }
  if (Array.isArray(itemDelta) && itemDelta[2] === 0) {
    return `_${index}`;
  }
  let reverseIndex = +index;
  for (const deltaIndex in delta) {
    const deltaItem = delta[deltaIndex];
    if (Array.isArray(deltaItem)) {
      if (deltaItem[2] === ARRAY_MOVE) {
        const moveFromIndex = Number.parseInt(deltaIndex.substring(1), 10);
        const moveToIndex = deltaItem[1];
        if (moveToIndex === +index) {
          return moveFromIndex;
        }
        if (moveFromIndex <= reverseIndex && moveToIndex > reverseIndex) {
          reverseIndex++;
        } else if (moveFromIndex >= reverseIndex && moveToIndex < reverseIndex) {
          reverseIndex--;
        }
      } else if (deltaItem[2] === 0) {
        const deleteIndex = Number.parseInt(deltaIndex.substring(1), 10);
        if (deleteIndex <= reverseIndex) {
          reverseIndex++;
        }
      } else if (deltaItem.length === 1 && Number.parseInt(deltaIndex, 10) <= reverseIndex) {
        reverseIndex--;
      }
    }
  }
  return reverseIndex;
};
const collectChildrenReverseFilter$1 = (context) => {
  if (!context || !context.children) {
    return;
  }
  const deltaWithChildren = context.delta;
  if (deltaWithChildren._t !== "a") {
    return;
  }
  const arrayDelta = deltaWithChildren;
  const length = context.children.length;
  const delta = {
    _t: "a"
  };
  for (let index = 0; index < length; index++) {
    const child = context.children[index];
    if (child === void 0)
      continue;
    let name = child.newName;
    if (typeof name === "undefined") {
      if (child.childName === void 0) {
        throw new Error("child.childName is undefined");
      }
      name = reverseArrayDeltaIndex(arrayDelta, child.childName, child.result);
    }
    if (delta[name] !== child.result) {
      delta[name] = child.result;
    }
  }
  context.setResult(delta).exit();
};
collectChildrenReverseFilter$1.filterName = "arraysCollectChildren";
const diffFilter$2 = function datesDiffFilter(context) {
  if (context.left instanceof Date) {
    if (context.right instanceof Date) {
      if (context.left.getTime() !== context.right.getTime()) {
        context.setResult([context.left, context.right]);
      } else {
        context.setResult(void 0);
      }
    } else {
      context.setResult([context.left, context.right]);
    }
    context.exit();
  } else if (context.right instanceof Date) {
    context.setResult([context.left, context.right]).exit();
  }
};
diffFilter$2.filterName = "dates";
const collectChildrenDiffFilter = (context) => {
  if (!context || !context.children) {
    return;
  }
  const length = context.children.length;
  let result2 = context.result;
  for (let index = 0; index < length; index++) {
    const child = context.children[index];
    if (child === void 0)
      continue;
    if (typeof child.result === "undefined") {
      continue;
    }
    result2 = result2 || {};
    if (child.childName === void 0) {
      throw new Error("diff child.childName is undefined");
    }
    result2[child.childName] = child.result;
  }
  if (result2 && context.leftIsArray) {
    result2._t = "a";
  }
  context.setResult(result2).exit();
};
collectChildrenDiffFilter.filterName = "collectChildren";
const objectsDiffFilter = (context) => {
  var _a;
  if (context.leftIsArray || context.leftType !== "object") {
    return;
  }
  const left = context.left;
  const right = context.right;
  const propertyFilter = (_a = context.options) === null || _a === void 0 ? void 0 : _a.propertyFilter;
  for (const name in left) {
    if (!Object.prototype.hasOwnProperty.call(left, name)) {
      continue;
    }
    if (propertyFilter && !propertyFilter(name, context)) {
      continue;
    }
    const child = new DiffContext(left[name], right[name]);
    context.push(child, name);
  }
  for (const name in right) {
    if (!Object.prototype.hasOwnProperty.call(right, name)) {
      continue;
    }
    if (propertyFilter && !propertyFilter(name, context)) {
      continue;
    }
    if (typeof left[name] === "undefined") {
      const child = new DiffContext(void 0, right[name]);
      context.push(child, name);
    }
  }
  if (!context.children || context.children.length === 0) {
    context.setResult(void 0).exit();
    return;
  }
  context.exit();
};
objectsDiffFilter.filterName = "objects";
const patchFilter$2 = function nestedPatchFilter2(context) {
  if (!context.nested) {
    return;
  }
  const nestedDelta = context.delta;
  if (nestedDelta._t) {
    return;
  }
  const objectDelta = nestedDelta;
  for (const name in objectDelta) {
    const child = new PatchContext(context.left[name], objectDelta[name]);
    context.push(child, name);
  }
  context.exit();
};
patchFilter$2.filterName = "objects";
const collectChildrenPatchFilter2 = function collectChildrenPatchFilter3(context) {
  if (!context || !context.children) {
    return;
  }
  const deltaWithChildren = context.delta;
  if (deltaWithChildren._t) {
    return;
  }
  const object = context.left;
  const length = context.children.length;
  for (let index = 0; index < length; index++) {
    const child = context.children[index];
    if (child === void 0)
      continue;
    const property = child.childName;
    if (Object.prototype.hasOwnProperty.call(context.left, property) && child.result === void 0) {
      delete object[property];
    } else if (object[property] !== child.result) {
      object[property] = child.result;
    }
  }
  context.setResult(object).exit();
};
collectChildrenPatchFilter2.filterName = "collectChildren";
const reverseFilter$2 = function nestedReverseFilter(context) {
  if (!context.nested) {
    return;
  }
  const nestedDelta = context.delta;
  if (nestedDelta._t) {
    return;
  }
  const objectDelta = context.delta;
  for (const name in objectDelta) {
    const child = new ReverseContext(objectDelta[name]);
    context.push(child, name);
  }
  context.exit();
};
reverseFilter$2.filterName = "objects";
const collectChildrenReverseFilter = (context) => {
  if (!context || !context.children) {
    return;
  }
  const deltaWithChildren = context.delta;
  if (deltaWithChildren._t) {
    return;
  }
  const length = context.children.length;
  const delta = {};
  for (let index = 0; index < length; index++) {
    const child = context.children[index];
    if (child === void 0)
      continue;
    const property = child.childName;
    if (delta[property] !== child.result) {
      delta[property] = child.result;
    }
  }
  context.setResult(delta).exit();
};
collectChildrenReverseFilter.filterName = "collectChildren";
const TEXT_DIFF = 2;
const DEFAULT_MIN_LENGTH = 60;
let cachedDiffPatch = null;
function getDiffMatchPatch(options, required) {
  var _a;
  if (!cachedDiffPatch) {
    let instance;
    if ((_a = options === null || options === void 0 ? void 0 : options.textDiff) === null || _a === void 0 ? void 0 : _a.diffMatchPatch) {
      instance = new options.textDiff.diffMatchPatch();
    } else {
      if (!required) {
        return null;
      }
      const error2 = new Error("The diff-match-patch library was not provided. Pass the library in through the options or use the `jsondiffpatch/with-text-diffs` entry-point.");
      error2.diff_match_patch_not_found = true;
      throw error2;
    }
    cachedDiffPatch = {
      diff: (txt1, txt2) => instance.patch_toText(instance.patch_make(txt1, txt2)),
      patch: (txt1, patch) => {
        const results = instance.patch_apply(instance.patch_fromText(patch), txt1);
        for (const resultOk of results[1]) {
          if (!resultOk) {
            const error2 = new Error("text patch failed");
            error2.textPatchFailed = true;
            throw error2;
          }
        }
        return results[0];
      }
    };
  }
  return cachedDiffPatch;
}
const diffFilter$1 = function textsDiffFilter(context) {
  var _a, _b;
  if (context.leftType !== "string") {
    return;
  }
  const left = context.left;
  const right = context.right;
  const minLength = ((_b = (_a = context.options) === null || _a === void 0 ? void 0 : _a.textDiff) === null || _b === void 0 ? void 0 : _b.minLength) || DEFAULT_MIN_LENGTH;
  if (left.length < minLength || right.length < minLength) {
    context.setResult([left, right]).exit();
    return;
  }
  const diffMatchPatch = getDiffMatchPatch(context.options);
  if (!diffMatchPatch) {
    context.setResult([left, right]).exit();
    return;
  }
  const diff2 = diffMatchPatch.diff;
  context.setResult([diff2(left, right), 0, TEXT_DIFF]).exit();
};
diffFilter$1.filterName = "texts";
const patchFilter$1 = function textsPatchFilter(context) {
  if (context.nested) {
    return;
  }
  const nonNestedDelta = context.delta;
  if (nonNestedDelta[2] !== TEXT_DIFF) {
    return;
  }
  const textDiffDelta = nonNestedDelta;
  const patch = getDiffMatchPatch(context.options, true).patch;
  context.setResult(patch(context.left, textDiffDelta[0])).exit();
};
patchFilter$1.filterName = "texts";
const textDeltaReverse = (delta) => {
  var _a, _b, _c;
  const headerRegex = /^@@ +-(\d+),(\d+) +\+(\d+),(\d+) +@@$/;
  const lines = delta.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line === void 0)
      continue;
    const lineStart = line.slice(0, 1);
    if (lineStart === "@") {
      const header = headerRegex.exec(line);
      if (header !== null) {
        const lineHeader = i;
        lines[lineHeader] = `@@ -${header[3]},${header[4]} +${header[1]},${header[2]} @@`;
      }
    } else if (lineStart === "+") {
      lines[i] = `-${(_a = lines[i]) === null || _a === void 0 ? void 0 : _a.slice(1)}`;
      if (((_b = lines[i - 1]) === null || _b === void 0 ? void 0 : _b.slice(0, 1)) === "+") {
        const lineTmp = lines[i];
        lines[i] = lines[i - 1];
        lines[i - 1] = lineTmp;
      }
    } else if (lineStart === "-") {
      lines[i] = `+${(_c = lines[i]) === null || _c === void 0 ? void 0 : _c.slice(1)}`;
    }
  }
  return lines.join("\n");
};
const reverseFilter$1 = function textsReverseFilter(context) {
  if (context.nested) {
    return;
  }
  const nonNestedDelta = context.delta;
  if (nonNestedDelta[2] !== TEXT_DIFF) {
    return;
  }
  const textDiffDelta = nonNestedDelta;
  context.setResult([textDeltaReverse(textDiffDelta[0]), 0, TEXT_DIFF]).exit();
};
reverseFilter$1.filterName = "texts";
const diffFilter = function trivialMatchesDiffFilter(context) {
  if (context.left === context.right) {
    context.setResult(void 0).exit();
    return;
  }
  if (typeof context.left === "undefined") {
    if (typeof context.right === "function") {
      throw new Error("functions are not supported");
    }
    context.setResult([context.right]).exit();
    return;
  }
  if (typeof context.right === "undefined") {
    context.setResult([context.left, 0, 0]).exit();
    return;
  }
  if (typeof context.left === "function" || typeof context.right === "function") {
    throw new Error("functions are not supported");
  }
  context.leftType = context.left === null ? "null" : typeof context.left;
  context.rightType = context.right === null ? "null" : typeof context.right;
  if (context.leftType !== context.rightType) {
    context.setResult([context.left, context.right]).exit();
    return;
  }
  if (context.leftType === "boolean" || context.leftType === "number") {
    context.setResult([context.left, context.right]).exit();
    return;
  }
  if (context.leftType === "object") {
    context.leftIsArray = Array.isArray(context.left);
  }
  if (context.rightType === "object") {
    context.rightIsArray = Array.isArray(context.right);
  }
  if (context.leftIsArray !== context.rightIsArray) {
    context.setResult([context.left, context.right]).exit();
    return;
  }
  if (context.left instanceof RegExp) {
    if (context.right instanceof RegExp) {
      context.setResult([context.left.toString(), context.right.toString()]).exit();
    } else {
      context.setResult([context.left, context.right]).exit();
    }
  }
};
diffFilter.filterName = "trivial";
const patchFilter = function trivialMatchesPatchFilter(context) {
  if (typeof context.delta === "undefined") {
    context.setResult(context.left).exit();
    return;
  }
  context.nested = !Array.isArray(context.delta);
  if (context.nested) {
    return;
  }
  const nonNestedDelta = context.delta;
  if (nonNestedDelta.length === 1) {
    context.setResult(nonNestedDelta[0]).exit();
    return;
  }
  if (nonNestedDelta.length === 2) {
    if (context.left instanceof RegExp) {
      const regexArgs = /^\/(.*)\/([gimyu]+)$/.exec(nonNestedDelta[1]);
      if (regexArgs === null || regexArgs === void 0 ? void 0 : regexArgs[1]) {
        context.setResult(new RegExp(regexArgs[1], regexArgs[2])).exit();
        return;
      }
    }
    context.setResult(nonNestedDelta[1]).exit();
    return;
  }
  if (nonNestedDelta.length === 3 && nonNestedDelta[2] === 0) {
    context.setResult(void 0).exit();
  }
};
patchFilter.filterName = "trivial";
const reverseFilter = function trivialReferseFilter(context) {
  if (typeof context.delta === "undefined") {
    context.setResult(context.delta).exit();
    return;
  }
  context.nested = !Array.isArray(context.delta);
  if (context.nested) {
    return;
  }
  const nonNestedDelta = context.delta;
  if (nonNestedDelta.length === 1) {
    context.setResult([nonNestedDelta[0], 0, 0]).exit();
    return;
  }
  if (nonNestedDelta.length === 2) {
    context.setResult([nonNestedDelta[1], nonNestedDelta[0]]).exit();
    return;
  }
  if (nonNestedDelta.length === 3 && nonNestedDelta[2] === 0) {
    context.setResult([nonNestedDelta[0]]).exit();
  }
};
reverseFilter.filterName = "trivial";
class DiffPatcher {
  constructor(options) {
    this.processor = new Processor(options);
    this.processor.pipe(new Pipe("diff").append(collectChildrenDiffFilter, diffFilter, diffFilter$2, diffFilter$1, objectsDiffFilter, diffFilter$3).shouldHaveResult());
    this.processor.pipe(new Pipe("patch").append(collectChildrenPatchFilter2, collectChildrenPatchFilter$1, patchFilter, patchFilter$1, patchFilter$2, patchFilter$3).shouldHaveResult());
    this.processor.pipe(new Pipe("reverse").append(collectChildrenReverseFilter, collectChildrenReverseFilter$1, reverseFilter, reverseFilter$1, reverseFilter$2, reverseFilter$3).shouldHaveResult());
  }
  options(options) {
    return this.processor.options(options);
  }
  diff(left, right) {
    return this.processor.process(new DiffContext(left, right));
  }
  patch(left, delta) {
    return this.processor.process(new PatchContext(left, delta));
  }
  reverse(delta) {
    return this.processor.process(new ReverseContext(delta));
  }
  unpatch(right, delta) {
    return this.patch(right, this.reverse(delta));
  }
  clone(value2) {
    return clone(value2);
  }
}
let defaultInstance$1;
function diff$1(left, right) {
  if (!defaultInstance$1) {
    defaultInstance$1 = new DiffPatcher();
  }
  return defaultInstance$1.diff(left, right);
}
class BaseFormatter {
  format(delta, left) {
    const context = {};
    this.prepareContext(context);
    const preparedContext = context;
    this.recurse(preparedContext, delta, left);
    return this.finalize(preparedContext);
  }
  prepareContext(context) {
    context.buffer = [];
    context.out = function(...args) {
      if (!this.buffer) {
        throw new Error("context buffer is not initialized");
      }
      this.buffer.push(...args);
    };
  }
  typeFormattterNotFound(_context, deltaType) {
    throw new Error(`cannot format delta type: ${deltaType}`);
  }
  /* eslint-disable @typescript-eslint/no-unused-vars */
  typeFormattterErrorFormatter(_context, _err, _delta, _leftValue, _key, _leftKey, _movedFrom) {
  }
  /* eslint-enable @typescript-eslint/no-unused-vars */
  finalize({ buffer }) {
    if (Array.isArray(buffer)) {
      return buffer.join("");
    }
    return "";
  }
  recurse(context, delta, left, key, leftKey, movedFrom, isLast) {
    const useMoveOriginHere = delta && movedFrom;
    const leftValue = useMoveOriginHere ? movedFrom.value : left;
    if (typeof delta === "undefined" && typeof key === "undefined") {
      return void 0;
    }
    const type = this.getDeltaType(delta, movedFrom);
    const nodeType = type === "node" ? delta._t === "a" ? "array" : "object" : "";
    if (typeof key !== "undefined") {
      this.nodeBegin(context, key, leftKey, type, nodeType, isLast !== null && isLast !== void 0 ? isLast : false);
    } else {
      this.rootBegin(context, type, nodeType);
    }
    let typeFormattter;
    try {
      typeFormattter = type !== "unknown" ? this[`format_${type}`] : this.typeFormattterNotFound(context, type);
      typeFormattter.call(this, context, delta, leftValue, key, leftKey, movedFrom);
    } catch (err) {
      this.typeFormattterErrorFormatter(context, err, delta, leftValue, key, leftKey, movedFrom);
      if (typeof console !== "undefined" && console.error) {
        console.error(err.stack);
      }
    }
    if (typeof key !== "undefined") {
      this.nodeEnd(context, key, leftKey, type, nodeType, isLast !== null && isLast !== void 0 ? isLast : false);
    } else {
      this.rootEnd(context, type, nodeType);
    }
  }
  formatDeltaChildren(context, delta, left) {
    this.forEachDeltaKey(delta, left, (key, leftKey, movedFrom, isLast) => {
      this.recurse(context, delta[key], left ? left[leftKey] : void 0, key, leftKey, movedFrom, isLast);
    });
  }
  forEachDeltaKey(delta, left, fn) {
    const keys = [];
    const arrayKeys = delta._t === "a";
    if (!arrayKeys) {
      const deltaKeys = Object.keys(delta);
      if (typeof left === "object" && left !== null) {
        keys.push(...Object.keys(left));
      }
      for (const key of deltaKeys) {
        if (keys.indexOf(key) >= 0)
          continue;
        keys.push(key);
      }
      for (let index = 0; index < keys.length; index++) {
        const key = keys[index];
        if (key === void 0)
          continue;
        const isLast = index === keys.length - 1;
        fn(
          // for object diff, the delta key and left key are the same
          key,
          key,
          // there's no "move" in object diff
          void 0,
          isLast
        );
      }
      return;
    }
    const movedFrom = {};
    for (const key in delta) {
      if (Object.prototype.hasOwnProperty.call(delta, key)) {
        const value2 = delta[key];
        if (Array.isArray(value2) && value2[2] === 3) {
          const movedDelta = value2;
          movedFrom[movedDelta[1]] = Number.parseInt(key.substring(1));
        }
      }
    }
    const arrayDelta = delta;
    let leftIndex = 0;
    let rightIndex = 0;
    const leftArray = Array.isArray(left) ? left : void 0;
    const leftLength = leftArray ? leftArray.length : (
      // if we don't have the original array,
      // use a length that ensures we'll go thru all delta keys
      Object.keys(arrayDelta).reduce((max, key) => {
        if (key === "_t")
          return max;
        const isLeftKey = key.substring(0, 1) === "_";
        if (isLeftKey) {
          const itemDelta = arrayDelta[key];
          const leftIndex3 = Number.parseInt(key.substring(1));
          const rightIndex3 = Array.isArray(itemDelta) && itemDelta.length >= 3 && itemDelta[2] === 3 ? itemDelta[1] : void 0;
          const maxIndex2 = Math.max(leftIndex3, rightIndex3 !== null && rightIndex3 !== void 0 ? rightIndex3 : 0);
          return maxIndex2 > max ? maxIndex2 : max;
        }
        const rightIndex2 = Number.parseInt(key);
        const leftIndex2 = movedFrom[rightIndex2];
        const maxIndex = Math.max(leftIndex2 !== null && leftIndex2 !== void 0 ? leftIndex2 : 0, rightIndex2 !== null && rightIndex2 !== void 0 ? rightIndex2 : 0);
        return maxIndex > max ? maxIndex : max;
      }, 0) + 1
    );
    let rightLength = leftLength;
    let previousFnArgs;
    const addKey = (...args) => {
      if (previousFnArgs) {
        fn(...previousFnArgs);
      }
      previousFnArgs = args;
    };
    const flushLastKey = () => {
      if (!previousFnArgs) {
        return;
      }
      fn(previousFnArgs[0], previousFnArgs[1], previousFnArgs[2], true);
    };
    while (leftIndex < leftLength || rightIndex < rightLength || `${rightIndex}` in arrayDelta) {
      let hasDelta = false;
      const leftIndexKey = `_${leftIndex}`;
      const rightIndexKey = `${rightIndex}`;
      const movedFromIndex = rightIndex in movedFrom ? movedFrom[rightIndex] : void 0;
      if (leftIndexKey in arrayDelta) {
        hasDelta = true;
        const itemDelta = arrayDelta[leftIndexKey];
        addKey(leftIndexKey, movedFromIndex !== null && movedFromIndex !== void 0 ? movedFromIndex : leftIndex, movedFromIndex ? {
          key: `_${movedFromIndex}`,
          value: leftArray ? leftArray[movedFromIndex] : void 0
        } : void 0, false);
        if (Array.isArray(itemDelta)) {
          if (itemDelta[2] === 0) {
            rightLength--;
            leftIndex++;
          } else if (itemDelta[2] === 3) {
            leftIndex++;
          } else {
            leftIndex++;
          }
        } else {
          leftIndex++;
        }
      }
      if (rightIndexKey in arrayDelta) {
        hasDelta = true;
        const itemDelta = arrayDelta[rightIndexKey];
        const isItemAdded = Array.isArray(itemDelta) && itemDelta.length === 1;
        addKey(rightIndexKey, movedFromIndex !== null && movedFromIndex !== void 0 ? movedFromIndex : leftIndex, movedFromIndex ? {
          key: `_${movedFromIndex}`,
          value: leftArray ? leftArray[movedFromIndex] : void 0
        } : void 0, false);
        if (isItemAdded) {
          rightLength++;
          rightIndex++;
        } else if (movedFromIndex === void 0) {
          leftIndex++;
          rightIndex++;
        } else {
          rightIndex++;
        }
      }
      if (!hasDelta) {
        if (leftArray && movedFromIndex === void 0 || this.includeMoveDestinations !== false) {
          addKey(rightIndexKey, movedFromIndex !== null && movedFromIndex !== void 0 ? movedFromIndex : leftIndex, movedFromIndex ? {
            key: `_${movedFromIndex}`,
            value: leftArray ? leftArray[movedFromIndex] : void 0
          } : void 0, false);
        }
        if (movedFromIndex !== void 0) {
          rightIndex++;
        } else {
          leftIndex++;
          rightIndex++;
        }
      }
    }
    flushLastKey();
  }
  getDeltaType(delta, movedFrom) {
    if (typeof delta === "undefined") {
      if (typeof movedFrom !== "undefined") {
        return "movedestination";
      }
      return "unchanged";
    }
    if (Array.isArray(delta)) {
      if (delta.length === 1) {
        return "added";
      }
      if (delta.length === 2) {
        return "modified";
      }
      if (delta.length === 3 && delta[2] === 0) {
        return "deleted";
      }
      if (delta.length === 3 && delta[2] === 2) {
        return "textdiff";
      }
      if (delta.length === 3 && delta[2] === 3) {
        return "moved";
      }
    } else if (typeof delta === "object") {
      return "node";
    }
    return "unknown";
  }
  parseTextDiff(value2) {
    var _a;
    const output = [];
    const lines = value2.split("\n@@ ");
    for (const line of lines) {
      const lineOutput = {
        pieces: []
      };
      const location = (_a = /^(?:@@ )?[-+]?(\d+),(\d+)/.exec(line)) === null || _a === void 0 ? void 0 : _a.slice(1);
      if (!location) {
        throw new Error("invalid text diff format");
      }
      assertArrayHasAtLeast2(location);
      lineOutput.location = {
        line: location[0],
        chr: location[1]
      };
      const pieces = line.split("\n").slice(1);
      for (let pieceIndex = 0, piecesLength = pieces.length; pieceIndex < piecesLength; pieceIndex++) {
        const piece = pieces[pieceIndex];
        if (piece === void 0 || !piece.length) {
          continue;
        }
        const pieceOutput = {
          type: "context"
        };
        if (piece.substring(0, 1) === "+") {
          pieceOutput.type = "added";
        } else if (piece.substring(0, 1) === "-") {
          pieceOutput.type = "deleted";
        }
        pieceOutput.text = piece.slice(1);
        lineOutput.pieces.push(pieceOutput);
      }
      output.push(lineOutput);
    }
    return output;
  }
}
class HtmlFormatter extends BaseFormatter {
  typeFormattterErrorFormatter(context, err) {
    const message2 = typeof err === "object" && err !== null && "message" in err && typeof err.message === "string" ? err.message : String(err);
    context.out(`<pre class="jsondiffpatch-error">${htmlEscape(message2)}</pre>`);
  }
  formatValue(context, value2) {
    const valueAsHtml = typeof value2 === "undefined" ? "undefined" : htmlEscape(JSON.stringify(value2, null, 2));
    context.out(`<pre>${valueAsHtml}</pre>`);
  }
  formatTextDiffString(context, value2) {
    const lines = this.parseTextDiff(value2);
    context.out('<ul class="jsondiffpatch-textdiff">');
    for (let i = 0, l = lines.length; i < l; i++) {
      const line = lines[i];
      if (line === void 0)
        return;
      context.out(`<li><div class="jsondiffpatch-textdiff-location"><span class="jsondiffpatch-textdiff-line-number">${line.location.line}</span><span class="jsondiffpatch-textdiff-char">${line.location.chr}</span></div><div class="jsondiffpatch-textdiff-line">`);
      const pieces = line.pieces;
      for (let pieceIndex = 0, piecesLength = pieces.length; pieceIndex < piecesLength; pieceIndex++) {
        const piece = pieces[pieceIndex];
        if (piece === void 0)
          return;
        context.out(`<span class="jsondiffpatch-textdiff-${piece.type}">${htmlEscape(decodeURI(piece.text))}</span>`);
      }
      context.out("</div></li>");
    }
    context.out("</ul>");
  }
  rootBegin(context, type, nodeType) {
    const nodeClass = `jsondiffpatch-${type}${nodeType ? ` jsondiffpatch-child-node-type-${nodeType}` : ""}`;
    context.out(`<div class="jsondiffpatch-delta ${nodeClass}">`);
  }
  rootEnd(context) {
    context.out(`</div>${context.hasArrows ? `<script type="text/javascript">setTimeout(${adjustArrows.toString()},10);<\/script>` : ""}`);
  }
  nodeBegin(context, key, leftKey, type, nodeType) {
    const nodeClass = `jsondiffpatch-${type}${nodeType ? ` jsondiffpatch-child-node-type-${nodeType}` : ""}`;
    const label2 = typeof leftKey === "number" && key.substring(0, 1) === "_" ? key.substring(1) : key;
    context.out(`<li class="${nodeClass}" data-key="${htmlEscape(key)}"><div class="jsondiffpatch-property-name">${htmlEscape(label2)}</div>`);
  }
  nodeEnd(context) {
    context.out("</li>");
  }
  format_unchanged(context, _delta, left) {
    if (typeof left === "undefined") {
      return;
    }
    context.out('<div class="jsondiffpatch-value">');
    this.formatValue(context, left);
    context.out("</div>");
  }
  format_movedestination(context, _delta, left) {
    if (typeof left === "undefined") {
      return;
    }
    context.out('<div class="jsondiffpatch-value">');
    this.formatValue(context, left);
    context.out("</div>");
  }
  format_node(context, delta, left) {
    const nodeType = delta._t === "a" ? "array" : "object";
    context.out(`<ul class="jsondiffpatch-node jsondiffpatch-node-type-${nodeType}">`);
    this.formatDeltaChildren(context, delta, left);
    context.out("</ul>");
  }
  format_added(context, delta) {
    context.out('<div class="jsondiffpatch-value">');
    this.formatValue(context, delta[0]);
    context.out("</div>");
  }
  format_modified(context, delta) {
    context.out('<div class="jsondiffpatch-value jsondiffpatch-left-value">');
    this.formatValue(context, delta[0]);
    context.out('</div><div class="jsondiffpatch-value jsondiffpatch-right-value">');
    this.formatValue(context, delta[1]);
    context.out("</div>");
  }
  format_deleted(context, delta) {
    context.out('<div class="jsondiffpatch-value">');
    this.formatValue(context, delta[0]);
    context.out("</div>");
  }
  format_moved(context, delta) {
    context.out('<div class="jsondiffpatch-value">');
    this.formatValue(context, delta[0]);
    context.out(`</div><div class="jsondiffpatch-moved-destination">${delta[1]}</div>`);
    context.out(
      /* jshint multistr: true */
      `<div class="jsondiffpatch-arrow" style="position: relative; left: -34px;">
          <svg width="30" height="60" style="position: absolute; display: none;">
          <defs>
              <marker id="markerArrow" markerWidth="8" markerHeight="8"
                 refx="2" refy="4" stroke="#88f"
                     orient="auto" markerUnits="userSpaceOnUse">
                  <path d="M1,1 L1,7 L7,4 L1,1" style="fill: #339;" />
              </marker>
          </defs>
          <path d="M30,0 Q-10,25 26,50"
            style="stroke: #88f; stroke-width: 2px; fill: none; stroke-opacity: 0.5; marker-end: url(#markerArrow);"
          ></path>
          </svg>
      </div>`
    );
    context.hasArrows = true;
  }
  format_textdiff(context, delta) {
    context.out('<div class="jsondiffpatch-value">');
    this.formatTextDiffString(context, delta[0]);
    context.out("</div>");
  }
}
function htmlEscape(value2) {
  if (typeof value2 === "number")
    return value2;
  let html = String(value2);
  const replacements = [
    [/&/g, "&amp;"],
    [/</g, "&lt;"],
    [/>/g, "&gt;"],
    [/'/g, "&apos;"],
    [/"/g, "&quot;"]
  ];
  for (const replacement of replacements) {
    html = html.replace(replacement[0], replacement[1]);
  }
  return html;
}
const adjustArrows = function jsondiffpatchHtmlFormatterAdjustArrows(nodeArg) {
  const node2 = nodeArg || document;
  const getElementText = ({ textContent, innerText }) => textContent || innerText;
  const eachByQuery = (el, query, fn) => {
    const elems = el.querySelectorAll(query);
    for (let i = 0, l = elems.length; i < l; i++) {
      fn(elems[i]);
    }
  };
  const eachChildren = ({ children }, fn) => {
    for (let i = 0, l = children.length; i < l; i++) {
      const element = children[i];
      if (!element)
        continue;
      fn(element, i);
    }
  };
  eachByQuery(node2, ".jsondiffpatch-arrow", ({ parentNode, children, style }) => {
    const arrowParent = parentNode;
    const svg = children[0];
    const path = svg.children[1];
    svg.style.display = "none";
    const moveDestinationElem = arrowParent.querySelector(".jsondiffpatch-moved-destination");
    if (!(moveDestinationElem instanceof HTMLElement))
      return;
    const destination = getElementText(moveDestinationElem);
    const container2 = arrowParent.parentNode;
    if (!container2)
      return;
    let destinationElem;
    eachChildren(container2, (child) => {
      if (child.getAttribute("data-key") === destination) {
        destinationElem = child;
      }
    });
    if (!destinationElem) {
      return;
    }
    try {
      const distance = destinationElem.offsetTop - arrowParent.offsetTop;
      svg.setAttribute("height", `${Math.abs(distance) + 6}`);
      style.top = `${-8 + (distance > 0 ? 0 : distance)}px`;
      const curve = distance > 0 ? `M30,0 Q-10,${Math.round(distance / 2)} 26,${distance - 4}` : `M30,${-distance} Q-10,${Math.round(-distance / 2)} 26,4`;
      path.setAttribute("d", curve);
      svg.style.display = "";
    } catch (err) {
      console.debug(`[jsondiffpatch] error adjusting arrows: ${err}`);
    }
  });
};
let defaultInstance;
function format(delta, left) {
  if (!defaultInstance) {
    defaultInstance = new HtmlFormatter();
  }
  return defaultInstance.format(delta, left);
}
const StateDiffView = ({
  before,
  after,
  className
}) => {
  const state_diff = diff$1(sanitizeKeys(before), sanitizeKeys(after));
  const html_result = format(state_diff) || "Unable to render differences";
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    "div",
    {
      dangerouslySetInnerHTML: { __html: unescapeNewlines(html_result) },
      className: clsx(className)
    }
  );
};
function unescapeNewlines(obj) {
  if (typeof obj === "string") {
    return obj.replace(/\\n/g, "\n");
  }
  if (obj === null || typeof obj !== "object") {
    return obj;
  }
  if (Array.isArray(obj)) {
    return obj.map((item) => unescapeNewlines(item));
  }
  return Object.fromEntries(
    Object.entries(obj).map(([key, value2]) => [
      key,
      unescapeNewlines(value2)
    ])
  );
}
function sanitizeKeys(obj) {
  if (typeof obj !== "object" || obj === null) {
    return obj;
  }
  if (Array.isArray(obj)) {
    return obj.map((item) => sanitizeKeys(item));
  }
  return Object.fromEntries(
    Object.entries(obj).map(([key, value2]) => [
      key.replace(/</g, "&lt;").replace(/>/g, "&gt;"),
      sanitizeKeys(value2)
    ])
  );
}
const AsciinemaPlayer = ({
  id,
  rows,
  cols,
  inputUrl,
  outputUrl,
  timingUrl,
  fit,
  speed,
  autoPlay,
  loop,
  theme,
  idleTimeLimit = 2,
  style
}) => {
  const playerContainerRef = reactExports.useRef(null);
  reactExports.useEffect(() => {
    if (!playerContainerRef.current) return;
    const player = create(
      {
        url: [timingUrl, outputUrl, inputUrl],
        parser: "typescript"
      },
      playerContainerRef.current,
      {
        rows,
        cols,
        autoPlay,
        loop,
        theme,
        speed,
        idleTimeLimit,
        fit
      }
    );
    player.play();
    return () => {
      player.dispose();
    };
  }, [
    timingUrl,
    outputUrl,
    inputUrl,
    rows,
    cols,
    autoPlay,
    loop,
    theme,
    speed,
    idleTimeLimit,
    fit
  ]);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    "div",
    {
      id: `asciinema-player-${id || "default"}`,
      ref: playerContainerRef,
      style: { ...style }
    }
  );
};
function useRevokableUrls() {
  const urlsRef = reactExports.useRef([]);
  const createRevokableUrl = reactExports.useCallback(
    (data, type = "text/plain") => {
      const blob = new Blob([data], { type });
      const url = URL.createObjectURL(blob);
      urlsRef.current.push(url);
      return url;
    },
    []
  );
  reactExports.useEffect(() => {
    return () => {
      urlsRef.current.forEach((url) => URL.revokeObjectURL(url));
      urlsRef.current = [];
    };
  }, []);
  return createRevokableUrl;
}
const carouselThumbs = "_carouselThumbs_1mvg8_1";
const carouselThumb = "_carouselThumb_1mvg8_1";
const carouselPlayIcon = "_carouselPlayIcon_1mvg8_16";
const lightboxOverlay = "_lightboxOverlay_1mvg8_20";
const lightboxContent = "_lightboxContent_1mvg8_33";
const lightboxButtonCloseWrapper = "_lightboxButtonCloseWrapper_1mvg8_45";
const lightboxButtonClose = "_lightboxButtonClose_1mvg8_45";
const lightboxPreviewButton = "_lightboxPreviewButton_1mvg8_63";
const styles$8 = {
  carouselThumbs,
  carouselThumb,
  carouselPlayIcon,
  lightboxOverlay,
  lightboxContent,
  lightboxButtonCloseWrapper,
  lightboxButtonClose,
  lightboxPreviewButton
};
const LightboxCarousel = ({ id, slides }) => {
  const [isOpen, setIsOpen] = useProperty(id, "isOpen", {
    defaultValue: false
  });
  const [currentIndex, setCurrentIndex] = useProperty(id, "currentIndex", {
    defaultValue: 0
  });
  const [showOverlay, setShowOverlay] = useProperty(id, "showOverlay", {
    defaultValue: false
  });
  const openLightbox = reactExports.useCallback(
    (index) => {
      setCurrentIndex(index);
      setShowOverlay(true);
      setTimeout(() => setIsOpen(true), 10);
    },
    [setCurrentIndex, setIsOpen, setShowOverlay]
  );
  const closeLightbox = reactExports.useCallback(() => {
    setIsOpen(false);
  }, [setIsOpen]);
  reactExports.useEffect(() => {
    if (!isOpen && showOverlay) {
      const timer = setTimeout(() => {
        setShowOverlay(false);
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [isOpen, showOverlay, setShowOverlay]);
  const showNext = reactExports.useCallback(() => {
    setCurrentIndex(currentIndex + 1);
  }, [setCurrentIndex, currentIndex]);
  const showPrev = reactExports.useCallback(() => {
    setCurrentIndex((currentIndex - 1 + slides.length) % slides.length);
  }, [setCurrentIndex, currentIndex, slides.length]);
  reactExports.useEffect(() => {
    if (!isOpen) return;
    const handleKeyUp = (e) => {
      if (e.key === "Escape") {
        closeLightbox();
      } else if (e.key === "ArrowRight") {
        showNext();
      } else if (e.key === "ArrowLeft") {
        showPrev();
      }
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener("keyup", handleKeyUp, true);
    return () => window.removeEventListener("keyup", handleKeyUp);
  }, [closeLightbox, isOpen, showNext, showPrev]);
  const handleThumbClick = reactExports.useCallback(
    (e) => {
      const index = Number(e.currentTarget.dataset.index);
      openLightbox(index);
    },
    [openLightbox]
  );
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx("lightbox-carousel-container"), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$8.carouselThumbs), children: slides.map((slide, index) => {
      return /* @__PURE__ */ jsxRuntimeExports.jsxs(
        "div",
        {
          "data-index": index,
          className: clsx(styles$8.carouselThumb),
          onClick: handleThumbClick,
          children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: slide.label }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: /* @__PURE__ */ jsxRuntimeExports.jsx(
              "i",
              {
                className: clsx(
                  ApplicationIcons.play,
                  styles$8.carouselPlayIcon
                )
              }
            ) })
          ]
        },
        index
      );
    }) }),
    showOverlay && /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        className: clsx(styles$8.lightboxOverlay, isOpen ? "open" : "closed"),
        children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$8.lightboxButtonCloseWrapper), children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              className: styles$8.lightboxButtonClose,
              onClick: closeLightbox,
              children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: ApplicationIcons.close })
            }
          ) }),
          slides.length > 1 ? /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              className: clsx(styles$8.lightboxPreviewButton, "prev"),
              onClick: showPrev,
              children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: ApplicationIcons.previous })
            }
          ) : "",
          slides.length > 1 ? /* @__PURE__ */ jsxRuntimeExports.jsx(
            "button",
            {
              className: clsx(styles$8.lightboxPreviewButton, "next"),
              onClick: showNext,
              children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: ApplicationIcons.next })
            }
          ) : "",
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "div",
            {
              className: clsx(styles$8.lightboxContent, isOpen ? "open" : "closed"),
              children: slides[currentIndex].render()
            },
            `carousel-slide-${currentIndex}`
          )
        ]
      }
    )
  ] });
};
const HumanBaselineView = ({
  started,
  runtime,
  answer: answer2,
  completed,
  running,
  sessionLogs
}) => {
  const createRevokableUrl = useRevokableUrls();
  const player_fns = [];
  let count = 1;
  for (const sessionLog of sessionLogs) {
    const rows = extractSize(sessionLog.output, "LINES", 24);
    const cols = extractSize(sessionLog.output, "COLUMNS", 80);
    const currentCount = count;
    const title2 = sessionLogs.length === 1 ? "Terminal Session" : `Terminal Session ${currentCount}`;
    player_fns.push({
      label: title2,
      render: () => /* @__PURE__ */ jsxRuntimeExports.jsx(
        AsciinemaPlayer,
        {
          id: `player-${currentCount}`,
          inputUrl: createRevokableUrl(sessionLog.input),
          outputUrl: createRevokableUrl(sessionLog.output),
          timingUrl: createRevokableUrl(sessionLog.timing),
          rows,
          cols,
          className: "asciinema-player",
          style: {
            height: `${rows * 2}em`,
            width: `${cols * 2}em`
          },
          fit: "both"
        }
      )
    });
    count += 1;
  }
  const StatusMessage = ({
    completed: completed2,
    running: running2,
    answer: answer22
  }) => {
    if (running2) {
      return /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "text-style-label", children: "Running" });
    } else if (completed2) {
      return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "span",
          {
            className: "text-style-label text-style-secondary asciinema-player-status",
            children: "Answer"
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: answer22 })
      ] });
    } else {
      return "Unknown status";
    }
  };
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "asciinema-wrapper", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "asciinema-container", children: [
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "asciinema-header-left text-style-label", children: [
      started ? formatDateTime(started) : "",
      runtime ? ` (${formatTime(Math.floor(runtime))})` : ""
    ] }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "asciinema-header-center text-style-label" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "asciinema-header-right", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
      StatusMessage,
      {
        completed,
        running,
        answer: answer2
      }
    ) }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "asciinema-body", children: /* @__PURE__ */ jsxRuntimeExports.jsx(LightboxCarousel, { id: "ascii-cinema", slides: player_fns }) })
  ] }) });
};
const extractSize = (value2, label2, defaultValue) => {
  const regex = new RegExp(`${label2}="(\\d+)"`);
  const match = value2.match(regex);
  const size = match ? match[1] : void 0;
  if (size) {
    return parseInt(size);
  } else {
    return defaultValue;
  }
};
const toolsGrid = "_toolsGrid_1qqm2_1";
const tools = "_tools_1qqm2_1";
const tool = "_tool_1qqm2_1";
const styles$7 = {
  toolsGrid,
  tools,
  tool
};
const system_msg_added_sig = {
  type: "system_message",
  signature: {
    remove: ["/messages/0/source"],
    replace: ["/messages/0/role", "/messages/0/content"],
    add: ["/messages/1"]
  },
  render: (_changes, resolvedState) => {
    const messages2 = resolvedState["messages"];
    const message2 = messages2[0];
    if (typeof message2 !== "object" || !message2) {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(jsxRuntimeExports.Fragment, {});
    }
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      ChatView,
      {
        id: "system_msg_event_preview",
        messages: [message2],
        allowLinking: false
      },
      "system_msg_event_preview"
    );
  }
};
const kToolPattern = "/tools/(\\d+)";
const use_tools = {
  type: "use_tools",
  signature: {
    add: ["/tools/0"],
    replace: ["/tool_choice"],
    remove: []
  },
  render: (changes, resolvedState) => {
    return renderTools(changes, resolvedState);
  }
};
const add_tools = {
  type: "add_tools",
  signature: {
    add: [kToolPattern],
    replace: [],
    remove: []
  },
  render: (changes, resolvedState) => {
    return renderTools(changes, resolvedState);
  }
};
const messages = {
  type: "messages",
  match: (changes) => {
    const allMessages = changes.every((change) => {
      if (change.op === "add" && change.path.match(/\/messages\/\d+/)) {
        return typeof change.value["role"] === "string" && ["user", "assistant", "system", "tool"].includes(change.value["role"]);
      }
      return false;
    });
    return allMessages;
  },
  render: (changes) => {
    const messages2 = changes.map((c) => c.value);
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      ChatView,
      {
        id: "system_msg_event_preview",
        messages: messages2,
        allowLinking: false
      },
      "system_msg_event_preview"
    );
  }
};
const humanAgentKey = (key) => {
  return `HumanAgentState:${key}`;
};
const human_baseline_session = {
  type: "human_baseline_session",
  signature: {
    add: ["HumanAgentState:logs"],
    replace: [],
    remove: []
  },
  render: (_changes, state) => {
    const started = state[humanAgentKey("started_running")];
    const runtime = state[humanAgentKey("accumulated_time")];
    const answer2 = state[humanAgentKey("answer")];
    const completed = !!answer2;
    const running = state[humanAgentKey("running_state")];
    const rawSessions = state[humanAgentKey("logs")];
    const startedDate = started ? new Date(started * 1e3) : void 0;
    const sessions = {};
    if (rawSessions) {
      for (const key of Object.keys(rawSessions)) {
        const value2 = rawSessions[key];
        const match = key.match(/(.*)_(\d+_\d+)\.(.*)/);
        if (match) {
          const user = match[1];
          const timestamp = match[2];
          const type = match[3];
          sessions[timestamp] = sessions[timestamp] || {};
          switch (type) {
            case "input":
              sessions[timestamp].input = value2;
              break;
            case "output":
              sessions[timestamp].output = value2;
              break;
            case "timing":
              sessions[timestamp].timing = value2;
              break;
            case "name":
              sessions[timestamp].name = value2;
              break;
          }
          sessions[timestamp].user = user;
        }
      }
    }
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      HumanBaselineView,
      {
        started: startedDate,
        running,
        completed,
        answer: answer2,
        runtime,
        sessionLogs: Object.values(sessions)
      },
      "human_baseline_view"
    );
  }
};
const renderTools = (changes, resolvedState) => {
  const toolIndexes = [];
  for (const change of changes) {
    const match = change.path.match(kToolPattern);
    if (match) {
      toolIndexes.push(match[1]);
    }
  }
  const toolName = (toolChoice2) => {
    if (typeof toolChoice2 === "object" && toolChoice2 && !Array.isArray(toolChoice2)) {
      return toolChoice2["name"];
    } else {
      return String(toolChoice2);
    }
  };
  const toolsInfo = {};
  const hasToolChoice = changes.find((change) => {
    return change.path.startsWith("/tool_choice");
  });
  if (resolvedState.tool_choice && hasToolChoice) {
    toolsInfo["Tool Choice"] = /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: clsx("text-size-smaller"), children: toolName(resolvedState.tool_choice) });
  }
  const tools2 = resolvedState.tools;
  if (tools2.length > 0) {
    if (toolIndexes.length === 0) {
      toolsInfo["Tools"] = /* @__PURE__ */ jsxRuntimeExports.jsx(Tools, { toolDefinitions: resolvedState.tools });
    } else {
      const filtered = tools2.filter((_, index) => {
        return toolIndexes.includes(index.toString());
      });
      toolsInfo["Tools"] = /* @__PURE__ */ jsxRuntimeExports.jsx(Tools, { toolDefinitions: filtered });
    }
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$7.tools), children: Object.keys(toolsInfo).map((key) => {
    return /* @__PURE__ */ jsxRuntimeExports.jsxs(reactExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        "div",
        {
          className: clsx(
            "text-size-smaller",
            "text-style-label",
            "text-style-secondary"
          ),
          children: key
        }
      ),
      toolsInfo[key]
    ] }, key);
  }) }, "state-diff-tools");
};
const createMessageRenderer = (name, role) => {
  return {
    type: name,
    match: (changes) => {
      if (changes.length === 1) {
        const change = changes[0];
        if (change.op === "add" && change.path.match(/\/messages\/\d+/)) {
          return change.value["role"] === role;
        }
      }
      return false;
    },
    render: (changes) => {
      const message2 = changes[0].value;
      return /* @__PURE__ */ jsxRuntimeExports.jsx(
        ChatView,
        {
          id: "system_msg_event_preview",
          messages: [message2],
          allowLinking: false
        },
        "system_msg_event_preview"
      );
    }
  };
};
const RenderableChangeTypes = [
  system_msg_added_sig,
  createMessageRenderer("assistant_msg", "assistant"),
  createMessageRenderer("user_msg", "user"),
  use_tools,
  add_tools,
  messages
];
const StoreSpecificRenderableTypes = [
  human_baseline_session
];
const Tools = ({ toolDefinitions }) => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles$7.toolsGrid, children: toolDefinitions.map((toolDefinition, idx) => {
    const toolName = toolDefinition.name;
    const toolArgs = toolDefinition.parameters?.properties ? Object.keys(toolDefinition.parameters.properties) : [];
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      Tool,
      {
        toolName,
        toolArgs
      },
      `${toolName}-${idx}`
    );
  }) });
};
const Tool = ({ toolName, toolArgs }) => {
  const functionCall = toolArgs && toolArgs.length > 0 ? `${toolName}(${toolArgs.join(", ")})` : toolName;
  return /* @__PURE__ */ jsxRuntimeExports.jsx("code", { className: clsx("text-size-smallest", styles$7.tool), children: functionCall });
};
const diff = "_diff_eobja_1";
const summary$2 = "_summary_eobja_6";
const styles$6 = {
  diff,
  summary: summary$2
};
const StateEventView = ({
  eventNode,
  className
}) => {
  const event = eventNode.event;
  const summary2 = reactExports.useMemo(() => {
    return summarizeChanges(event.changes);
  }, [event.changes]);
  const [before, after] = reactExports.useMemo(() => {
    try {
      return synthesizeComparable(event.changes);
    } catch (e) {
      console.error(
        "Unable to synthesize comparable object to display state diffs.",
        e
      );
      return [{}, {}];
    }
  }, [event.changes]);
  const changePreview = reactExports.useMemo(() => {
    const isStore = eventNode.event.event === "store";
    return generatePreview(event.changes, structuredClone(after), isStore);
  }, [eventNode.event.event, event.changes, after]);
  const title2 = event.event === "state" ? "State Updated" : "Store Updated";
  const collapseEvent = useStore((state) => state.sampleActions.collapseEvent);
  reactExports.useEffect(() => {
    if (changePreview === void 0) {
      collapseEvent(kTranscriptCollapseScope, eventNode.id, true);
    }
  }, [changePreview, collapseEvent, eventNode.id]);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      title: formatTitle(title2, void 0, event.working_start),
      className,
      subTitle: formatDateTime(new Date(event.timestamp)),
      text: !changePreview ? summary2 : void 0,
      collapsibleContent: true,
      children: [
        changePreview ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { "data-name": "Summary", className: clsx(styles$6.summary), children: changePreview }) : void 0,
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          StateDiffView,
          {
            before,
            after,
            "data-name": "Diff",
            className: clsx(styles$6.diff)
          }
        )
      ]
    }
  );
};
const generatePreview = (changes, resolvedState, isStore) => {
  const results = [];
  for (const changeType of [
    ...RenderableChangeTypes,
    ...isStore ? StoreSpecificRenderableTypes : []
  ]) {
    if (changeType.signature) {
      const requiredMatchCount = changeType.signature.remove.length + changeType.signature.replace.length + changeType.signature.add.length;
      let matchingOps = 0;
      for (const change of changes) {
        const op = change.op;
        switch (op) {
          case "add":
            if (changeType.signature.add && changeType.signature.add.length > 0) {
              changeType.signature.add.forEach((signature) => {
                if (change.path.match(signature)) {
                  matchingOps++;
                }
              });
            }
            break;
          case "remove":
            if (changeType.signature.remove && changeType.signature.remove.length > 0) {
              changeType.signature.remove.forEach((signature) => {
                if (change.path.match(signature)) {
                  matchingOps++;
                }
              });
            }
            break;
          case "replace":
            if (changeType.signature.replace && changeType.signature.replace.length > 0) {
              changeType.signature.replace.forEach((signature) => {
                if (change.path.match(signature)) {
                  matchingOps++;
                }
              });
            }
            break;
        }
      }
      if (matchingOps === requiredMatchCount) {
        const el = changeType.render(changes, resolvedState);
        results.push(el);
        break;
      }
    } else if (changeType.match) {
      const matches = changeType.match(changes);
      if (matches) {
        const el = changeType.render(changes, resolvedState);
        results.push(el);
        break;
      }
    }
  }
  return results.length > 0 ? results : void 0;
};
const summarizeChanges = (changes) => {
  const changeMap = {
    add: [],
    copy: [],
    move: [],
    replace: [],
    remove: [],
    test: []
  };
  for (const change of changes) {
    switch (change.op) {
      case "add":
        changeMap.add.push(change.path);
        break;
      case "copy":
        changeMap.copy.push(change.path);
        break;
      case "move":
        changeMap.move.push(change.path);
        break;
      case "replace":
        changeMap.replace.push(change.path);
        break;
      case "remove":
        changeMap.remove.push(change.path);
        break;
      case "test":
        changeMap.test.push(change.path);
        break;
    }
  }
  const changeList = [];
  const totalOpCount = Object.keys(changeMap).reduce((prev, current) => {
    return prev + changeMap[current].length;
  }, 0);
  if (totalOpCount > 2) {
    Object.keys(changeMap).forEach((key) => {
      const opChanges = changeMap[key];
      if (opChanges.length > 0) {
        changeList.push(`${key} ${opChanges.length}`);
      }
    });
  } else {
    Object.keys(changeMap).forEach((key) => {
      const opChanges = changeMap[key];
      if (opChanges.length > 0) {
        changeList.push(`${key} ${opChanges.join(", ")}`);
      }
    });
  }
  return changeList.join(", ");
};
const synthesizeComparable = (changes) => {
  const before = {};
  const after = {};
  for (const change of changes) {
    switch (change.op) {
      case "add":
        initializeArrays(before, change.path);
        initializeArrays(after, change.path);
        setPath(after, change.path, change.value);
        break;
      case "copy":
        setPath(before, change.path, change.value);
        setPath(after, change.path, change.value);
        break;
      case "move":
        setPath(before, change.from || "", change.value);
        setPath(after, change.path, change.value);
        break;
      case "remove":
        setPath(before, change.path, change.value);
        break;
      case "replace":
        initializeArrays(before, change.path);
        initializeArrays(after, change.path);
        setPath(before, change.path, change.replaced);
        setPath(after, change.path, change.value);
        break;
    }
  }
  return [before, after];
};
function setPath(target2, path, value2) {
  const keys = parsePath(path);
  let current = target2;
  for (let i = 0; i < keys.length - 1; i++) {
    const key = keys[i];
    if (!(key in current)) {
      current[key] = isArrayIndex(keys[i + 1]) ? [] : {};
    }
    current = current[key];
  }
  const lastKey = keys[keys.length - 1];
  current[lastKey] = value2;
}
function initializeArrays(target2, path) {
  const keys = parsePath(path);
  let current = target2;
  for (let i = 0; i < keys.length - 1; i++) {
    const key = keys[i];
    const nextKey = keys[i + 1];
    if (isArrayIndex(nextKey)) {
      current[key] = initializeArray(
        current[key],
        nextKey
      );
    } else {
      current[key] = initializeObject(current[key]);
    }
    current = current[key];
  }
  const lastKey = keys[keys.length - 1];
  if (isArrayIndex(lastKey)) {
    const lastValue = current[lastKey];
    initializeArray(lastValue, lastKey);
  }
}
function parsePath(path) {
  return path.split("/").filter(Boolean);
}
function isArrayIndex(key) {
  return /^\d+$/.test(key);
}
function initializeArray(current, nextKey) {
  if (!Array.isArray(current)) {
    current = [];
  }
  const nextKeyIndex = parseInt(nextKey, 10);
  while (current.length < nextKeyIndex) {
    current.push("");
  }
  return current;
}
function initializeObject(current) {
  return current ?? {};
}
const StepEventView = ({
  eventNode,
  children,
  className
}) => {
  const event = eventNode.event;
  const descriptor = stepDescriptor(event);
  const title2 = eventTitle(event);
  const text = summarize$1(children);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      childIds: children.map((child) => child.id),
      className: clsx("transcript-step", className),
      title: formatTitle(title2, void 0, event.working_start),
      subTitle: formatDateTime(new Date(event.timestamp)),
      icon: descriptor.icon,
      text
    }
  );
};
const summarize$1 = (children) => {
  if (children.length === 0) {
    return "(no events)";
  }
  const formatEvent = (event, count) => {
    if (count === 1) {
      return `${count} ${event} event`;
    } else {
      return `${count} ${event} events`;
    }
  };
  const typeCount = {};
  children.forEach((child) => {
    const currentCount = typeCount[child.event.event] || 0;
    typeCount[child.event.event] = currentCount + 1;
  });
  const numberOfTypes = Object.keys(typeCount).length;
  if (numberOfTypes < 3) {
    return Object.keys(typeCount).map((key) => {
      return formatEvent(key, typeCount[key]);
    }).join(", ");
  }
  if (children.length === 1) {
    return "1 event";
  } else {
    return `${children.length} events`;
  }
};
const stepDescriptor = (event) => {
  const rootStepDescriptor = {
    endSpace: true
  };
  if (event.type === "solver" || event.type === "scorer") {
    return { ...rootStepDescriptor };
  } else if (event.event === "step") {
    return { ...rootStepDescriptor };
  } else {
    switch (event.name) {
      case "sample_init":
        return { ...rootStepDescriptor };
      default:
        return { endSpace: false };
    }
  }
};
const summary$1 = "_summary_ac4z2_1";
const summaryRendered = "_summaryRendered_ac4z2_6";
const subtaskSummary = "_subtaskSummary_ac4z2_10";
const subtaskLabel = "_subtaskLabel_ac4z2_17";
const styles$5 = {
  summary: summary$1,
  summaryRendered,
  subtaskSummary,
  subtaskLabel
};
const SubtaskEventView = ({
  eventNode,
  children,
  className
}) => {
  const event = eventNode.event;
  const body2 = [];
  if (event.type === "fork") {
    body2.push(
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { title: "Summary", className: clsx(styles$5.summary), children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-style-label"), children: "Inputs" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$5.summaryRendered), children: /* @__PURE__ */ jsxRuntimeExports.jsx(Rendered, { values: event.input }) })
      ] })
    );
  } else {
    body2.push(
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        SubtaskSummary,
        {
          "data-name": "Summary",
          input: event.input,
          result: event.result
        }
      )
    );
  }
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      className,
      title: formatTitle(eventTitle(event), void 0, event.working_time),
      subTitle: formatTiming(event.timestamp, event.working_start),
      childIds: children.map((child) => child.id),
      collapseControl: "bottom",
      children: body2
    }
  );
};
const SubtaskSummary = ({ input, result: result2 }) => {
  const output = typeof result2 === "object" ? result2 : { result: result2 };
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$5.subtaskSummary), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-style-label", "text-size-small"), children: "Input" }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-size-large", styles$5.subtaskLabel) }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-style-label", "text-size-small"), children: "Output" }),
    input ? /* @__PURE__ */ jsxRuntimeExports.jsx(Rendered, { values: input }) : void 0,
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx("text-size-title-secondary", styles$5.subtaskLabel), children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: ApplicationIcons.arrows.right }) }),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: /* @__PURE__ */ jsxRuntimeExports.jsx(Rendered, { values: output }) })
  ] });
};
const Rendered = ({ values }) => {
  if (Array.isArray(values)) {
    return values.map((val) => {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(Rendered, { values: val });
    });
  } else if (values && typeof values === "object") {
    if (Object.keys(values).length === 0) {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(None, {});
    } else {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(MetaDataGrid, { entries: values });
    }
  } else {
    return values;
  }
};
const None = () => {
  return /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: clsx("text-size-small", "text-style-secondary"), children: "[None]" });
};
const summary = "_summary_1qsnv_1";
const approval = "_approval_1qsnv_6";
const progress = "_progress_1qsnv_12";
const styles$4 = {
  summary,
  approval,
  progress
};
const ToolEventView = ({
  eventNode,
  children,
  className,
  context
}) => {
  const event = eventNode.event;
  const turnLabel2 = context?.turnInfo ? `turn ${context.turnInfo.turnNumber}/${context.turnInfo.totalTurns}` : void 0;
  const { input, description, functionCall, contentType } = reactExports.useMemo(
    () => resolveToolInput(event.function, event.arguments),
    [event.function, event.arguments]
  );
  const { approvalNode, lastModelNode } = reactExports.useMemo(() => {
    const approvalNode2 = children.find((e) => {
      return e.event.event === "approval";
    });
    const lastModelNode2 = children.findLast((e) => {
      return e.event.event === "model";
    });
    return {
      approvalNode: approvalNode2,
      lastModelNode: lastModelNode2
    };
  }, [children]);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      title: formatTitle(eventTitle(event), void 0, event.working_time),
      className,
      subTitle: formatTiming(event.timestamp, event.working_start),
      icon: ApplicationIcons.solvers.use_tools,
      childIds: children.map((child) => child.id),
      collapseControl: "bottom",
      turnLabel: turnLabel2,
      children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { "data-name": "Summary", className: styles$4.summary, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          ToolCallView,
          {
            id: `${eventNode.id}-tool-call`,
            functionCall,
            input,
            description,
            contentType,
            output: event.error?.message || event.result,
            mode: "compact",
            view: event.view ? substituteToolCallContent(
              event.view,
              event.arguments
            ) : void 0
          }
        ),
        lastModelNode ? /* @__PURE__ */ jsxRuntimeExports.jsx(
          ChatView,
          {
            id: `${eventNode.id}-toolcall-chatmessage`,
            messages: lastModelNode.event.output.choices.map((m) => m.message),
            numbered: false,
            toolCallStyle: "compact",
            allowLinking: false
          }
        ) : void 0,
        approvalNode ? /* @__PURE__ */ jsxRuntimeExports.jsx(
          ApprovalEventView,
          {
            eventNode: approvalNode,
            className: styles$4.approval
          }
        ) : "",
        event.pending ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$4.progress), children: /* @__PURE__ */ jsxRuntimeExports.jsx(PulsingDots, { subtle: false, size: "medium" }) }) : void 0
      ] })
    }
  );
};
const container$1 = "_container_io1r0_1";
const wrappingContent = "_wrappingContent_io1r0_8";
const separator = "_separator_io1r0_13";
const unchanged = "_unchanged_io1r0_22";
const section = "_section_io1r0_27";
const spacer = "_spacer_io1r0_31";
const styles$3 = {
  container: container$1,
  wrappingContent,
  separator,
  unchanged,
  section,
  spacer
};
const kUnchangedSentinel = "UNCHANGED";
const ScoreEditEventView = ({
  eventNode,
  className
}) => {
  const event = eventNode.event;
  const subtitle = event.edit.provenance ? `[${formatDateTime(new Date(event.edit.provenance.timestamp))}] ${event.edit.provenance.author}: ${event.edit.provenance.reason || ""}` : void 0;
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      title: formatTitle(eventTitle(event), void 0, event.working_start),
      className: clsx(className, "text-size-small"),
      subTitle: subtitle,
      collapsibleContent: true,
      icon: ApplicationIcons.edit,
      children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { "data-name": "Summary", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            className: clsx(
              "text-style-label",
              "text-style-secondary",
              styles$3.section
            ),
            children: "Updated Values"
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$3.container), children: [
          event.edit.value !== void 0 ? /* @__PURE__ */ jsxRuntimeExports.jsxs(reactExports.Fragment, { children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.separator) }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-style-label", children: "Value" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: renderScore(event.edit.value) })
          ] }) : "",
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.separator) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-style-label", children: "Answer" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.wrappingContent), children: event.edit.answer === kUnchangedSentinel ? /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: clsx(styles$3.unchanged), children: "[unchanged]" }) : /* @__PURE__ */ jsxRuntimeExports.jsx(RenderedText, { markdown: event.edit.answer || "" }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.separator) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-style-label", children: "Explanation" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.wrappingContent), children: /* @__PURE__ */ jsxRuntimeExports.jsx(RenderedText, { markdown: event.edit.explanation || "" }) })
        ] }),
        event.edit.provenance ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$3.container), children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            "div",
            {
              className: clsx(
                "text-style-label",
                "text-style-secondary",
                styles$3.section
              ),
              children: "Provenance"
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.spacer) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.separator) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-style-label", children: "Author" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.wrappingContent), children: /* @__PURE__ */ jsxRuntimeExports.jsx(RenderedText, { markdown: event.edit.provenance.author }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.separator) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-style-label", children: "Reason" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.wrappingContent), children: /* @__PURE__ */ jsxRuntimeExports.jsx(RenderedText, { markdown: event.edit.provenance.reason || "" }) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.separator) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-style-label", children: "Time" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$3.wrappingContent), children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            RenderedText,
            {
              markdown: formatDateTime(new Date(event.edit.provenance.timestamp)) || ""
            }
          ) })
        ] }) : "",
        event.edit.metadata && event.edit.metadata !== kUnchangedSentinel ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { "data-name": "Metadata", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          RecordTree,
          {
            id: `${eventNode.id}-score-metadata`,
            record: event.edit.metadata || {},
            className: styles$3.metadataTree,
            defaultExpandLevel: 0
          }
        ) }) : void 0
      ] })
    }
  );
};
const SpanEventView = ({
  eventNode,
  children,
  className
}) => {
  const event = eventNode.event;
  const descriptor = spanDescriptor(event);
  const title2 = eventTitle(event);
  const text = reactExports.useMemo(() => summarize(children), [children]);
  const childIds = reactExports.useMemo(() => children.map((child) => child.id), [children]);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      childIds,
      className: clsx("transcript-span", className),
      title: formatTitle(title2, void 0, event.working_start),
      subTitle: formatDateTime(new Date(event.timestamp)),
      text,
      icon: descriptor.icon
    }
  );
};
const summarize = (children) => {
  if (children.length === 0) {
    return "(no events)";
  }
  const formatEvent = (event, count) => {
    if (count === 1) {
      return `${count} ${event} event`;
    } else {
      return `${count} ${event} events`;
    }
  };
  const typeCount = {};
  children.forEach((child) => {
    const currentCount = typeCount[child.event.event] || 0;
    typeCount[child.event.event] = currentCount + 1;
  });
  const numberOfTypes = Object.keys(typeCount).length;
  if (numberOfTypes < 3) {
    return Object.keys(typeCount).map((key) => {
      return formatEvent(key, typeCount[key]);
    }).join(", ");
  }
  if (children.length === 1) {
    return "1 event";
  } else {
    return `${children.length} events`;
  }
};
const spanDescriptor = (event) => {
  const rootStepDescriptor = {
    endSpace: true
  };
  if (event.type === "solver" || event.type === "scorer") {
    return { ...rootStepDescriptor };
  } else if (event.event === "span_begin") {
    return { ...rootStepDescriptor };
  } else {
    switch (event.name) {
      case "sample_init":
        return { ...rootStepDescriptor };
      default:
        return { endSpace: false };
    }
  }
};
const node = "_node_1r858_1";
const attached = "_attached_1r858_5";
const attachedParent = "_attachedParent_1r858_9";
const attachedChild = "_attachedChild_1r858_16";
const styles$2 = {
  node,
  attached,
  attachedParent,
  attachedChild
};
const eventSearchText = (node2) => {
  const texts = [];
  const event = node2.event;
  const title2 = eventTitle(event);
  if (title2) {
    texts.push(title2);
  }
  switch (event.event) {
    case "model": {
      if (event.output?.choices) {
        for (const choice of event.output.choices) {
          texts.push(...extractContentText(choice.message.content));
        }
      }
      if (event.input) {
        for (const msg of event.input) {
          if (msg.role === "user" || msg.role === "system") {
            texts.push(...extractContentText(msg.content));
          }
        }
      }
      break;
    }
    case "tool": {
      if (event.function) {
        texts.push(event.function);
      }
      if (event.arguments) {
        texts.push(JSON.stringify(event.arguments));
      }
      if (event.result) {
        if (typeof event.result === "string") {
          texts.push(event.result);
        } else {
          texts.push(JSON.stringify(event.result));
        }
      }
      if (event.error?.message) {
        texts.push(event.error.message);
      }
      if (event.view?.content) {
        const substituted = substituteToolCallContent(
          event.view,
          event.arguments
        );
        texts.push(substituted.content);
      }
      break;
    }
    case "error": {
      if (event.error?.message) {
        texts.push(event.error.message);
      }
      if (event.error?.traceback) {
        texts.push(event.error.traceback);
      }
      break;
    }
    case "logger": {
      if (event.message?.message) {
        texts.push(event.message.message);
      }
      if (event.message?.filename) {
        texts.push(event.message.filename);
      }
      break;
    }
    case "info": {
      if (event.data) {
        if (typeof event.data === "string") {
          texts.push(event.data);
        } else {
          texts.push(JSON.stringify(event.data));
        }
      }
      break;
    }
    case "compaction": {
      if (event.source) {
        texts.push(event.source);
      }
      texts.push(JSON.stringify(event));
      break;
    }
    case "subtask": {
      if (event.input) {
        texts.push(JSON.stringify(event.input));
      }
      if (event.result) {
        texts.push(JSON.stringify(event.result));
      }
      break;
    }
    case "score": {
      if (event.score.answer) {
        texts.push(event.score.answer);
      }
      if (event.score.explanation) {
        texts.push(event.score.explanation);
      }
      if (event.target) {
        const target2 = Array.isArray(event.target) ? event.target.join("\n") : event.target;
        texts.push(target2);
      }
      if (event.score.value != null) {
        texts.push(
          typeof event.score.value === "object" ? JSON.stringify(event.score.value) : String(event.score.value)
        );
      }
      break;
    }
    case "score_edit": {
      if (event.edit.answer) {
        texts.push(event.edit.answer);
      }
      if (event.edit.explanation) {
        texts.push(event.edit.explanation);
      }
      if (event.edit.provenance) {
        if (event.edit.provenance.author) {
          texts.push(event.edit.provenance.author);
        }
        if (event.edit.provenance.reason) {
          texts.push(event.edit.provenance.reason);
        }
      }
      break;
    }
    case "sample_init": {
      if (event.sample.target) {
        const target2 = Array.isArray(event.sample.target) ? event.sample.target.join("\n") : event.sample.target;
        texts.push(target2);
      }
      break;
    }
    case "sample_limit": {
      if (event.message) {
        texts.push(event.message);
      }
      break;
    }
    case "input": {
      if (event.input_ansi) {
        texts.push(event.input_ansi);
      }
      break;
    }
    case "approval": {
      if (event.explanation) {
        texts.push(event.explanation);
      }
      break;
    }
    case "sandbox": {
      if (event.cmd) {
        texts.push(event.cmd);
      }
      if (event.file) {
        texts.push(event.file);
      }
      if (event.input) {
        texts.push(event.input);
      }
      if (event.output) {
        texts.push(event.output);
      }
      break;
    }
  }
  return texts;
};
const extractContentText = (content) => {
  if (typeof content === "string") {
    return [content];
  }
  const texts = [];
  for (const item of content) {
    switch (item.type) {
      case "text":
        texts.push(item.text);
        break;
      case "reasoning": {
        if (item.reasoning) {
          texts.push(item.reasoning);
        } else if (item.summary) {
          texts.push(item.summary);
        }
        break;
      }
      case "tool_use": {
        if (item.name) {
          texts.push(item.name);
        }
        if (item.arguments) {
          texts.push(JSON.stringify(item.arguments));
        }
        break;
      }
    }
  }
  return texts;
};
const TranscriptVirtualListComponent = ({
  id,
  listHandle,
  eventNodes,
  scrollRef,
  running,
  initialEventId,
  offsetTop,
  className,
  turnMap
}) => {
  const useVirtualization = running || eventNodes.length > 100;
  const setNativeFind = useStore((state) => state.appActions.setNativeFind);
  reactExports.useEffect(() => {
    setNativeFind(!useVirtualization);
  }, [setNativeFind, useVirtualization]);
  const initialEventIndex = reactExports.useMemo(() => {
    if (initialEventId === null || initialEventId === void 0) {
      return void 0;
    }
    const result2 = eventNodes.findIndex((event) => {
      return event.id === initialEventId;
    });
    return result2 === -1 ? void 0 : result2;
  }, [initialEventId, eventNodes]);
  const hasToolEventsAtCurrentDepth = reactExports.useCallback(
    (startIndex) => {
      for (let i = startIndex; i >= 0; i--) {
        const node2 = eventNodes[i];
        if (node2.event.event === "tool") {
          return true;
        }
        if (node2.depth < eventNodes[startIndex].depth) {
          return false;
        }
      }
      return false;
    },
    [eventNodes]
  );
  const nonVirtualGridRef = reactExports.useRef(null);
  reactExports.useEffect(() => {
    if (!useVirtualization && initialEventId) {
      const row2 = nonVirtualGridRef.current?.querySelector(
        `[id="${initialEventId}"]`
      );
      row2?.scrollIntoView({ block: "start" });
    }
  }, [initialEventId, useVirtualization]);
  const contextMap = reactExports.useMemo(() => {
    const map = /* @__PURE__ */ new Map();
    for (let i = 0; i < eventNodes.length; i++) {
      const node2 = eventNodes[i];
      const hasToolEvents = hasToolEventsAtCurrentDepth(i);
      const turnInfo = turnMap?.get(node2.id);
      map.set(node2.id, { hasToolEvents, turnInfo });
    }
    return map;
  }, [eventNodes, hasToolEventsAtCurrentDepth, turnMap]);
  const renderRow = reactExports.useCallback(
    (index, item, style) => {
      const paddingClass = index === 0 ? styles$2.first : void 0;
      const previousIndex = index - 1;
      const nextIndex = index + 1;
      const previous = previousIndex > 0 && previousIndex <= eventNodes.length ? eventNodes[previousIndex] : void 0;
      const next = nextIndex < eventNodes.length ? eventNodes[nextIndex] : void 0;
      const attached2 = item.event.event === "tool" && (previous?.event.event === "tool" || previous?.event.event === "model");
      const attachedParent2 = item.event.event === "model" && next?.event.event === "tool";
      const attachedClass = attached2 ? styles$2.attached : void 0;
      const attachedChildClass = attached2 ? styles$2.attachedChild : void 0;
      const attachedParentClass = attachedParent2 ? styles$2.attachedParent : void 0;
      const context = contextMap.get(item.id);
      return /* @__PURE__ */ jsxRuntimeExports.jsx(
        "div",
        {
          id: item.id,
          className: clsx(styles$2.node, paddingClass, attachedClass),
          style: {
            ...style,
            paddingLeft: `${item.depth <= 1 ? item.depth * 0.7 : (0.7 + item.depth - 1) * 1}em`,
            paddingRight: `${item.depth === 0 ? void 0 : ".7em"} `
          },
          children: /* @__PURE__ */ jsxRuntimeExports.jsx(
            RenderedEventNode,
            {
              node: item,
              next,
              className: clsx(attachedParentClass, attachedChildClass),
              context
            }
          )
        },
        item.id
      );
    },
    [eventNodes, contextMap]
  );
  if (useVirtualization) {
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      LiveVirtualList,
      {
        listHandle,
        className,
        id,
        scrollRef,
        data: eventNodes,
        initialTopMostItemIndex: initialEventIndex,
        offsetTop,
        renderRow,
        live: running,
        itemSearchText: eventSearchText
      }
    );
  } else {
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { ref: nonVirtualGridRef, children: eventNodes.map((node2, index) => {
      const row2 = renderRow(index, node2, {
        scrollMarginTop: offsetTop
      });
      return row2;
    }) });
  }
};
const panel = "_panel_8zdtn_1";
const styles$1 = {
  panel
};
const CompactionEventView = ({
  eventNode,
  className
}) => {
  const event = eventNode.event;
  let data = {};
  if (event.tokens_before) {
    data["tokens_before"] = event.tokens_before;
  }
  if (event.tokens_after) {
    data["tokens_after"] = event.tokens_after;
  }
  data = { ...data, ...event.metadata || {} };
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    EventPanel,
    {
      eventNodeId: eventNode.id,
      depth: eventNode.depth,
      title: formatTitle(eventTitle(event), void 0, event.working_start),
      className,
      subTitle: formatDateTime(new Date(event.timestamp)),
      icon: ApplicationIcons.info,
      children: [/* @__PURE__ */ jsxRuntimeExports.jsx(MetaDataGrid, { entries: data, className: styles$1.panel })]
    }
  );
};
const TranscriptVirtualList = reactExports.memo(
  (props) => {
    let {
      id,
      scrollRef,
      eventNodes,
      listHandle,
      running,
      initialEventId,
      offsetTop,
      className,
      turnMap
    } = props;
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      TranscriptVirtualListComponent,
      {
        id,
        listHandle,
        eventNodes,
        initialEventId,
        offsetTop,
        scrollRef,
        running,
        className,
        turnMap
      }
    );
  }
);
const RenderedEventNode = reactExports.memo(
  ({ node: node2, next, className, context }) => {
    switch (node2.event.event) {
      case "sample_init":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          SampleInitEventView,
          {
            eventNode: node2,
            className
          }
        );
      case "sample_limit":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          SampleLimitEventView,
          {
            eventNode: node2,
            className
          }
        );
      case "info":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          InfoEventView,
          {
            eventNode: node2,
            className
          }
        );
      case "compaction":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          CompactionEventView,
          {
            eventNode: node2,
            className
          }
        );
      case "logger":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          LoggerEventView,
          {
            eventNode: node2,
            className
          }
        );
      case "model":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          ModelEventView,
          {
            eventNode: node2,
            showToolCalls: next?.event.event !== "tool",
            className,
            context
          }
        );
      case "score":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          ScoreEventView,
          {
            eventNode: node2,
            className
          }
        );
      case "score_edit":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          ScoreEditEventView,
          {
            eventNode: node2,
            className
          }
        );
      case "state":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          StateEventView,
          {
            eventNode: node2,
            className
          }
        );
      case "span_begin":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          SpanEventView,
          {
            eventNode: node2,
            children: node2.children,
            className
          }
        );
      case "step":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          StepEventView,
          {
            eventNode: node2,
            children: node2.children,
            className
          }
        );
      case "store":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          StateEventView,
          {
            eventNode: node2,
            className
          }
        );
      case "subtask":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          SubtaskEventView,
          {
            eventNode: node2,
            className,
            children: node2.children
          }
        );
      case "tool":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          ToolEventView,
          {
            eventNode: node2,
            className,
            children: node2.children,
            context
          }
        );
      case "input":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          InputEventView,
          {
            eventNode: node2,
            className
          }
        );
      case "error":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          ErrorEventView,
          {
            eventNode: node2,
            className
          }
        );
      case "approval":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          ApprovalEventView,
          {
            eventNode: node2,
            className
          }
        );
      case "sandbox":
        return /* @__PURE__ */ jsxRuntimeExports.jsx(
          SandboxEventView,
          {
            eventNode: node2,
            className
          }
        );
      default:
        return null;
    }
  }
);
const transformTree = (roots) => {
  const treeNodeTransformers = transformers();
  const visitNode = (node2) => {
    let currentNodes = [node2];
    currentNodes = currentNodes.map((n) => {
      n.children = n.children.flatMap(visitNode);
      return n;
    });
    for (const transformer of treeNodeTransformers) {
      const nextNodes = [];
      for (const currentNode of currentNodes) {
        if (transformer.matches(currentNode)) {
          const result2 = transformer.process(currentNode);
          if (Array.isArray(result2)) {
            nextNodes.push(...result2);
          } else {
            nextNodes.push(result2);
          }
        } else {
          nextNodes.push(currentNode);
        }
      }
      currentNodes = nextNodes;
    }
    return currentNodes.length === 1 ? currentNodes[0] : currentNodes;
  };
  const processedRoots = roots.flatMap(visitNode);
  const flushedNodes = [];
  for (const transformer of treeNodeTransformers) {
    if (transformer.flush) {
      const flushResults = transformer.flush();
      if (flushResults && flushResults.length > 0) {
        flushedNodes.push(...flushResults);
      }
    }
  }
  return [...processedRoots, ...flushedNodes];
};
const transformers = () => {
  const treeNodeTransformers = [
    {
      name: "unwrap_tools",
      matches: (node2) => node2.event.event === SPAN_BEGIN && node2.event.type === TYPE_TOOL,
      process: (node2) => elevateChildNode(node2, TYPE_TOOL) || node2
    },
    {
      name: "unwrap_subtasks",
      matches: (node2) => node2.event.event === SPAN_BEGIN && node2.event.type === TYPE_SUBTASK,
      process: (node2) => elevateChildNode(node2, TYPE_SUBTASK) || node2
    },
    {
      name: "unwrap_agent_solver",
      matches: (node2) => node2.event.event === SPAN_BEGIN && node2.event["type"] === TYPE_SOLVER && node2.children.length === 2 && node2.children[0].event.event === SPAN_BEGIN && node2.children[0].event.type === TYPE_AGENT && node2.children[1].event.event === STATE,
      process: (node2) => skipFirstChildNode(node2)
    },
    {
      name: "unwrap_agent_solver w/store",
      matches: (node2) => node2.event.event === SPAN_BEGIN && node2.event["type"] === TYPE_SOLVER && node2.children.length === 3 && node2.children[0].event.event === SPAN_BEGIN && node2.children[0].event.type === TYPE_AGENT && node2.children[1].event.event === STATE && node2.children[2].event.event === STORE,
      process: (node2) => skipFirstChildNode(node2)
    },
    {
      name: "unwrap_handoff",
      matches: (node2) => {
        const isHandoffNode = node2.event.event === SPAN_BEGIN && node2.event["type"] === TYPE_HANDOFF;
        if (!isHandoffNode) {
          return false;
        }
        if (node2.children.length === 1) {
          return node2.children[0].event.event === TOOL && !!node2.children[0].event.agent;
        } else {
          return node2.children.length === 2 && node2.children[0].event.event === TOOL && node2.children[1].event.event === STORE && node2.children[0].children.length === 2 && node2.children[0].children[0].event.event === SPAN_BEGIN && node2.children[0].children[0].event.type === TYPE_AGENT;
        }
      },
      process: (node2) => skipThisNode(node2)
    },
    {
      name: "discard_solvers_span",
      matches: (Node2) => Node2.event.event === SPAN_BEGIN && Node2.event.type === TYPE_SOLVERS,
      process: (node2) => {
        const nodes = discardNode(node2);
        return nodes;
      }
    }
  ];
  return treeNodeTransformers;
};
const elevateChildNode = (node2, childEventType) => {
  const targetIndex = node2.children.findIndex(
    (child) => child.event.event === childEventType
  );
  if (targetIndex === -1) {
    return null;
  }
  const targetNode = { ...node2.children[targetIndex] };
  const remainingChildren = node2.children.filter((_, i) => i !== targetIndex);
  targetNode.depth = node2.depth;
  targetNode.children = setDepth(remainingChildren, node2.depth + 1);
  return targetNode;
};
const skipFirstChildNode = (node2) => {
  const agentSpan = node2.children.splice(0, 1)[0];
  node2.children.unshift(...reduceDepth(agentSpan.children));
  return node2;
};
const skipThisNode = (node2) => {
  const newNode = { ...node2.children[0] };
  newNode.depth = node2.depth;
  newNode.children = reduceDepth(newNode.children, 2);
  return newNode;
};
const discardNode = (node2) => {
  const nodes = reduceDepth(node2.children, 1);
  return nodes;
};
const reduceDepth = (nodes, depth = 1) => {
  return nodes.map((node2) => {
    if (node2.children.length > 0) {
      node2.children = reduceDepth(node2.children, 1);
    }
    node2.depth = node2.depth - depth;
    return node2;
  });
};
const setDepth = (nodes, depth) => {
  return nodes.map((node2) => {
    if (node2.children.length > 0) {
      node2.children = setDepth(node2.children, depth + 1);
    }
    node2.depth = depth;
    return node2;
  });
};
function treeifyEvents(events, depth) {
  const useSpans = hasSpans(events);
  events = injectScorersSpan(events);
  const nodes = useSpans ? treeifyWithSpans(events, depth) : treeifyWithSteps(events, depth);
  return useSpans ? transformTree(nodes) : nodes;
}
const treeifyWithSpans = (events, depth) => {
  const { rootNodes, createNode } = createNodeFactory(depth);
  const spanNodes = /* @__PURE__ */ new Map();
  const processEvent = (event, parentOverride) => {
    if (event.event === SPAN_END) {
      return;
    }
    if (event.event === STEP && event.action !== ACTION_BEGIN) {
      return;
    }
    const resolvedParent = resolveParentForEvent(event, spanNodes);
    const parentNode = resolvedParent ?? null;
    const node2 = createNode(event, parentNode);
    if (event.event === SPAN_BEGIN) {
      const spanId = getEventSpanId(event);
      if (spanId !== null) {
        spanNodes.set(spanId, node2);
      }
    }
  };
  events.forEach((event) => processEvent(event));
  return rootNodes;
};
const treeifyWithSteps = (events, depth) => {
  const { rootNodes, createNode } = createNodeFactory(depth);
  const stack = [];
  const pushStack = (node2) => {
    stack.push(node2);
  };
  const popStack = () => {
    if (stack.length > 0) {
      stack.pop();
    }
  };
  const processEvent = (event) => {
    const parent = stack.length > 0 ? stack[stack.length - 1] : null;
    switch (event.event) {
      case STEP:
        if (event.action === ACTION_BEGIN) {
          const node2 = createNode(event, parent);
          pushStack(node2);
        } else {
          popStack();
        }
        break;
      case SPAN_BEGIN: {
        const node2 = createNode(event, parent);
        pushStack(node2);
        break;
      }
      case SPAN_END:
        popStack();
        break;
      default:
        createNode(event, parent);
        break;
    }
  };
  events.forEach(processEvent);
  return rootNodes;
};
const createNodeFactory = (depth) => {
  const rootNodes = [];
  const childCounts = /* @__PURE__ */ new Map();
  const pathByNode = /* @__PURE__ */ new Map();
  const createNode = (event, parent) => {
    const parentKey = parent ?? null;
    const nextIndex = childCounts.get(parentKey) ?? 0;
    childCounts.set(parentKey, nextIndex + 1);
    const parentPath = parent ? pathByNode.get(parent) : void 0;
    const path = parentPath !== void 0 ? `${parentPath}.${nextIndex}` : `${nextIndex}`;
    const eventId = event.uuid || `event_node_${path}`;
    const nodeDepth = parent ? parent.depth + 1 : depth;
    const node2 = new EventNode(eventId, event, nodeDepth);
    pathByNode.set(node2, path);
    if (parent) {
      parent.children.push(node2);
    } else {
      rootNodes.push(node2);
    }
    return node2;
  };
  return { rootNodes, createNode };
};
const resolveParentForEvent = (event, spanNodes) => {
  if (event.event === SPAN_BEGIN) {
    const parentId = event.parent_id;
    if (parentId) {
      return spanNodes.get(parentId) ?? null;
    }
    return null;
  }
  const spanId = getEventSpanId(event);
  if (spanId !== null) {
    return spanNodes.get(spanId) ?? null;
  }
  return null;
};
const getEventSpanId = (event) => {
  const spanId = event.span_id;
  return spanId ?? null;
};
const kBeginScorerId = "E617087FA405";
const kEndScorerId = "C39922B09481";
const kScorersSpanId = "C5A831026F2C";
const injectScorersSpan = (events) => {
  const results = [];
  const collectedScorerEvents = [];
  let hasCollectedScorers = false;
  let collecting = null;
  const flushCollected = () => {
    if (collectedScorerEvents.length > 0) {
      const beginSpan = {
        name: "scorers",
        id: kBeginScorerId,
        span_id: kScorersSpanId,
        event: SPAN_BEGIN,
        type: TYPE_SCORERS,
        timestamp: collectedScorerEvents[0].timestamp,
        working_start: collectedScorerEvents[0].working_start,
        pending: false,
        parent_id: null,
        uuid: null,
        metadata: null
      };
      const scoreEvents = collectedScorerEvents.map((event) => {
        return {
          ...event,
          parent_id: event.event === "span_begin" ? event.parent_id || kScorersSpanId : null
        };
      });
      const endSpan = {
        id: kEndScorerId,
        span_id: kScorersSpanId,
        event: SPAN_END,
        pending: false,
        working_start: collectedScorerEvents[collectedScorerEvents.length - 1].working_start,
        timestamp: collectedScorerEvents[collectedScorerEvents.length - 1].timestamp,
        uuid: null,
        metadata: null
      };
      collectedScorerEvents.length = 0;
      hasCollectedScorers = true;
      return [beginSpan, ...scoreEvents, endSpan];
    }
    return [];
  };
  for (const event of events) {
    if (event.event === SPAN_BEGIN && event.type === TYPE_SCORERS) {
      return events;
    }
    if (event.event === SPAN_BEGIN && event.type === TYPE_SCORER && !hasCollectedScorers) {
      collecting = event.span_id;
    }
    if (collecting) {
      if (event.event === SPAN_END && event.span_id === collecting) {
        collecting = null;
        results.push(...flushCollected());
        results.push(event);
      } else {
        collectedScorerEvents.push(event);
      }
    } else {
      results.push(event);
    }
  }
  return results;
};
const useEventNodes = (events, running) => {
  const { eventTree, defaultCollapsedIds } = reactExports.useMemo(() => {
    const resolvedEvents = fixupEventStream(events, !running);
    const rawEventTree = treeifyEvents(resolvedEvents, 0);
    const filterEmpty = (eventNodes) => {
      return eventNodes.filter((node2) => {
        if (node2.children && node2.children.length > 0) {
          node2.children = filterEmpty(node2.children);
        }
        return node2.event.event !== "span_begin" && node2.event.event !== "step" || node2.children && node2.children.length > 0;
      });
    };
    const eventTree2 = filterEmpty(rawEventTree);
    const defaultCollapsedIds2 = {};
    const findCollapsibleEvents = (nodes) => {
      for (const node2 of nodes) {
        if (kCollapsibleEventTypes.includes(node2.event.event) && collapseFilters.some(
          (filter) => filter(
            node2.event
          )
        )) {
          defaultCollapsedIds2[node2.id] = true;
        }
        findCollapsibleEvents(node2.children);
      }
    };
    findCollapsibleEvents(eventTree2);
    return { eventTree: eventTree2, defaultCollapsedIds: defaultCollapsedIds2 };
  }, [events, running]);
  return { eventNodes: eventTree, defaultCollapsedIds };
};
const collapseFilters = [
  (event) => event.type === "solver" && event.name === "system_message",
  (event) => {
    if (event.event === "step" || event.event === "span_begin") {
      return event.name === kSandboxSignalName || event.name === "init" || event.name === "sample_init";
    }
    return false;
  },
  (event) => event.event === "tool" && !event.agent && !event.failed,
  (event) => event.event === "subtask"
];
const TranscriptPanel = reactExports.memo((props) => {
  let { id, scrollRef, events, running, initialEventId, topOffset } = props;
  const filteredEventTypes = useStore(
    (state) => state.sample.eventFilter.filteredTypes
  );
  const sampleStatus = useStore((state) => state.sample.sampleStatus);
  const filteredEvents = reactExports.useMemo(() => {
    if (filteredEventTypes.length === 0) {
      return events;
    }
    return events.filter((event) => {
      return !filteredEventTypes.includes(event.event);
    });
  }, [events, filteredEventTypes]);
  const { eventNodes, defaultCollapsedIds } = useEventNodes(
    filteredEvents,
    running === true
  );
  const collapsedEvents = useStore((state) => state.sample.collapsedEvents);
  const setCollapsedEvents = useStore(
    (state) => state.sampleActions.setCollapsedEvents
  );
  const flattenedNodes = reactExports.useMemo(() => {
    return flatTree(
      eventNodes,
      (collapsedEvents ? collapsedEvents[kTranscriptCollapseScope] : void 0) || defaultCollapsedIds
    );
  }, [eventNodes, collapsedEvents, defaultCollapsedIds]);
  const outlineFilteredNodes = reactExports.useMemo(() => {
    return flatTree(
      eventNodes,
      (collapsedEvents ? collapsedEvents[kTranscriptOutlineCollapseScope] : void 0) || defaultCollapsedIds,
      [
        // Strip specific nodes
        removeNodeVisitor("logger"),
        removeNodeVisitor("info"),
        removeNodeVisitor("state"),
        removeNodeVisitor("store"),
        removeNodeVisitor("approval"),
        removeNodeVisitor("input"),
        removeNodeVisitor("sandbox"),
        // Strip the sandbox wrapper (and children)
        removeStepSpanNameVisitor(kSandboxSignalName),
        // Remove child events for scorers
        noScorerChildren()
      ]
    );
  }, [eventNodes, collapsedEvents, defaultCollapsedIds]);
  const turnMap = reactExports.useMemo(() => {
    const turns = makeTurns(outlineFilteredNodes);
    const map = /* @__PURE__ */ new Map();
    const turnNodes = turns.filter(
      (n) => n.event.event === "span_begin" && n.event.type === "turn"
    );
    const totalTurns = turnNodes.length;
    let turnNumber = 0;
    const modelEventTurnNumbers = /* @__PURE__ */ new Map();
    for (const node2 of turnNodes) {
      turnNumber++;
      const modelChild = node2.children.find((c) => c.event.event === "model");
      if (modelChild) {
        modelEventTurnNumbers.set(modelChild.id, turnNumber);
      }
    }
    let currentTurn = 0;
    for (const node2 of flattenedNodes) {
      const modelTurn = modelEventTurnNumbers.get(node2.id);
      if (modelTurn !== void 0) {
        currentTurn = modelTurn;
        map.set(node2.id, { turnNumber: currentTurn, totalTurns });
      } else if (currentTurn > 0) {
        map.set(node2.id, { turnNumber: currentTurn, totalTurns });
      }
    }
    return map;
  }, [outlineFilteredNodes, flattenedNodes]);
  const collapsedMode = useStore((state) => state.sample.collapsedMode);
  reactExports.useEffect(() => {
    if (events.length <= 0 || collapsedMode !== null) {
      return;
    }
    if (!collapsedEvents && Object.keys(defaultCollapsedIds).length > 0) {
      setCollapsedEvents(kTranscriptCollapseScope, defaultCollapsedIds);
    }
  }, [
    defaultCollapsedIds,
    collapsedEvents,
    setCollapsedEvents,
    events.length,
    collapsedMode
  ]);
  const allNodesList = reactExports.useMemo(() => {
    return flatTree(eventNodes, null);
  }, [eventNodes]);
  reactExports.useEffect(() => {
    if (events.length <= 0 || collapsedMode === null) {
      return;
    }
    const collapseIds = {};
    const collapsed22 = collapsedMode === "collapsed";
    allNodesList.forEach((node2) => {
      if (node2.event.uuid && (collapsed22 && !hasSpans(node2.children.map((child) => child.event)) || !collapsed22)) {
        collapseIds[node2.event.uuid] = collapsedMode === "collapsed";
      }
    });
    setCollapsedEvents(kTranscriptCollapseScope, collapseIds);
  }, [collapsedMode, events, allNodesList, setCollapsedEvents]);
  const { logPath } = useLogRouteParams();
  const [collapsed2, setCollapsed] = useCollapsedState(
    `transcript-panel-${logPath || "na"}`,
    false
  );
  const listHandle = reactExports.useRef(null);
  reactExports.useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.metaKey || event.ctrlKey) {
        if (event.key === "ArrowUp") {
          listHandle.current?.scrollToIndex({ index: 0, align: "center" });
          event.preventDefault();
        } else if (event.key === "ArrowDown") {
          listHandle.current?.scrollToIndex({
            index: Math.max(flattenedNodes.length - 5, 0),
            align: "center",
            behavior: "auto"
          });
          setTimeout(() => {
            listHandle.current?.scrollToIndex({
              index: Math.max(flattenedNodes.length - 1, 0),
              align: "end",
              behavior: "auto"
            });
          }, 250);
        }
      }
    };
    const scrollElement = scrollRef.current;
    if (scrollElement) {
      scrollElement.addEventListener("keydown", handleKeyDown);
      if (!scrollElement.hasAttribute("tabIndex")) {
        scrollElement.setAttribute("tabIndex", "0");
      }
      return () => {
        scrollElement.removeEventListener("keydown", handleKeyDown);
      };
    }
  }, [scrollRef, flattenedNodes]);
  if (sampleStatus === "loading" && flattenedNodes.length === 0) {
    return void 0;
  }
  if (flattenedNodes.length === 0) {
    const isCompletedFiltered = flattenedNodes.length === 0 && events.length > 0;
    const message2 = isCompletedFiltered ? "The currently applied filter hides all events." : "No events to display.";
    return /* @__PURE__ */ jsxRuntimeExports.jsx(NoContentsPanel, { text: message2 });
  } else {
    return /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        className: clsx(
          styles$l.container,
          collapsed2 ? styles$l.collapsed : void 0
        ),
        children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs(
            StickyScroll,
            {
              scrollRef,
              className: styles$l.treeContainer,
              offsetTop: topOffset,
              children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx(
                  TranscriptOutline,
                  {
                    className: clsx(styles$l.outline),
                    eventNodes,
                    filteredNodes: outlineFilteredNodes,
                    running,
                    defaultCollapsedIds,
                    scrollRef
                  }
                ),
                /* @__PURE__ */ jsxRuntimeExports.jsx(
                  "div",
                  {
                    className: styles$l.outlineToggle,
                    onClick: () => setCollapsed(!collapsed2),
                    children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: ApplicationIcons.sidebar })
                  }
                )
              ]
            }
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            TranscriptVirtualList,
            {
              id,
              listHandle,
              eventNodes: flattenedNodes,
              scrollRef,
              running,
              initialEventId: initialEventId === void 0 ? null : initialEventId,
              offsetTop: topOffset,
              className: styles$l.listContainer,
              turnMap
            }
          )
        ]
      }
    );
  }
});
const SampleDisplay = ({
  id,
  scrollRef,
  focusOnLoad
}) => {
  const baseId = `sample-display`;
  const sampleData = useSampleData();
  const sample2 = reactExports.useMemo(() => {
    return sampleData.getSelectedSample();
  }, [sampleData]);
  const runningSampleData = sampleData.running;
  const evalSpec = useStore((state) => state.log.selectedLogDetails?.eval);
  const { setDocumentTitle } = useDocumentTitle();
  reactExports.useEffect(() => {
    setDocumentTitle({ evalSpec, sample: sample2 });
  }, [setDocumentTitle, sample2, evalSpec]);
  const selectedTab = useStore((state) => state.app.tabs.sample);
  const setSelectedTab = useStore((state) => state.appActions.setSampleTab);
  const { sampleTabId } = useParams();
  const effectiveSelectedTab = sampleTabId || selectedTab;
  const navigate = useNavigate();
  const tabsRef = reactExports.useRef(null);
  const [tabsHeight, setTabsHeight] = reactExports.useState(-1);
  reactExports.useEffect(() => {
    const updateHeight = () => {
      if (tabsRef.current) {
        const height = tabsRef.current.getBoundingClientRect().height;
        setTabsHeight(height);
      }
    };
    updateHeight();
    window.addEventListener("resize", updateHeight);
    return () => window.removeEventListener("resize", updateHeight);
  }, []);
  const selectedSampleSummary = useSelectedSampleSummary();
  const sampleEvents = sample2?.events || runningSampleData;
  const sampleMessages = reactExports.useMemo(() => {
    if (sample2?.messages) {
      return sample2.messages;
    } else if (runningSampleData) {
      return messagesFromEvents(runningSampleData);
    } else {
      return [];
    }
  }, [sample2?.messages, runningSampleData]);
  const {
    logPath: urlLogPath,
    id: urlSampleId,
    epoch: urlEpoch
  } = useLogOrSampleRouteParams();
  reactExports.useEffect(() => {
    setTimeout(() => {
      if (focusOnLoad) {
        scrollRef.current?.focus();
      }
    }, 10);
  }, [focusOnLoad, scrollRef]);
  const sampleUrlBuilder = useSampleUrlBuilder();
  const onSelectedTab = reactExports.useCallback(
    (e) => {
      const el = e.currentTarget;
      const id2 = el.id;
      setSelectedTab(id2);
      if (id2 !== sampleTabId && urlLogPath) {
        const url = sampleUrlBuilder(urlLogPath, urlSampleId, urlEpoch, id2);
        navigate(url);
      }
    },
    [
      setSelectedTab,
      sampleTabId,
      urlLogPath,
      sampleUrlBuilder,
      urlSampleId,
      urlEpoch,
      navigate
    ]
  );
  const sampleMetadatas = metadataViewsForSample(
    `${baseId}-${id}`,
    scrollRef,
    sample2
  );
  const tabsetId = `task-sample-details-tab-${id}`;
  const targetId = `${tabsetId}-content`;
  const isShowing = useStore((state) => state.app.dialogs.transcriptFilter);
  const setShowing = useStore(
    (state) => state.appActions.setShowingTranscriptFilterDialog
  );
  const displayMode = useStore((state) => state.app.displayMode);
  const setDisplayMode = useStore((state) => state.appActions.setDisplayMode);
  const filterRef = reactExports.useRef(null);
  const optionsRef = reactExports.useRef(null);
  const handlePrintClick = reactExports.useCallback(() => {
    printSample(id, targetId);
  }, [id, targetId]);
  const toggleFilter = reactExports.useCallback(() => {
    setShowing(!isShowing);
  }, [setShowing, isShowing]);
  const toggleDisplayMode = reactExports.useCallback(() => {
    setDisplayMode(displayMode === "rendered" ? "raw" : "rendered");
  }, [displayMode, setDisplayMode]);
  const collapsedMode = useStore((state) => state.sample.collapsedMode);
  const setCollapsedMode = useStore(
    (state) => state.sampleActions.setCollapsedMode
  );
  const isCollapsed = (mode) => {
    return mode === "collapsed";
  };
  const toggleCollapsedMode = reactExports.useCallback(() => {
    setCollapsedMode(isCollapsed(collapsedMode) ? "expanded" : "collapsed");
  }, [collapsedMode, setCollapsedMode]);
  const { isDebugFilter, isDefaultFilter } = useTranscriptFilter();
  const api = useStore((state) => state.api);
  const downloadFiles = useStore((state) => state.capabilities.downloadFiles);
  const tools2 = [];
  const [icon2, setIcon] = reactExports.useState(ApplicationIcons.copy);
  tools2.push(
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      ToolDropdownButton,
      {
        label: "Copy",
        icon: icon2,
        items: {
          UUID: () => {
            if (sample2?.uuid) {
              navigator.clipboard.writeText(sample2.uuid);
              setIcon(ApplicationIcons.confirm);
              setTimeout(() => {
                setIcon(ApplicationIcons.copy);
              }, 1250);
            }
          },
          Transcript: () => {
            if (sample2?.messages) {
              navigator.clipboard.writeText(messagesToStr(sample2.messages));
              setIcon(ApplicationIcons.confirm);
              setTimeout(() => {
                setIcon(ApplicationIcons.copy);
              }, 1250);
            }
          }
        }
      },
      "sample-copy"
    )
  );
  if (downloadFiles && sample2 && api?.download_file) {
    const sampleId = sample2.id ?? "sample";
    tools2.push(
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        ToolDropdownButton,
        {
          label: "Download",
          icon: ApplicationIcons.downloadLog,
          items: {
            "Sample JSON": () => {
              api.download_file(
                `${sampleId}.json`,
                JSON.stringify(sample2, null, 2)
              );
            },
            Transcript: () => {
              api.download_file(
                `${sampleId}-transcript.txt`,
                messagesToStr(sample2.messages ?? [])
              );
            }
          }
        },
        "sample-download"
      )
    );
  }
  if (selectedTab === kSampleTranscriptTabId) {
    const label2 = isDebugFilter ? "Debug" : isDefaultFilter ? "Default" : "Custom";
    tools2.push(
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        ToolButton,
        {
          label: `Events: ${label2}`,
          icon: ApplicationIcons.filter,
          onClick: toggleFilter,
          ref: filterRef
        },
        "sample-filter-transcript"
      )
    );
    tools2.push(
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        ToolButton,
        {
          label: isCollapsed(collapsedMode) ? "Expand" : "Collapse",
          icon: isCollapsed(collapsedMode) ? ApplicationIcons.expand.all : ApplicationIcons.collapse.all,
          onClick: toggleCollapsedMode
        },
        "sample-collapse-transcript"
      )
    );
  }
  tools2.push(
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      ToolButton,
      {
        label: "Raw",
        icon: ApplicationIcons.display,
        onClick: toggleDisplayMode,
        ref: optionsRef,
        latched: displayMode === "raw"
      },
      "options-button"
    )
  );
  if (!isVscode()) {
    tools2.push(
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        ToolButton,
        {
          label: "Print",
          icon: ApplicationIcons.copy,
          onClick: handlePrintClick
        },
        "sample-print-tool"
      )
    );
  }
  const running = reactExports.useMemo(() => {
    return isRunning(selectedSampleSummary, runningSampleData);
  }, [selectedSampleSummary, runningSampleData]);
  const sampleDetailNavigation = useSampleDetailNavigation();
  const displaySample = sample2 || selectedSampleSummary;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(reactExports.Fragment, { children: [
    displaySample ? /* @__PURE__ */ jsxRuntimeExports.jsx(SampleSummaryView, { parent_id: id, sample: displaySample }) : void 0,
    /* @__PURE__ */ jsxRuntimeExports.jsxs(
      TabSet,
      {
        id: tabsetId,
        tabsRef,
        className: clsx(styles$t.tabControls),
        tabControlsClassName: clsx("text-size-base"),
        tabPanelsClassName: clsx(styles$t.tabPanel),
        tools: tools2,
        children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs(
            TabPanel,
            {
              id: kSampleTranscriptTabId,
              className: clsx("sample-tab", styles$t.transcriptContainer),
              title: "Transcript",
              onSelected: onSelectedTab,
              selected: effectiveSelectedTab === kSampleTranscriptTabId || effectiveSelectedTab === void 0,
              scrollable: false,
              children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx(
                  TranscriptFilterPopover,
                  {
                    showing: isShowing,
                    setShowing,
                    positionEl: filterRef.current
                  }
                ),
                /* @__PURE__ */ jsxRuntimeExports.jsx(
                  TranscriptPanel,
                  {
                    id: `${baseId}-transcript-display-${id}`,
                    events: sampleEvents || [],
                    initialEventId: sampleDetailNavigation.event,
                    topOffset: tabsHeight,
                    running,
                    scrollRef
                  },
                  `${baseId}-transcript-display-${id}`
                )
              ]
            },
            kSampleTranscriptTabId
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            TabPanel,
            {
              id: kSampleMessagesTabId,
              className: clsx("sample-tab", styles$t.fullWidth, styles$t.chat),
              title: "Messages",
              onSelected: onSelectedTab,
              selected: effectiveSelectedTab === kSampleMessagesTabId,
              scrollable: false,
              children: /* @__PURE__ */ jsxRuntimeExports.jsx(
                ChatViewVirtualList,
                {
                  id: `${baseId}-chat-${id}`,
                  messages: sampleMessages,
                  initialMessageId: sampleDetailNavigation.message,
                  topOffset: tabsHeight,
                  indented: true,
                  scrollRef,
                  toolCallStyle: "complete",
                  running,
                  className: styles$t.fullWidth
                },
                `${baseId}-chat-${id}`
              )
            },
            kSampleMessagesTabId
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            TabPanel,
            {
              id: kSampleScoringTabId,
              className: "sample-tab",
              title: "Scoring",
              onSelected: onSelectedTab,
              selected: effectiveSelectedTab === kSampleScoringTabId,
              children: /* @__PURE__ */ jsxRuntimeExports.jsx(
                SampleScoresView,
                {
                  sample: sample2,
                  className: styles$t.padded,
                  scrollRef
                }
              )
            },
            kSampleScoringTabId
          ),
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            TabPanel,
            {
              id: kSampleMetdataTabId,
              className: clsx("sample-tab"),
              title: "Metadata",
              onSelected: onSelectedTab,
              selected: effectiveSelectedTab === kSampleMetdataTabId,
              children: !sample2 || sampleMetadatas.length > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$t.padded, styles$t.fullWidth), children: sampleMetadatas }) : /* @__PURE__ */ jsxRuntimeExports.jsx(NoContentsPanel, { text: "No metadata" })
            }
          ),
          sample2?.error || sample2?.error_retries && sample2?.error_retries.length > 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx(
            TabPanel,
            {
              id: kSampleErrorTabId,
              className: "sample-tab",
              title: "Errors",
              onSelected: onSelectedTab,
              selected: effectiveSelectedTab === kSampleErrorTabId,
              children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles$t.error), children: [
                sample2?.error ? /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: `Sample Error` }),
                  /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { children: /* @__PURE__ */ jsxRuntimeExports.jsx(
                    ANSIDisplay,
                    {
                      output: sample2.error.traceback_ansi,
                      className: clsx("text-size-small", styles$t.ansi),
                      style: {
                        fontSize: "clamp(0.3rem, 1.1vw, 0.8rem)",
                        margin: "0.5em 0"
                      }
                    }
                  ) })
                ] }, `sample-error}`) : void 0,
                sample2.error_retries?.map((retry, index) => {
                  return /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
                    /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: `Attempt ${index + 1}` }),
                    /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { children: /* @__PURE__ */ jsxRuntimeExports.jsx(
                      ANSIDisplay,
                      {
                        output: retry.traceback_ansi,
                        className: clsx("text-size-small", styles$t.ansi),
                        style: {
                          fontSize: "clamp(0.3rem, 1.1vw, 0.8rem)",
                          margin: "0.5em 0"
                        }
                      }
                    ) })
                  ] }, `sample-retry-error-${index}`);
                })
              ] })
            }
          ) : null,
          /* @__PURE__ */ jsxRuntimeExports.jsx(
            TabPanel,
            {
              id: kSampleJsonTabId,
              className: "sample-tab",
              title: "JSON",
              onSelected: onSelectedTab,
              selected: effectiveSelectedTab === kSampleJsonTabId,
              children: !sample2 ? /* @__PURE__ */ jsxRuntimeExports.jsx(NoContentsPanel, { text: "JSON not available" }) : estimateSize(sample2.events) > 25 * 1024 * 1024 ? /* @__PURE__ */ jsxRuntimeExports.jsx(NoContentsPanel, { text: "JSON too large to display" }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles$t.padded, styles$t.fullWidth), children: /* @__PURE__ */ jsxRuntimeExports.jsx(
                JSONPanel,
                {
                  data: sample2,
                  simple: true,
                  className: clsx("text-size-small")
                }
              ) })
            }
          )
        ]
      }
    )
  ] });
};
const metadataViewsForSample = (id, scrollRef, sample2) => {
  if (!sample2) {
    return [];
  }
  const sampleMetadatas = [];
  if (sample2.invalidation) {
    const formatTimestamp = (timestamp) => {
      try {
        return formatDateTime(new Date(timestamp));
      } catch {
        return timestamp;
      }
    };
    const invalidationRecord = {};
    if (sample2.invalidation.author) {
      invalidationRecord["Author"] = sample2.invalidation.author;
    }
    if (sample2.invalidation.timestamp) {
      invalidationRecord["Timestamp"] = formatTimestamp(
        sample2.invalidation.timestamp
      );
    }
    if (sample2.invalidation.reason) {
      invalidationRecord["Reason"] = sample2.invalidation.reason;
    }
    if (sample2.invalidation.metadata && Object.keys(sample2.invalidation.metadata).length > 0) {
      invalidationRecord["Metadata"] = sample2.invalidation.metadata;
    }
    sampleMetadatas.push(
      /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: "Invalidation" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { padded: false, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          RecordTree,
          {
            id: `task-sample-invalidation-${id}`,
            record: invalidationRecord,
            className: clsx("tab-pane", styles$t.noTop),
            scrollRef
          }
        ) })
      ] }, `sample-invalidation-${id}`)
    );
  }
  if (sample2.model_usage && Object.keys(sample2.model_usage).length > 0) {
    sampleMetadatas.push(
      /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: "Usage" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          ModelTokenTable,
          {
            model_usage: sample2.model_usage,
            className: clsx(styles$t.noTop)
          }
        ) })
      ] }, `sample-usage-${id}`)
    );
  }
  if (sample2.total_time !== void 0 && sample2.total_time !== null && sample2.working_time !== void 0 && sample2.working_time !== null) {
    sampleMetadatas.push(
      /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: "Time" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { padded: false, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          RecordTree,
          {
            id: `task-sample-time-${id}`,
            record: {
              Working: formatTime(sample2.working_time),
              Total: formatTime(sample2.total_time)
            },
            className: clsx("tab-pane", styles$t.noTop),
            scrollRef
          }
        ) })
      ] }, `sample-time-${id}`)
    );
  }
  if (Object.keys(sample2?.metadata).length > 0) {
    sampleMetadatas.push(
      /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: "Metadata" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { padded: false, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          RecordTree,
          {
            id: `task-sample-metadata-${id}`,
            record: sample2?.metadata,
            className: clsx("tab-pane", styles$t.noTop),
            scrollRef
          }
        ) })
      ] }, `sample-metadata-${id}`)
    );
  }
  if (Object.keys(sample2?.store).length > 0) {
    sampleMetadatas.push(
      /* @__PURE__ */ jsxRuntimeExports.jsxs(Card, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(CardHeader, { label: "Store" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(CardBody, { padded: false, children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          RecordTree,
          {
            id: `task-sample-store-${id}`,
            record: sample2?.store,
            className: clsx("tab-pane", styles$t.noTop),
            scrollRef,
            processStore: true
          }
        ) })
      ] }, `sample-store-${id}`)
    );
  }
  return sampleMetadatas;
};
const printSample = (id, targetId) => {
  const targetTabEl = document.querySelector(
    `#${escapeSelector(targetId)} .sample-tab.tab-pane.show.active`
  );
  if (targetTabEl) {
    const targetEl = targetTabEl.firstElementChild;
    if (targetEl) {
      const headingId = `sample-heading-${id}`;
      const headingEl = document.getElementById(headingId);
      const headingHtml = printHeadingHtml();
      const css = `
      html { font-size: 9pt }
      /* Allow content to break anywhere without any forced page breaks */
      * {
        break-inside: auto;  /* Let elements break anywhere */
        page-break-inside: auto;  /* Legacy support */
        break-before: auto;
        page-break-before: auto;
        break-after: auto;
        page-break-after: auto;
      }
      /* Specifically disable all page breaks for divs */
      div {
        break-inside: auto;
        page-break-inside: auto;
      }
      body > .transcript-step {
        break-inside: avoid;
      }
      body{
        -webkit-print-color-adjust:exact !important;
        print-color-adjust:exact !important;
      }
      /* Allow preformatted text and code blocks to break across pages */
      pre, code {
          white-space: pre-wrap; /* Wrap long lines instead of keeping them on one line */
          overflow-wrap: break-word; /* Ensure long words are broken to fit within the page */
          break-inside: auto; /* Allow page breaks inside the element */
          page-break-inside: auto; /* Older equivalent */
      }

      /* Additional control for long lines within code/preformatted blocks */
      pre {
          word-wrap: break-word; /* Break long words if needed */
      }    
          
      `;
      printHtml(
        [headingHtml, headingEl?.outerHTML, targetEl.innerHTML].join("\n"),
        css
      );
    }
  }
};
const isRunning = (sampleSummary, runningSampleData) => {
  if (sampleSummary && sampleSummary.completed === false) {
    return true;
  }
  if (!sampleSummary && (!runningSampleData || runningSampleData.length === 0)) {
    return true;
  }
  if (runningSampleData && runningSampleData.length > 0) {
    return true;
  }
  return false;
};
const container = "_container_ly812_1";
const scroller = "_scroller_ly812_7";
const styles = {
  container,
  scroller
};
const InlineSampleDisplay = ({
  showActivity,
  className
}) => {
  useLoadSample();
  usePollSample();
  return /* @__PURE__ */ jsxRuntimeExports.jsx(InlineSampleComponent, { showActivity, className });
};
const InlineSampleComponent = ({
  showActivity,
  className
}) => {
  const sampleData = useSampleData();
  const scrollRef = reactExports.useRef(null);
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(className, styles.container), children: [
    showActivity && /* @__PURE__ */ jsxRuntimeExports.jsx(
      ActivityBar,
      {
        animating: sampleData.status === "loading" || sampleData.status === "streaming"
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: clsx(styles.scroller), ref: scrollRef, children: /* @__PURE__ */ jsxRuntimeExports.jsx(StickyScrollProvider, { value: scrollRef, children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: styles.body, children: sampleData.error ? /* @__PURE__ */ jsxRuntimeExports.jsx(
      ErrorPanel,
      {
        title: "Unable to load sample",
        error: sampleData.error
      }
    ) : /* @__PURE__ */ jsxRuntimeExports.jsx(
      SampleDisplay,
      {
        id: "inline-sample-display",
        scrollRef
      }
    ) }) }) })
  ] });
};
export {
  Card as C,
  EmptyPanel as E,
  FindBand as F,
  InlineSampleDisplay as I,
  ModelTokenTable as M,
  NoContentsPanel as N,
  PulsingDots as P,
  TabSet as T,
  CardHeader as a,
  CardBody as b,
  TabPanel as c,
  ExtendedFindProvider as d,
  usePollSample as e,
  InlineSampleComponent as f,
  truncateMarkdown as t,
  useLoadSample as u
};
//# sourceMappingURL=InlineSampleDisplay.js.map
