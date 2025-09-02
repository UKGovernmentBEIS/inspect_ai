import clsx from "clsx";
import {
  FC,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { ApplicationIcons } from "../app/appearance/icons";
import { useStore } from "../state/store";
import styles from "./FindBand.module.css";

interface FindBandProps {}

export const FindBand: FC<FindBandProps> = () => {
  const searchBoxRef = useRef<HTMLInputElement>(null);
  const hideFind = useStore((state) => state.appActions.hideFind);

  const setFindTerm = useStore((state) => state.appActions.setFindTerm);
  const findTerm = useStore((state) => state.app.find.term);
  const findIndex = useStore((state) => state.app.find.index);
  const findResults = useStore((state) => state.app.find.results);
  const searching = useStore((state) => state.app.find.searching);
  const setFindIndex = useStore((state) => state.appActions.setFindIndex);
  const setSearching = useStore((state) => state.appActions.setSearching);

  const findMatches = useMemo(() => {
    return Object.values(findResults || {}).reduce((a, b) => a + b, 0);
  }, [findResults]);

  useEffect(() => {
    setTimeout(() => {
      searchBoxRef.current?.focus();
    }, 10);
  }, []);

  const handleSearch = useCallback(
    (back = false) => {
      if (searching) {
        const currentIndex = findIndex ?? -1;
        const nextIndex = !back ? currentIndex + 1 : currentIndex - 1;
        const normalized = Math.max(
          0,
          Math.min((findMatches ?? 1) - 1, nextIndex),
        );
        setFindIndex(normalized);
      } else {
        setSearching(true);
      }
    },
    [findTerm, findIndex, findMatches, searching, setFindIndex],
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Escape") {
        hideFind();
      } else if (e.key === "Enter") {
        handleSearch(false);
      }
    },
    [hideFind, handleSearch],
  );

  const next = useCallback(() => {
    handleSearch(true);
  }, [handleSearch]);

  const previous = useCallback(() => {
    handleSearch(false);
  }, [handleSearch]);

  return (
    <div className={clsx(styles.findBand)}>
      <input
        type="text"
        value={findTerm}
        onChange={(e) => setFindTerm(e.target.value)}
        placeholder="Find"
        onKeyDown={handleKeyDown}
        ref={searchBoxRef}
      />
      <span
        className={clsx(
          styles.findNoResults,
          findResults !== undefined ? styles.visible : undefined,
        )}
      >
        {findResults !== undefined && findMatches > 0
          ? `${findIndex! + 1} of ${findMatches}`
          : "No results"}
      </span>
      <button
        type="button"
        title="Previous match"
        className="btn next"
        onClick={next}
      >
        <i className={ApplicationIcons.arrows.up} />
      </button>
      <button
        type="button"
        title="Next match"
        className="btn prev"
        onClick={previous}
      >
        <i className={ApplicationIcons.arrows.down} />
      </button>
      <button
        type="button"
        title="Close"
        className="btn close"
        onClick={hideFind}
      >
        <i className={ApplicationIcons.close} />
      </button>
    </div>
  );
};
