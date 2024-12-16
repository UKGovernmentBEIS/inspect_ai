// @ts-check
import { html } from "htm/preact";
import { useEffect, useRef } from "preact/hooks";

// Import the asciinema player library
import * as AsciinemaPlayer from "asciinema-player";

/**
 * Renders the ChatView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string} props.id - The ID for the chat view.
 * @param {string} [props.height] - The height for the player container
 * @param {string} [props.width] - The width for the player container
 * @param {string} [props.fit] - how to fit the player
 * @param {Object} [props.style] - Inline styles for the chat view.
 * @param {number} [props.speed] - The speed to play (1 = 1x, 1.5 = 1.5x...)
 * @param {boolean} [props.autoPlay] - Whether to autoplay
 * @param {boolean} [props.loop] - Whether to loop
 * @param {string} [props.theme] - The terminal theme (e.g. "solarized-dark")
 * @param {number} [props.idleTimeLimit] - The amount to compress idle time to
 * @returns {import("preact").JSX.Element} The component.
 */
export const AsciiCinemaPlayer = ({
  id,
  height,
  width,
  fit,
  speed,
  autoPlay,
  loop,
  theme,
  idleTimeLimit = 2,
  style,
}) => {
  const playerContainerRef = useRef();

  useEffect(() => {
    AsciinemaPlayer.create(
      "data:text/plain;base64,eyJ2ZXJzaW9uIjogMiwgIndpZHRoIjogODAsICJoZWlnaHQiOiAyNH0KWzAuMSwgIm8iLCAiaGVsbCJdClswLjUsICJvIiwgIm8gIl0KWzIuNSwgIm8iLCAid29ybGQhXG5cciJdCg==",
      playerContainerRef.current,
      {
        autoPlay,
        loop,
        theme,
        speed,
        idleTimeLimit,
        fit,
      },
    );
  }, []);

  return html`
    <div
      id="asciinema-player-${id}"
      ref=${playerContainerRef}
      style=${{ width, height, ...style }}
    ></div>
  `;
};
