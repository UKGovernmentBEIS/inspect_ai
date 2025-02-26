import clsx from "clsx";
import { FC, ReactNode, useCallback, useEffect, useState } from "react";
import { ApplicationIcons } from "../appearance/icons";
import styles from "./LightboxCarousel.module.css";

interface Slide {
  label: string;
  render: () => ReactNode;
}

interface LightboxCarouselProps {
  slides: Slide[];
}

/**
 * LightboxCarousel component provides a carousel with lightbox functionality.
 */
export const LightboxCarousel: FC<LightboxCarouselProps> = ({ slides }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [showOverlay, setShowOverlay] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(0);

  const openLightbox = useCallback(
    (index: number) => {
      setCurrentIndex(index);
      setShowOverlay(true);

      // Slight delay before setting isOpen so the fade-in starts from opacity: 0
      setTimeout(() => setIsOpen(true), 10);
    },
    [setCurrentIndex, setShowOverlay],
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
    setCurrentIndex((prev) => {
      return (prev + 1) % slides.length;
    });
  }, [slides, setCurrentIndex]);

  const showPrev = useCallback(() => {
    setCurrentIndex((prev) => (prev - 1 + slides.length) % slides.length);
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
