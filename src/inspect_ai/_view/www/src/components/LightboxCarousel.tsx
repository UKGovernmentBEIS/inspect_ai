import clsx from "clsx";
import { FC, ReactNode, useCallback, useEffect } from "react";
import { ApplicationIcons } from "../appearance/icons";
import { useStore } from "../state/store";
import styles from "./LightboxCarousel.module.css";

interface Slide {
  label: string;
  render: () => ReactNode;
}

interface LightboxCarouselProps {
  id: string;
  slides: Slide[];
}

const kIsOpen = "isOpen";
const kShowOverlay = "showOverlay";
const kCurrentIndex = "currentIndex";

/**
 * LightboxCarousel component provides a carousel with lightbox functionality.
 */
export const LightboxCarousel: FC<LightboxCarouselProps> = ({ id, slides }) => {
  const isOpen = useStore((state) =>
    state.appActions.getPropertyValue(id, kIsOpen, false),
  );
  const showOverlay = useStore((state) =>
    state.appActions.getPropertyValue(id, kShowOverlay, false),
  );
  const currentIndex = useStore((state) =>
    state.appActions.getPropertyValue(id, kCurrentIndex, 0),
  );

  const setPropertyValue = useStore(
    (state) => state.appActions.setPropertyValue,
  );
  const removePropertyValue = useStore(
    (state) => state.appActions.removePropertyValue,
  );

  useEffect(() => {
    return () => {
      [kIsOpen, kShowOverlay, kCurrentIndex].forEach((p) =>
        removePropertyValue(id, p),
      );
    };
  }, []);

  const openLightbox = useCallback(
    (index: number) => {
      setPropertyValue(id, kCurrentIndex, index);
      setPropertyValue(id, kShowOverlay, true);

      // Slight delay before setting isOpen so the fade-in starts from opacity: 0
      setTimeout(() => setPropertyValue(id, kIsOpen, true), 10);
    },
    [setPropertyValue],
  );

  const closeLightbox = useCallback(() => {
    setPropertyValue(id, kIsOpen, false);
  }, [setPropertyValue]);

  // Remove the overlay from the DOM after fade-out completes
  useEffect(() => {
    if (!isOpen && showOverlay) {
      const timer = setTimeout(() => {
        setPropertyValue(id, kShowOverlay, false);
      }, 300); // match your transition duration
      return () => clearTimeout(timer);
    }
  }, [isOpen, showOverlay, setPropertyValue]);

  const showNext = useCallback(() => {
    setPropertyValue(id, kCurrentIndex, currentIndex + 1);
  }, [slides, setPropertyValue]);

  const showPrev = useCallback(() => {
    setPropertyValue(
      id,
      kCurrentIndex,
      (currentIndex - 1 + slides.length) % slides.length,
    );
  }, [slides, setPropertyValue]);

  // Keyboard Navigation
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyUp = (e: KeyboardEvent) => {
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
  }, [isOpen, showNext, showPrev]);

  return (
    <div className={clsx("lightbox-carousel-container")}>
      <div className={clsx(styles.carouselThumbs)}>
        {slides.map((slide, index) => {
          return (
            <div
              key={index}
              className={clsx(styles.carouselThumb)}
              onClick={() => openLightbox(index)}
            >
              <div>{slide.label}</div>
              <div>
                <i
                  className={clsx(
                    ApplicationIcons.play,
                    styles.carouselPlayIcon,
                  )}
                />
              </div>
            </div>
          );
        })}
      </div>
      {showOverlay && (
        <div
          className={clsx(styles.lightboxOverlay, isOpen ? "open" : "closed")}
        >
          <div className={clsx(styles.lightboxButtonCloseWrapper)}>
            <button
              className={styles.lightboxButtonClose}
              onClick={closeLightbox}
            >
              <i className={ApplicationIcons.close}></i>
            </button>
          </div>
          {slides.length > 1 ? (
            <button
              className={clsx(styles.lightboxPreviewButton, "prev")}
              onClick={showPrev}
            >
              <i className={ApplicationIcons.previous}></i>
            </button>
          ) : (
            ""
          )}
          {slides.length > 1 ? (
            <button
              className={clsx(styles.lightboxPreviewButton, "next")}
              onClick={showNext}
            >
              <i className={ApplicationIcons.next} />
            </button>
          ) : (
            ""
          )}
          <div
            key={`carousel-slide-${currentIndex}`}
            className={clsx(styles.lightboxContent, isOpen ? "open" : "closed")}
          >
            {slides[currentIndex].render()}
          </div>
        </div>
      )}
    </div>
  );
};
