import clsx from "clsx";
import { FC, MouseEvent, ReactNode, useCallback, useEffect } from "react";
import { ApplicationIcons } from "../app/appearance/icons";
import { useProperty } from "../state/hooks";
import styles from "./LightboxCarousel.module.css";

interface Slide {
  label: string;
  render: () => ReactNode;
}

interface LightboxCarouselProps {
  id: string;
  slides: Slide[];
}

/**
 * LightboxCarousel component provides a carousel with lightbox functionality.
 */
export const LightboxCarousel: FC<LightboxCarouselProps> = ({ id, slides }) => {
  const [isOpen, setIsOpen] = useProperty(id, "isOpen", {
    defaultValue: false,
  });

  const [currentIndex, setCurrentIndex] = useProperty(id, "currentIndex", {
    defaultValue: 0,
  });

  const [showOverlay, setShowOverlay] = useProperty(id, "showOverlay", {
    defaultValue: false,
  });

  const openLightbox = useCallback(
    (index: number) => {
      setCurrentIndex(index);
      setShowOverlay(true);

      // Slight delay before setting isOpen so the fade-in starts from opacity: 0
      setTimeout(() => setIsOpen(true), 10);
    },
    [setIsOpen],
  );

  const closeLightbox = useCallback(() => {
    setIsOpen(false);
  }, [setIsOpen]);

  // Remove the overlay from the DOM after fade-out completes
  useEffect(() => {
    if (!isOpen && showOverlay) {
      const timer = setTimeout(() => {
        setShowOverlay(false);
      }, 300); // match your transition duration
      return () => clearTimeout(timer);
    }
  }, [isOpen, showOverlay, setShowOverlay]);

  const showNext = useCallback(() => {
    setCurrentIndex(currentIndex + 1);
  }, [slides, setCurrentIndex]);

  const showPrev = useCallback(() => {
    setCurrentIndex((currentIndex - 1 + slides.length) % slides.length);
  }, [slides, setCurrentIndex]);

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

  const handleThumbClick = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      const index = Number((e.currentTarget as HTMLDivElement).dataset.index);
      openLightbox(index);
    },
    [openLightbox],
  );
  return (
    <div className={clsx("lightbox-carousel-container")}>
      <div className={clsx(styles.carouselThumbs)}>
        {slides.map((slide, index) => {
          return (
            <div
              key={index}
              data-index={index}
              className={clsx(styles.carouselThumb)}
              onClick={handleThumbClick}
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
