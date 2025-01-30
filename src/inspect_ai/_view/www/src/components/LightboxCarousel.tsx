import clsx from "clsx";
import { useCallback, useEffect, useState } from "react";
import { ApplicationIcons } from "../appearance/icons";
import "./LightboxCarousel.css";

interface Slide {
  label: string;
  render: () => React.ReactNode;
}

interface LightboxCarouselProps {
  slides: Slide[];
}

/**
 * LightboxCarousel component provides a carousel with lightbox functionality.
 */
export const LightboxCarousel: React.FC<LightboxCarouselProps> = ({
  slides,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [showOverlay, setShowOverlay] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(0);

  const openLightbox = (index: number) => {
    setCurrentIndex(index);
    setShowOverlay(true);

    // Slight delay before setting isOpen so the fade-in starts from opacity: 0
    setTimeout(() => setIsOpen(true), 10);
  };

  const closeLightbox = () => {
    setIsOpen(false);
  };

  // Remove the overlay from the DOM after fade-out completes
  useEffect(() => {
    if (!isOpen && showOverlay) {
      const timer = setTimeout(() => {
        setShowOverlay(false);
      }, 300); // match your transition duration
      return () => clearTimeout(timer);
    }
  }, [isOpen, showOverlay]);

  const showNext = useCallback(() => {
    setCurrentIndex((prev) => {
      return (prev + 1) % slides.length;
    });
  }, [slides]);

  const showPrev = useCallback(() => {
    setCurrentIndex((prev) => (prev - 1 + slides.length) % slides.length);
  }, [slides]);

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
    <div className="lightbox-carousel-container">
      <div className="carousel-thumbs">
        {slides.map((slide, index) => {
          return (
            <div
              key={index}
              className="carousel-thumb"
              onClick={() => openLightbox(index)}
            >
              <div>{slide.label}</div>
              <div>
                <i
                  className={clsx(ApplicationIcons.play, "carousel-play-icon")}
                />
              </div>
            </div>
          );
        })}
      </div>
      {showOverlay && (
        <div className={clsx("lightbox-overlay", isOpen ? "open" : "closed")}>
          <div className={"lightbox-button-close-wrapper"}>
            <button className={"lightbox-button-close"} onClick={closeLightbox}>
              <i className={ApplicationIcons.close}></i>
            </button>
          </div>
          {slides.length > 1 ? (
            <button
              className={"lightbox-preview-button prev"}
              onClick={showPrev}
            >
              <i className={ApplicationIcons.previous}></i>
            </button>
          ) : (
            ""
          )}
          {slides.length > 1 ? (
            <button
              className={"lightbox-preview-button next"}
              onClick={showNext}
            >
              <i className={ApplicationIcons.next} />
            </button>
          ) : (
            ""
          )}
          <div
            key={`carousel-slide-${currentIndex}`}
            className={clsx("lightbox-content", isOpen ? "open" : "closed")}
          >
            {slides[currentIndex].render()}
          </div>
        </div>
      )}
    </div>
  );
};
