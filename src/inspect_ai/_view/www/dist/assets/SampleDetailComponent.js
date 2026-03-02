import { u as useStore, j as jsxRuntimeExports, A as ApplicationIcons } from "./index.js";
import { b as reactExports } from "./vendor-grid.js";
import { d as ExtendedFindProvider, F as FindBand, f as InlineSampleComponent } from "./InlineSampleDisplay.js";
import { X as useSampleData, A as ApplicationNavbar, c as clsx } from "./ApplicationNavbar.js";
const detail = "_detail_14cqz_1";
const panel = "_panel_14cqz_7";
const sampleInfo = "_sampleInfo_14cqz_11";
const sampleNav = "_sampleNav_14cqz_17";
const nav = "_nav_14cqz_25";
const disabled = "_disabled_14cqz_25";
const styles = {
  detail,
  panel,
  sampleInfo,
  sampleNav,
  nav,
  disabled
};
const SampleDetailComponent = ({
  sampleId,
  epoch,
  tabId,
  navigation,
  navbarConfig
}) => {
  const { onPrevious, onNext, hasPrevious, hasNext } = navigation;
  const {
    currentPath,
    fnNavigationUrl,
    bordered = true,
    breadcrumbsEnabled
  } = navbarConfig;
  const sampleData = useSampleData();
  const sample = reactExports.useMemo(() => {
    return sampleData.getSelectedSample();
  }, [sampleData]);
  const sampleStatus = useStore((state) => state.sample.sampleStatus);
  const sampleMatchesRequest = reactExports.useMemo(() => {
    if (!sample || !sampleId || !epoch) return false;
    return String(sample.id) === sampleId && sample.epoch === parseInt(epoch, 10);
  }, [sample, sampleId, epoch]);
  const showFind = useStore((state) => state.app.showFind);
  const setShowFind = useStore((state) => state.appActions.setShowFind);
  const hideFind = useStore((state) => state.appActions.hideFind);
  const nativeFind = useStore((state) => state.app.nativeFind);
  const setSampleTab = useStore((state) => state.appActions.setSampleTab);
  reactExports.useEffect(() => {
    if (tabId) {
      setSampleTab(tabId);
    }
  }, [tabId, setSampleTab]);
  const handleKeyDown = reactExports.useCallback(
    (e) => {
      const activeElement = document.activeElement;
      const isInputFocused = activeElement && (activeElement.tagName === "INPUT" || activeElement.tagName === "TEXTAREA" || activeElement.tagName === "SELECT");
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        if (!nativeFind) {
          e.preventDefault();
          e.stopPropagation();
          setShowFind(true);
        }
      } else if (e.key === "Escape") {
        if (!nativeFind) {
          hideFind();
        }
      } else if (!isInputFocused) {
        if (e.key === "ArrowLeft") {
          if (hasPrevious) {
            e.preventDefault();
            onPrevious();
          }
        } else if (e.key === "ArrowRight") {
          if (hasNext) {
            e.preventDefault();
            onNext();
          }
        }
      }
    },
    [
      setShowFind,
      hideFind,
      hasPrevious,
      hasNext,
      nativeFind,
      onPrevious,
      onNext
    ]
  );
  reactExports.useEffect(() => {
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [handleKeyDown]);
  const handleNavButtonKeyDown = reactExports.useCallback(
    (e, action, enabled) => {
      if ((e.key === "Enter" || e.key === " ") && enabled) {
        e.preventDefault();
        action();
      }
    },
    []
  );
  return /* @__PURE__ */ jsxRuntimeExports.jsxs(ExtendedFindProvider, { children: [
    showFind ? /* @__PURE__ */ jsxRuntimeExports.jsx(FindBand, {}) : "",
    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: styles.detail, children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        ApplicationNavbar,
        {
          currentPath,
          fnNavigationUrl,
          bordered,
          breadcrumbsEnabled,
          children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles.sampleNav), children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "div",
              {
                onClick: hasPrevious ? onPrevious : void 0,
                onKeyDown: (e) => handleNavButtonKeyDown(e, onPrevious, hasPrevious),
                tabIndex: hasPrevious ? 0 : -1,
                role: "button",
                "aria-label": "Previous sample",
                "aria-disabled": !hasPrevious,
                className: clsx(!hasPrevious && styles.disabled, styles.nav),
                children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx(ApplicationIcons.previous) })
              }
            ),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles.sampleInfo, "text-size-smallest"), children: [
              "Sample ",
              sampleId,
              " (Epoch ",
              epoch,
              ")"
            ] }),
            /* @__PURE__ */ jsxRuntimeExports.jsx(
              "div",
              {
                onClick: hasNext ? onNext : void 0,
                onKeyDown: (e) => handleNavButtonKeyDown(e, onNext, hasNext),
                tabIndex: hasNext ? 0 : -1,
                role: "button",
                "aria-label": "Next sample",
                "aria-disabled": !hasNext,
                className: clsx(!hasNext && styles.disabled, styles.nav),
                children: /* @__PURE__ */ jsxRuntimeExports.jsx("i", { className: clsx(ApplicationIcons.next) })
              }
            )
          ] })
        }
      ),
      sampleStatus !== "loading" && sample && sampleMatchesRequest && /* @__PURE__ */ jsxRuntimeExports.jsx(
        InlineSampleComponent,
        {
          showActivity: false,
          className: styles.panel
        }
      )
    ] })
  ] });
};
export {
  SampleDetailComponent as S
};
//# sourceMappingURL=SampleDetailComponent.js.map
