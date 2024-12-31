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
 * @param {string} props.inputUrl - The input url for the player
 * @param {string} props.outputUrl - The output url for the player
 * @param {string} props.timingUrl - The timing url for the player
 * @param {number} [props.rows] - The rows for the player's initial size
 * @param {number} [props.cols] - The cols for the player's initial size
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
  style,
}) => {
  const playerContainerRef = useRef();
  useEffect(() => {
    const player = AsciinemaPlayer.create(
      {
        url: [timingUrl, outputUrl, inputUrl],
        parser: "typescript",
      },
      playerContainerRef.current,
      {
        rows: rows,
        cols: cols,
        autoPlay,
        loop,
        theme,
        speed,
        idleTimeLimit,
        fit,
      },
    );
    player.play();
    return () => {
      player.dispose();
    };
  }, []);

  return html`
    <div
      id="asciinema-player-${id || "default"}"
      ref=${playerContainerRef}
      style=${{ ...style }}
    ></div>
  `;
};
