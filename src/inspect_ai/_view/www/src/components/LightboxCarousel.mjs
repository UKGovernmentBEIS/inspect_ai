import { html } from "htm/preact";
import { useState, useCallback, useEffect } from "preact/hooks";
import { ApplicationIcons } from "../appearance/Icons.mjs";

/**
 * @typedef {Object} Slide
 * @property {string} label - The label for the slide.
 * @property {() => import("preact").JSX.Element} render - A function that returns another function to render the slide as a JSX element.
 */

/**
 * LightboxCarousel component provides a carousel with lightbox functionality.
 * @param {Object} props - Component properties.
 * @property {Array<Slide>} props.slides - Array of slide render functions.
 * @returns {import("preact").JSX.Element} LightboxCarousel component.
 */
export const LightboxCarousel = ({ slides }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [showOverlay, setShowOverlay] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(0);

  const openLightbox = (index) => {
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
  }, [isOpen, showNext, showPrev]);

  // Common button style
  const buttonStyle = {
    position: "absolute",
    top: "50%",
    transform: "translateY(-50%)",
    background: "none",
    color: "#fff",
    border: "none",
    padding: "0.5em",
    fontSize: "3em",
    cursor: "pointer",
    zIndex: "9999",
  };

  const prevButtonStyle = {
    ...buttonStyle,
    left: "10px",
  };

  const nextButtonStyle = {
    ...buttonStyle,
    right: "10px",
  };

  // Overlay style (fixed to fill the screen, flex for centering)
  const overlayStyle = {
    position: "fixed",
    top: 0,
    left: 0,
    width: "100vw",
    height: "100vh",
    background: "rgba(0,0,0,0.8)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    opacity: isOpen ? "1" : "0",
    visibility: isOpen ? "visible" : "hidden",
    transition: "opacity 0.3s ease, visibility 0.3s ease",
    zIndex: 9998,
  };

  // Close button style
  const closeButtonWrapperStyle = {
    position: "absolute",
    top: "10px",
    right: "10px",
  };

  const closeButtonStyle = {
    border: "none",
    background: "none",
    color: "#fff",
    fontSize: "3em",
    fontWeight: "500",
    cursor: "pointer",
    paddingLeft: "1em",
    paddingBottom: "1em",
    zIndex: "10000",
  };

  // Lightbox content container style
  const contentStyle = {
    maxWidth: "90%",
    maxHeight: "90%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    position: "relative",
    // fade in/out
    opacity: isOpen ? "1" : "0",
    visibility: isOpen ? "visible" : "hidden",
    transition: "opacity 0.3s ease, visibility 0.3s ease",
    zIndex: 9999,
  };

  return html`
    <div className="lightbox-carousel-container">
      <!-- Thumbnails -->
      <div
        className="carousel-thumbs"
        style=${{
          display: "grid",
          gridTemplateColumns: "auto auto auto auto",
        }}
      >
        ${slides.map((slide, index) => {
          return html`
            <div
              key=${index}
              className="carousel-thumb"
              onClick=${() => openLightbox(index)}
              style=${{
                background: "black",
                color: "white",
                padding: "4em 0",
                border: "0",
                margin: "5px",
                cursor: "pointer",
                textAlign: "center",
              }}
            >
              <div>${slide.label}</div>
              <div>
                <i
                  class=${ApplicationIcons.play}
                  style=${{ fontSize: "4em" }}
                ></i>
              </div>
            </div>
          `;
        })}
      </div>

      <!-- Lightbox Overlay -->
      ${showOverlay &&
      html`
        <div className="lightbox-overlay" style=${overlayStyle}>
          <div style=${closeButtonWrapperStyle}>
            <button style=${closeButtonStyle} onClick=${closeLightbox}>
              <i class=${ApplicationIcons.close}></i>
            </button>
          </div>

          ${slides.length > 1
            ? html` <button style=${prevButtonStyle} onClick=${showPrev}>
                <i class=${ApplicationIcons.previous}></i>
              </button>`
            : ""}
          ${slides.length > 1
            ? html` <button style=${nextButtonStyle} onClick=${showNext}>
                <i class=${ApplicationIcons.next}></i>
              </button>`
            : ""}

          <div
            key=${`carousel-slide-${currentIndex}`}
            className="lightbox-content"
            style=${contentStyle}
          >
            ${slides[currentIndex].render()}
          </div>
        </div>
      `}
    </div>
  `;
};
