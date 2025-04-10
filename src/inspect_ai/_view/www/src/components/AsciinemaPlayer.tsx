import * as AsciicinemaPlayerJS from "asciinema-player";
import "asciinema-player/dist/bundle/asciinema-player.css";
import { CSSProperties, FC, useEffect, useRef } from "react";

interface AsciinemaPlayerProps {
  id?: string;
  inputUrl: string;
  outputUrl: string;
  timingUrl: string;
  rows?: number;
  cols?: number;
  fit?: string;
  style?: CSSProperties;
  speed?: number;
  autoPlay?: boolean;
  loop?: boolean;
  theme?: string;
  idleTimeLimit?: number;
  className?: string;
}

export const AsciinemaPlayer: FC<AsciinemaPlayerProps> = ({
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
  const playerContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!playerContainerRef.current) return;

    const player = AsciicinemaPlayerJS.create(
      {
        url: [timingUrl, outputUrl, inputUrl],
        parser: "typescript",
      },
      playerContainerRef.current,
      {
        rows,
        cols,
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
  }, [
    timingUrl,
    outputUrl,
    inputUrl,
    rows,
    cols,
    autoPlay,
    loop,
    theme,
    speed,
    idleTimeLimit,
    fit,
  ]);

  return (
    <div
      id={`asciinema-player-${id || "default"}`}
      ref={playerContainerRef}
      style={{ ...style }}
    />
  );
};
