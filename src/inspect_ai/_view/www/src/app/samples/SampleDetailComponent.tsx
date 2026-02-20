import React, { FC, useCallback, useEffect, useMemo } from "react";
import { ExtendedFindProvider } from "../../components/ExtendedFindContext";
import { FindBand } from "../../components/FindBand";
import { useSampleData } from "../../state/hooks";
import { useStore } from "../../state/store";
import { ApplicationIcons } from "../appearance/icons";
import { ApplicationNavbar } from "../navbar/ApplicationNavbar";
import { InlineSampleComponent } from "./InlineSampleDisplay";

import clsx from "clsx";
import styles from "./SampleDetailComponent.module.css";

/**
 * Configuration for sample navigation (prev/next)
 */
export interface SampleNavigationConfig {
  /** Handler for navigating to previous sample */
  onPrevious: () => void;
  /** Handler for navigating to next sample */
  onNext: () => void;
  /** Whether there is a previous sample to navigate to */
  hasPrevious: boolean;
  /** Whether there is a next sample to navigate to */
  hasNext: boolean;
}

/**
 * Configuration for the application navbar
 */
export interface NavbarConfig {
  /** The current path to display in breadcrumb */
  currentPath: string | undefined;
  /** Function to build navigation URLs for breadcrumb segments */
  fnNavigationUrl: (file: string, log_dir?: string) => string;
  /** Whether to show a border on the navbar */
  bordered?: boolean;

  breadcrumbsEnabled?: boolean;
}

/**
 * Props for the SampleDetailComponent
 */
export interface SampleDetailComponentProps {
  /** The sample ID from URL params */
  sampleId: string | undefined;
  /** The epoch from URL params */
  epoch: string | undefined;
  /** The tab ID from URL params (for sample tabs like transcript, messages, etc.) */
  tabId: string | undefined;
  /** Navigation configuration for prev/next sample */
  navigation: SampleNavigationConfig;
  /** Navbar configuration for breadcrumb and back navigation */
  navbarConfig: NavbarConfig;
}

/**
 * Shared component for displaying sample details with navigation.
 * Used by both SampleDetailView (for /samples route) and LogSampleDetailView (for /logs route).
 *
 * This component handles:
 * - Keyboard shortcuts (arrow keys for nav, Ctrl+F for find)
 * - Find band integration
 * - Sample tab synchronization (URL → state)
 * - Navigation controls UI (prev/next buttons + sample info)
 * - Sample content rendering via InlineSampleComponent
 *
 * The parent component is responsible for:
 * - Loading hooks (useLoadLog, useLoadSample, usePollSample)
 * - Calculating navigation state
 * - Navigation callbacks
 * - Cleanup on unmount
 */
export const SampleDetailComponent: FC<SampleDetailComponentProps> = ({
  sampleId,
  epoch,
  tabId,
  navigation,
  navbarConfig,
}) => {
  const { onPrevious, onNext, hasPrevious, hasNext } = navigation;
  const {
    currentPath,
    fnNavigationUrl,
    bordered = true,
    breadcrumbsEnabled,
  } = navbarConfig;

  // Sample data and status
  const sampleData = useSampleData();
  const sample = useMemo(() => {
    return sampleData.getSelectedSample();
  }, [sampleData]);

  // Check if the loaded sample matches the requested sample from URL params
  // This prevents showing old sample data while a new sample is loading
  const sampleMatchesRequest = useMemo(() => {
    if (!sample || !sampleId || !epoch) {
      return true;
    }
    return (
      String(sample.id) === sampleId && sample.epoch === parseInt(epoch, 10)
    );
  }, [sample, sampleId, epoch]);

  // Find functionality
  const showFind = useStore((state) => state.app.showFind);
  const setShowFind = useStore((state) => state.appActions.setShowFind);
  const hideFind = useStore((state) => state.appActions.hideFind);
  const nativeFind = useStore((state) => state.app.nativeFind);

  // Sample tab synchronization
  const setSampleTab = useStore((state) => state.appActions.setSampleTab);

  useEffect(() => {
    // Set the sample tab if specified in the URL
    if (tabId) {
      setSampleTab(tabId);
    }
  }, [tabId, setSampleTab]);

  // Global keydown handler for keyboard shortcuts
  const handleKeyDown = useCallback(
    (e: globalThis.KeyboardEvent) => {
      // Don't handle keyboard events if focus is on an input, textarea, or select element
      const activeElement = document.activeElement;
      const isInputFocused =
        activeElement &&
        (activeElement.tagName === "INPUT" ||
          activeElement.tagName === "TEXTAREA" ||
          activeElement.tagName === "SELECT");

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
        // Navigation shortcuts (only when not in an input field)
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
      onNext,
    ],
  );

  useEffect(() => {
    // Use capture phase to catch event before it reaches other handlers
    document.addEventListener("keydown", handleKeyDown, true);

    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [handleKeyDown]);

  // Keyboard handler for navigation buttons (Enter/Space to activate)
  const handleNavButtonKeyDown = useCallback(
    (e: React.KeyboardEvent, action: () => void, enabled: boolean) => {
      if ((e.key === "Enter" || e.key === " ") && enabled) {
        e.preventDefault();
        action();
      }
    },
    [],
  );

  return (
    <ExtendedFindProvider>
      {showFind ? <FindBand /> : ""}
      <div className={styles.detail}>
        <ApplicationNavbar
          currentPath={currentPath}
          fnNavigationUrl={fnNavigationUrl}
          bordered={bordered}
          breadcrumbsEnabled={breadcrumbsEnabled}
        >
          <div className={clsx(styles.sampleNav)}>
            <div
              onClick={hasPrevious ? onPrevious : undefined}
              onKeyDown={(e) =>
                handleNavButtonKeyDown(e, onPrevious, hasPrevious)
              }
              tabIndex={hasPrevious ? 0 : -1}
              role="button"
              aria-label="Previous sample"
              aria-disabled={!hasPrevious}
              className={clsx(!hasPrevious && styles.disabled, styles.nav)}
            >
              <i className={clsx(ApplicationIcons.previous)} />
            </div>
            <div className={clsx(styles.sampleInfo, "text-size-smallest")}>
              Sample {sampleId} (Epoch {epoch})
            </div>
            <div
              onClick={hasNext ? onNext : undefined}
              onKeyDown={(e) => handleNavButtonKeyDown(e, onNext, hasNext)}
              tabIndex={hasNext ? 0 : -1}
              role="button"
              aria-label="Next sample"
              aria-disabled={!hasNext}
              className={clsx(!hasNext && styles.disabled, styles.nav)}
            >
              <i className={clsx(ApplicationIcons.next)} />
            </div>
          </div>
        </ApplicationNavbar>

        {sampleMatchesRequest && (
          <InlineSampleComponent
            showActivity={false}
            className={styles.panel}
          />
        )}
      </div>
    </ExtendedFindProvider>
  );
};
