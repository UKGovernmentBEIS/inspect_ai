declare module "asciinema-player" {
  export const create: (
    src: string | Object,
    el: HTMLElement,
    opts: {
      cols?: number;
      rows?: number;
      autoPlay?: boolean;
      preload?: boolean;
      loop?: boolean;
      theme?: string;
      startAt?: number | string;
      speed?: number;
      idleTimeLimit?: number;
      poster?: string;
      fit?: string;
      controls?: boolean;
      markers?: Array<number> | Array<[number, string]>;
      pauseOnMarkers?: boolean;
      terminalFontSize?: string;
      terminalFontFamily?: string;
      terminalLineHeight?: string;
      logger?: Object;
    },
  ) => any;
}
