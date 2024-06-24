/**
 * Bundled by jsDelivr using Rollup v2.79.1 and Terser v5.19.2.
 * Original file: /npm/ansi-output@0.0.9/dist/ansi-output.js
 *
 * Do NOT use SRI with dynamically generated files! More information: https://www.jsdelivr.com/using-sri-with-dynamic-files
 */
var e,
  t,
  r = { exports: {} };
(e = r),
  (t = (function (e, t) {
    Object.defineProperty(t, "__esModule", { value: !0 }),
      (t.ANSIOutput = t.ANSIColor = t.ANSIFont = t.ANSIStyle = void 0);
    let r = 0;
    const n = () => ("" + ++r).padStart(16, "0");
    var o, i, s, a, u, l, g;
    (function (e) {
      (e.Bold = "ansiBold"),
        (e.Dim = "ansiDim"),
        (e.Italic = "ansiItalic"),
        (e.Underlined = "ansiUnderlined"),
        (e.SlowBlink = "ansiSlowBlink"),
        (e.RapidBlink = "ansiRapidBlink"),
        (e.Hidden = "ansiHidden"),
        (e.CrossedOut = "ansiCrossedOut"),
        (e.Fraktur = "ansiFraktur"),
        (e.DoubleUnderlined = "ansiDoubleUnderlined"),
        (e.Framed = "ansiFramed"),
        (e.Encircled = "ansiEncircled"),
        (e.Overlined = "ansiOverlined"),
        (e.Superscript = "ansiSuperscript"),
        (e.Subscript = "ansiSubscript");
    })(o || (t.ANSIStyle = o = {})),
      (function (e) {
        (e.AlternativeFont1 = "ansiAlternativeFont1"),
          (e.AlternativeFont2 = "ansiAlternativeFont2"),
          (e.AlternativeFont3 = "ansiAlternativeFont3"),
          (e.AlternativeFont4 = "ansiAlternativeFont4"),
          (e.AlternativeFont5 = "ansiAlternativeFont5"),
          (e.AlternativeFont6 = "ansiAlternativeFont6"),
          (e.AlternativeFont7 = "ansiAlternativeFont7"),
          (e.AlternativeFont8 = "ansiAlternativeFont8"),
          (e.AlternativeFont9 = "ansiAlternativeFont9");
      })(i || (t.ANSIFont = i = {})),
      (function (e) {
        (e.Black = "ansiBlack"),
          (e.Red = "ansiRed"),
          (e.Green = "ansiGreen"),
          (e.Yellow = "ansiYellow"),
          (e.Blue = "ansiBlue"),
          (e.Magenta = "ansiMagenta"),
          (e.Cyan = "ansiCyan"),
          (e.White = "ansiWhite"),
          (e.BrightBlack = "ansiBrightBlack"),
          (e.BrightRed = "ansiBrightRed"),
          (e.BrightGreen = "ansiBrightGreen"),
          (e.BrightYellow = "ansiBrightYellow"),
          (e.BrightBlue = "ansiBrightBlue"),
          (e.BrightMagenta = "ansiBrightMagenta"),
          (e.BrightCyan = "ansiBrightCyan"),
          (e.BrightWhite = "ansiBrightWhite");
      })(s || (t.ANSIColor = s = {}));
    class h {
      _parserState = g.BufferingOutput;
      _controlSequence = "";
      _sgrState = void 0;
      _outputLines = [];
      _outputLine = 0;
      _outputColumn = 0;
      _buffer = "";
      _pendingNewline = !1;
      get outputLines() {
        return this.flushBuffer(), this._outputLines;
      }
      static processOutput(e) {
        const t = new h();
        return t.processOutput(e), t.outputLines;
      }
      processOutput(e) {
        for (let t = 0; t < e.length; t++) {
          this._pendingNewline &&
            (this.flushBuffer(),
            this._outputLine++,
            (this._outputColumn = 0),
            (this._pendingNewline = !1));
          const r = e.charAt(t);
          this._parserState === g.BufferingOutput
            ? "" === r
              ? (this.flushBuffer(),
                (this._parserState = g.ControlSequenceStarted))
              : "" === r
                ? (this.flushBuffer(),
                  (this._parserState = g.ParsingControlSequence))
                : this.processCharacter(r)
            : this._parserState === g.ControlSequenceStarted
              ? "[" === r
                ? (this._parserState = g.ParsingControlSequence)
                : ((this._parserState = g.BufferingOutput),
                  this.processCharacter(r))
              : this._parserState === g.ParsingControlSequence &&
                ((this._controlSequence += r),
                r.match(/^[A-Za-z]$/) && this.processControlSequence());
        }
        this.flushBuffer();
      }
      flushBuffer() {
        for (let e = this._outputLines.length; e < this._outputLine + 1; e++)
          this._outputLines.push(new d());
        this._buffer &&
          (this._outputLines[this._outputLine].insert(
            this._buffer,
            this._outputColumn,
            this._sgrState,
          ),
          (this._outputColumn += this._buffer.length),
          (this._buffer = ""));
      }
      processCharacter(e) {
        switch (e) {
          case "\n":
            this._pendingNewline = !0;
            break;
          case "\r":
            this.flushBuffer(), (this._outputColumn = 0);
            break;
          default:
            this._buffer += e;
        }
      }
      processControlSequence() {
        switch (
          this._controlSequence.charAt(this._controlSequence.length - 1)
        ) {
          case "A":
            this.processCUU();
            break;
          case "B":
            this.processCUD();
            break;
          case "C":
            this.processCUF();
            break;
          case "D":
            this.processCUB();
            break;
          case "H":
            this.processCUP();
            break;
          case "J":
            this.processED();
            break;
          case "K":
            this.processEL();
            break;
          case "m":
            this.processSGR();
        }
        (this._controlSequence = ""), (this._parserState = g.BufferingOutput);
      }
      processCUU() {
        const e = this._controlSequence.match(/^([0-9]*)A$/);
        e && (this._outputLine = Math.max(this._outputLine - k(e[1], 1, 1), 0));
      }
      processCUD() {
        const e = this._controlSequence.match(/^([0-9]*)B$/);
        e && (this._outputLine = this._outputLine + k(e[1], 1, 1));
      }
      processCUF() {
        const e = this._controlSequence.match(/^([0-9]*)C$/);
        e && (this._outputColumn = this._outputColumn + k(e[1], 1, 1));
      }
      processCUB() {
        const e = this._controlSequence.match(/^([0-9]*)D$/);
        e &&
          (this._outputColumn = Math.max(
            this._outputColumn - k(e[1], 1, 1),
            0,
          ));
      }
      processCUP() {
        const e = this._controlSequence.match(/^([0-9]*)(?:;?([0-9]*))H$/);
        e &&
          ((this._outputLine = k(e[1], 1, 1) - 1),
          (this._outputColumn = k(e[2], 1, 1) - 1));
      }
      processED() {
        const e = this._controlSequence.match(/^([0-9]*)J$/);
        if (e)
          switch (p(e[1], 0)) {
            case 0:
              this._outputLines[this._outputLine].clearToEndOfLine(
                this._outputColumn,
              );
              for (
                let e = this._outputLine + 1;
                e < this._outputLines.length;
                e++
              )
                this._outputLines[e].clearEntireLine();
              break;
            case 1:
              this._outputLines[this._outputLine].clearToBeginningOfLine(
                this._outputColumn,
              );
              for (let e = 0; e < this._outputLine; e++)
                this._outputLines[e].clearEntireLine();
              break;
            case 2:
              for (let e = 0; e < this._outputLines.length; e++)
                this._outputLines[e].clearEntireLine();
          }
      }
      processEL() {
        const e = this._controlSequence.match(/^([0-9]*)K$/);
        if (e) {
          const t = this._outputLines[this._outputLine];
          switch (p(e[1], 0)) {
            case 0:
              t.clearToEndOfLine(this._outputColumn);
              break;
            case 1:
              t.clearToBeginningOfLine(this._outputColumn);
              break;
            case 2:
              t.clearEntireLine();
          }
        }
      }
      processSGR() {
        const e = this._sgrState ? this._sgrState.copy() : new c(),
          t = this._controlSequence
            .slice(0, -1)
            .split(";")
            .map((e) => ("" === e ? a.Reset : parseInt(e, 10)));
        for (let r = 0; r < t.length; r++) {
          const n = () => {
            if (r + 1 !== t.length)
              switch (t[++r]) {
                case u.Color256: {
                  if (r + 1 === t.length) return;
                  const e = t[++r];
                  switch (e) {
                    case l.Black:
                      return s.Black;
                    case l.Red:
                      return s.Red;
                    case l.Green:
                      return s.Green;
                    case l.Yellow:
                      return s.Yellow;
                    case l.Blue:
                      return s.Blue;
                    case l.Magenta:
                      return s.Magenta;
                    case l.Cyan:
                      return s.Cyan;
                    case l.White:
                      return s.White;
                    case l.BrightBlack:
                      return s.BrightBlack;
                    case l.BrightRed:
                      return s.BrightRed;
                    case l.BrightGreen:
                      return s.BrightGreen;
                    case l.BrightYellow:
                      return s.BrightYellow;
                    case l.BrightBlue:
                      return s.BrightBlue;
                    case l.BrightMagenta:
                      return s.BrightMagenta;
                    case l.BrightCyan:
                      return s.BrightCyan;
                    case l.BrightWhite:
                      return s.BrightWhite;
                    default:
                      if (e % 1 != 0) return;
                      if (e >= 16 && e <= 231) {
                        let t = e - 16,
                          r = t % 6;
                        t = (t - r) / 6;
                        let n = t % 6;
                        t = (t - n) / 6;
                        let o = t;
                        return (
                          (r = Math.round((255 * r) / 5)),
                          (n = Math.round((255 * n) / 5)),
                          (o = Math.round((255 * o) / 5)),
                          "#" + _(o) + _(n) + _(r)
                        );
                      }
                      if (e >= 232 && e <= 255) {
                        const t = Math.round(((e - 232) / 23) * 255),
                          r = _(t);
                        return "#" + r + r + r;
                      }
                      return;
                  }
                }
                case u.ColorRGB: {
                  const e = [0, 0, 0];
                  for (let n = 0; n < 3 && r + 1 < t.length; n++) e[n] = t[++r];
                  return "#" + _(e[0]) + _(e[1]) + _(e[2]);
                }
              }
          };
          switch (t[r]) {
            case a.Reset:
              e.reset();
              break;
            case a.Bold:
              e.setStyle(o.Bold);
              break;
            case a.Dim:
              e.setStyle(o.Dim);
              break;
            case a.Italic:
              e.setStyle(o.Italic);
              break;
            case a.Underlined:
              e.setStyle(o.Underlined, o.DoubleUnderlined);
              break;
            case a.SlowBlink:
              e.setStyle(o.SlowBlink, o.RapidBlink);
              break;
            case a.RapidBlink:
              e.setStyle(o.RapidBlink, o.SlowBlink);
              break;
            case a.Reversed:
              e.setReversed(!0);
              break;
            case a.Hidden:
              e.setStyle(o.Hidden);
              break;
            case a.CrossedOut:
              e.setStyle(o.CrossedOut);
              break;
            case a.PrimaryFont:
              e.setFont();
              break;
            case a.AlternativeFont1:
              e.setFont(i.AlternativeFont1);
              break;
            case a.AlternativeFont2:
              e.setFont(i.AlternativeFont2);
              break;
            case a.AlternativeFont3:
              e.setFont(i.AlternativeFont3);
              break;
            case a.AlternativeFont4:
              e.setFont(i.AlternativeFont4);
              break;
            case a.AlternativeFont5:
              e.setFont(i.AlternativeFont5);
              break;
            case a.AlternativeFont6:
              e.setFont(i.AlternativeFont6);
              break;
            case a.AlternativeFont7:
              e.setFont(i.AlternativeFont7);
              break;
            case a.AlternativeFont8:
              e.setFont(i.AlternativeFont8);
              break;
            case a.AlternativeFont9:
              e.setFont(i.AlternativeFont9);
              break;
            case a.Fraktur:
              e.setStyle(o.Fraktur);
              break;
            case a.DoubleUnderlined:
              e.setStyle(o.DoubleUnderlined, o.Underlined);
              break;
            case a.NormalIntensity:
              e.deleteStyles(o.Bold, o.Dim);
              break;
            case a.NotItalicNotFraktur:
              e.deleteStyles(o.Italic, o.Fraktur);
              break;
            case a.NotUnderlined:
              e.deleteStyles(o.Underlined, o.DoubleUnderlined);
              break;
            case a.NotBlinking:
              e.deleteStyles(o.SlowBlink, o.RapidBlink);
              break;
            case a.ProportionalSpacing:
              break;
            case a.NotReversed:
              e.setReversed(!1);
              break;
            case a.Reveal:
              e.deleteStyles(o.Hidden);
              break;
            case a.NotCrossedOut:
              e.deleteStyles(o.CrossedOut);
              break;
            case a.ForegroundBlack:
              e.setForegroundColor(s.Black);
              break;
            case a.ForegroundRed:
              e.setForegroundColor(s.Red);
              break;
            case a.ForegroundGreen:
              e.setForegroundColor(s.Green);
              break;
            case a.ForegroundYellow:
              e.setForegroundColor(s.Yellow);
              break;
            case a.ForegroundBlue:
              e.setForegroundColor(s.Blue);
              break;
            case a.ForegroundMagenta:
              e.setForegroundColor(s.Magenta);
              break;
            case a.ForegroundCyan:
              e.setForegroundColor(s.Cyan);
              break;
            case a.ForegroundWhite:
              e.setForegroundColor(s.White);
              break;
            case a.SetForeground: {
              const t = n();
              t && e.setForegroundColor(t);
              break;
            }
            case a.DefaultForeground:
              e.setForegroundColor();
              break;
            case a.BackgroundBlack:
              e.setBackgroundColor(s.Black);
              break;
            case a.BackgroundRed:
              e.setBackgroundColor(s.Red);
              break;
            case a.BackgroundGreen:
              e.setBackgroundColor(s.Green);
              break;
            case a.BackgroundYellow:
              e.setBackgroundColor(s.Yellow);
              break;
            case a.BackgroundBlue:
              e.setBackgroundColor(s.Blue);
              break;
            case a.BackgroundMagenta:
              e.setBackgroundColor(s.Magenta);
              break;
            case a.BackgroundCyan:
              e.setBackgroundColor(s.Cyan);
              break;
            case a.BackgroundWhite:
              e.setBackgroundColor(s.White);
              break;
            case a.SetBackground: {
              const t = n();
              t && e.setBackgroundColor(t);
              break;
            }
            case a.DefaultBackground:
              e.setBackgroundColor();
              break;
            case a.ForegroundBrightBlack:
              e.setForegroundColor(s.BrightBlack);
              break;
            case a.ForegroundBrightRed:
              e.setForegroundColor(s.BrightRed);
              break;
            case a.ForegroundBrightGreen:
              e.setForegroundColor(s.BrightGreen);
              break;
            case a.ForegroundBrightYellow:
              e.setForegroundColor(s.BrightYellow);
              break;
            case a.ForegroundBrightBlue:
              e.setForegroundColor(s.BrightBlue);
              break;
            case a.ForegroundBrightMagenta:
              e.setForegroundColor(s.BrightMagenta);
              break;
            case a.ForegroundBrightCyan:
              e.setForegroundColor(s.BrightCyan);
              break;
            case a.ForegroundBrightWhite:
              e.setForegroundColor(s.BrightWhite);
              break;
            case a.BackgroundBrightBlack:
              e.setBackgroundColor(s.BrightBlack);
              break;
            case a.BackgroundBrightRed:
              e.setBackgroundColor(s.BrightRed);
              break;
            case a.BackgroundBrightGreen:
              e.setBackgroundColor(s.BrightGreen);
              break;
            case a.BackgroundBrightYellow:
              e.setBackgroundColor(s.BrightYellow);
              break;
            case a.BackgroundBrightBlue:
              e.setBackgroundColor(s.BrightBlue);
              break;
            case a.BackgroundBrightMagenta:
              e.setBackgroundColor(s.BrightMagenta);
              break;
            case a.BackgroundBrightCyan:
              e.setBackgroundColor(s.BrightCyan);
              break;
            case a.BackgroundBrightWhite:
              e.setBackgroundColor(s.BrightWhite);
          }
        }
        c.equivalent(e, this._sgrState) || (this._sgrState = e);
      }
    }
    (t.ANSIOutput = h),
      (function (e) {
        (e[(e.Reset = 0)] = "Reset"),
          (e[(e.Bold = 1)] = "Bold"),
          (e[(e.Dim = 2)] = "Dim"),
          (e[(e.Italic = 3)] = "Italic"),
          (e[(e.Underlined = 4)] = "Underlined"),
          (e[(e.SlowBlink = 5)] = "SlowBlink"),
          (e[(e.RapidBlink = 6)] = "RapidBlink"),
          (e[(e.Reversed = 7)] = "Reversed"),
          (e[(e.Hidden = 8)] = "Hidden"),
          (e[(e.CrossedOut = 9)] = "CrossedOut"),
          (e[(e.PrimaryFont = 10)] = "PrimaryFont"),
          (e[(e.AlternativeFont1 = 11)] = "AlternativeFont1"),
          (e[(e.AlternativeFont2 = 12)] = "AlternativeFont2"),
          (e[(e.AlternativeFont3 = 13)] = "AlternativeFont3"),
          (e[(e.AlternativeFont4 = 14)] = "AlternativeFont4"),
          (e[(e.AlternativeFont5 = 15)] = "AlternativeFont5"),
          (e[(e.AlternativeFont6 = 16)] = "AlternativeFont6"),
          (e[(e.AlternativeFont7 = 17)] = "AlternativeFont7"),
          (e[(e.AlternativeFont8 = 18)] = "AlternativeFont8"),
          (e[(e.AlternativeFont9 = 19)] = "AlternativeFont9"),
          (e[(e.Fraktur = 20)] = "Fraktur"),
          (e[(e.DoubleUnderlined = 21)] = "DoubleUnderlined"),
          (e[(e.NormalIntensity = 22)] = "NormalIntensity"),
          (e[(e.NotItalicNotFraktur = 23)] = "NotItalicNotFraktur"),
          (e[(e.NotUnderlined = 24)] = "NotUnderlined"),
          (e[(e.NotBlinking = 25)] = "NotBlinking"),
          (e[(e.ProportionalSpacing = 26)] = "ProportionalSpacing"),
          (e[(e.NotReversed = 27)] = "NotReversed"),
          (e[(e.Reveal = 28)] = "Reveal"),
          (e[(e.NotCrossedOut = 29)] = "NotCrossedOut"),
          (e[(e.ForegroundBlack = 30)] = "ForegroundBlack"),
          (e[(e.ForegroundRed = 31)] = "ForegroundRed"),
          (e[(e.ForegroundGreen = 32)] = "ForegroundGreen"),
          (e[(e.ForegroundYellow = 33)] = "ForegroundYellow"),
          (e[(e.ForegroundBlue = 34)] = "ForegroundBlue"),
          (e[(e.ForegroundMagenta = 35)] = "ForegroundMagenta"),
          (e[(e.ForegroundCyan = 36)] = "ForegroundCyan"),
          (e[(e.ForegroundWhite = 37)] = "ForegroundWhite"),
          (e[(e.SetForeground = 38)] = "SetForeground"),
          (e[(e.DefaultForeground = 39)] = "DefaultForeground"),
          (e[(e.BackgroundBlack = 40)] = "BackgroundBlack"),
          (e[(e.BackgroundRed = 41)] = "BackgroundRed"),
          (e[(e.BackgroundGreen = 42)] = "BackgroundGreen"),
          (e[(e.BackgroundYellow = 43)] = "BackgroundYellow"),
          (e[(e.BackgroundBlue = 44)] = "BackgroundBlue"),
          (e[(e.BackgroundMagenta = 45)] = "BackgroundMagenta"),
          (e[(e.BackgroundCyan = 46)] = "BackgroundCyan"),
          (e[(e.BackgroundWhite = 47)] = "BackgroundWhite"),
          (e[(e.SetBackground = 48)] = "SetBackground"),
          (e[(e.DefaultBackground = 49)] = "DefaultBackground"),
          (e[(e.DisableProportionalSpacing = 50)] =
            "DisableProportionalSpacing"),
          (e[(e.Framed = 51)] = "Framed"),
          (e[(e.Encircled = 52)] = "Encircled"),
          (e[(e.Overlined = 53)] = "Overlined"),
          (e[(e.NotFramedNotEncircled = 54)] = "NotFramedNotEncircled"),
          (e[(e.NotOverlined = 55)] = "NotOverlined"),
          (e[(e.SetUnderline = 58)] = "SetUnderline"),
          (e[(e.DefaultUnderline = 59)] = "DefaultUnderline"),
          (e[(e.IdeogramUnderlineOrRightSideLine = 60)] =
            "IdeogramUnderlineOrRightSideLine"),
          (e[(e.IdeogramDoubleUnderlineOrDoubleRightSideLine = 61)] =
            "IdeogramDoubleUnderlineOrDoubleRightSideLine"),
          (e[(e.IdeogramOverlineOrLeftSideLine = 62)] =
            "IdeogramOverlineOrLeftSideLine"),
          (e[(e.IdeogramDoubleOverlineOrDoubleLeftSideLine = 63)] =
            "IdeogramDoubleOverlineOrDoubleLeftSideLine"),
          (e[(e.IdeogramStressMarking = 64)] = "IdeogramStressMarking"),
          (e[(e.NoIdeogramAttributes = 65)] = "NoIdeogramAttributes"),
          (e[(e.Superscript = 73)] = "Superscript"),
          (e[(e.Subscript = 74)] = "Subscript"),
          (e[(e.NotSuperscriptNotSubscript = 75)] =
            "NotSuperscriptNotSubscript"),
          (e[(e.ForegroundBrightBlack = 90)] = "ForegroundBrightBlack"),
          (e[(e.ForegroundBrightRed = 91)] = "ForegroundBrightRed"),
          (e[(e.ForegroundBrightGreen = 92)] = "ForegroundBrightGreen"),
          (e[(e.ForegroundBrightYellow = 93)] = "ForegroundBrightYellow"),
          (e[(e.ForegroundBrightBlue = 94)] = "ForegroundBrightBlue"),
          (e[(e.ForegroundBrightMagenta = 95)] = "ForegroundBrightMagenta"),
          (e[(e.ForegroundBrightCyan = 96)] = "ForegroundBrightCyan"),
          (e[(e.ForegroundBrightWhite = 97)] = "ForegroundBrightWhite"),
          (e[(e.BackgroundBrightBlack = 100)] = "BackgroundBrightBlack"),
          (e[(e.BackgroundBrightRed = 101)] = "BackgroundBrightRed"),
          (e[(e.BackgroundBrightGreen = 102)] = "BackgroundBrightGreen"),
          (e[(e.BackgroundBrightYellow = 103)] = "BackgroundBrightYellow"),
          (e[(e.BackgroundBrightBlue = 104)] = "BackgroundBrightBlue"),
          (e[(e.BackgroundBrightMagenta = 105)] = "BackgroundBrightMagenta"),
          (e[(e.BackgroundBrightCyan = 106)] = "BackgroundBrightCyan"),
          (e[(e.BackgroundBrightWhite = 107)] = "BackgroundBrightWhite");
      })(a || (a = {})),
      (function (e) {
        (e[(e.Color256 = 5)] = "Color256"), (e[(e.ColorRGB = 2)] = "ColorRGB");
      })(u || (u = {})),
      (function (e) {
        (e[(e.Black = 0)] = "Black"),
          (e[(e.Red = 1)] = "Red"),
          (e[(e.Green = 2)] = "Green"),
          (e[(e.Yellow = 3)] = "Yellow"),
          (e[(e.Blue = 4)] = "Blue"),
          (e[(e.Magenta = 5)] = "Magenta"),
          (e[(e.Cyan = 6)] = "Cyan"),
          (e[(e.White = 7)] = "White"),
          (e[(e.BrightBlack = 8)] = "BrightBlack"),
          (e[(e.BrightRed = 9)] = "BrightRed"),
          (e[(e.BrightGreen = 10)] = "BrightGreen"),
          (e[(e.BrightYellow = 11)] = "BrightYellow"),
          (e[(e.BrightBlue = 12)] = "BrightBlue"),
          (e[(e.BrightMagenta = 13)] = "BrightMagenta"),
          (e[(e.BrightCyan = 14)] = "BrightCyan"),
          (e[(e.BrightWhite = 15)] = "BrightWhite");
      })(l || (l = {})),
      (function (e) {
        (e[(e.BufferingOutput = 0)] = "BufferingOutput"),
          (e[(e.ControlSequenceStarted = 1)] = "ControlSequenceStarted"),
          (e[(e.ParsingControlSequence = 2)] = "ParsingControlSequence");
      })(g || (g = {}));
    class c {
      _styles;
      _foregroundColor;
      _backgroundColor;
      _underlinedColor;
      _reversed;
      _font;
      reset() {
        (this._styles = void 0),
          (this._foregroundColor = void 0),
          (this._backgroundColor = void 0),
          (this._underlinedColor = void 0),
          (this._reversed = void 0),
          (this._font = void 0);
      }
      copy() {
        const e = new c();
        if (this._styles && this._styles.size) {
          const t = new Set();
          this._styles.forEach((e) => t.add(e)), (e._styles = t);
        }
        return (
          (e._foregroundColor = this._foregroundColor),
          (e._backgroundColor = this._backgroundColor),
          (e._underlinedColor = this._underlinedColor),
          (e._reversed = this._reversed),
          (e._font = this._font),
          e
        );
      }
      setStyle(e, ...t) {
        if (this._styles) for (const e of t) this._styles.delete(e);
        else this._styles = new Set();
        this._styles.add(e);
      }
      deleteStyles(...e) {
        if (this._styles) {
          for (const t of e) this._styles.delete(t);
          this._styles.size || (this._styles = void 0);
        }
      }
      setForegroundColor(e) {
        this._reversed
          ? (this._backgroundColor = e)
          : (this._foregroundColor = e);
      }
      setBackgroundColor(e) {
        this._reversed
          ? (this._foregroundColor = e)
          : (this._backgroundColor = e);
      }
      setReversed(e) {
        e
          ? this._reversed ||
            ((this._reversed = !0), this.reverseForegroundAndBackgroundColors())
          : this._reversed &&
            ((this._reversed = void 0),
            this.reverseForegroundAndBackgroundColors());
      }
      setFont(e) {
        this._font = e;
      }
      static equivalent(e, t) {
        const r = (e, t) => (t instanceof Set ? (t.size ? [...t] : void 0) : t);
        return e === t || JSON.stringify(e, r) === JSON.stringify(t, r);
      }
      get styles() {
        return this._styles ? [...this._styles] : void 0;
      }
      get foregroundColor() {
        if (this._backgroundColor && !this._foregroundColor)
          switch (this._backgroundColor) {
            case s.Black:
            case s.BrightBlack:
            case s.Red:
            case s.BrightRed:
              return s.White;
            case s.Green:
            case s.BrightGreen:
            case s.Yellow:
            case s.BrightYellow:
            case s.Blue:
            case s.BrightBlue:
            case s.Magenta:
            case s.BrightMagenta:
            case s.Cyan:
            case s.BrightCyan:
            case s.White:
            case s.BrightWhite:
              return s.Black;
          }
        return this._foregroundColor;
      }
      get backgroundColor() {
        return this._backgroundColor;
      }
      get underlinedColor() {
        return this._underlinedColor;
      }
      get font() {
        return this._font;
      }
      reverseForegroundAndBackgroundColors() {
        const e = this._foregroundColor;
        (this._foregroundColor = this._backgroundColor),
          (this._backgroundColor = e);
      }
    }
    class d {
      _id = n();
      _outputRuns = [];
      _totalLength = 0;
      clearEntireLine() {
        this._totalLength &&
          (this._outputRuns = [new B(" ".repeat(this._totalLength))]);
      }
      clearToEndOfLine(e) {
        if ((e = Math.max(e, 0)) >= this._totalLength) return;
        if (0 === e) return void this.clearEntireLine();
        let t,
          r,
          n = 0;
        for (let o = 0; o < this._outputRuns.length; o++) {
          const i = this._outputRuns[o];
          if (e < n + i.text.length) {
            (t = i), (r = o);
            break;
          }
          n += i.text.length;
        }
        if (void 0 === t || void 0 === r) return;
        const o = e - n,
          i = " ".repeat(this._totalLength - e),
          s = [];
        if (o) {
          const e = t.text.slice(0, o);
          s.push(new B(e, t.sgrState)), s.push(new B(i));
        } else s.push(new B(i));
        this.outputRuns.splice(r, this._outputRuns.length - r, ...s);
      }
      clearToBeginningOfLine(e) {
        if (0 === (e = Math.max(e, 0))) return;
        if (e >= this._totalLength) return void this.clearEntireLine();
        let t,
          r,
          n = 0;
        for (let o = this._outputRuns.length - 1; o >= 0; o--) {
          const i = this._outputRuns[o];
          if (e >= n - i.text.length) {
            (t = i), (r = o);
            break;
          }
          n -= i.text.length;
        }
        if (void 0 === t || void 0 === r) return;
        const o = n - e,
          i = " ".repeat(e),
          s = [new B(i)];
        if (o) {
          const e = t.text.slice(-o);
          s.push(new B(e, t.sgrState));
        }
        this.outputRuns.splice(0, this._outputRuns.length - r, ...s);
      }
      insert(e, t, r) {
        if (!e.length) return;
        if (t === this._totalLength) {
          if (((this._totalLength += e.length), this._outputRuns.length)) {
            const t = this._outputRuns[this._outputRuns.length - 1];
            if (c.equivalent(t.sgrState, r)) return void t.appendText(e);
          }
          return void this._outputRuns.push(new B(e, r));
        }
        if (t > this._totalLength) {
          const n = " ".repeat(t - this._totalLength);
          if (
            ((this._totalLength += n.length + e.length),
            !r && this._outputRuns.length)
          ) {
            const t = this._outputRuns[this._outputRuns.length - 1];
            if (!t.sgrState) return t.appendText(n), void t.appendText(e);
          }
          r
            ? (this._outputRuns.push(new B(n)),
              this._outputRuns.push(new B(e, r)))
            : this._outputRuns.push(new B(n + e));
        }
        let n,
          o = 0;
        for (let e = 0; e < this._outputRuns.length; e++) {
          const r = this._outputRuns[e];
          if (t < o + r.text.length) {
            n = e;
            break;
          }
          o += r.text.length;
        }
        if (void 0 === n) return void this._outputRuns.push(new B(e, r));
        if (t + e.length >= this._totalLength) {
          const i = t - o,
            s = [];
          if (i) {
            const t = this._outputRuns[n],
              o = t.text.slice(0, i);
            c.equivalent(t.sgrState, r)
              ? s.push(new B(o + e, r))
              : (s.push(new B(o, t.sgrState)), s.push(new B(e, r)));
          } else s.push(new B(e, r));
          return (
            this.outputRuns.splice(n, 1, ...s),
            void (this._totalLength = o + i + e.length)
          );
        }
        let i,
          s = this._totalLength;
        for (let r = this._outputRuns.length - 1; r >= 0; r--) {
          const n = this._outputRuns[r];
          if (t + e.length > s - n.text.length) {
            i = r;
            break;
          }
          s -= n.text.length;
        }
        if (void 0 === i) return void this._outputRuns.push(new B(e, r));
        const a = [],
          u = t - o;
        if (u) {
          const e = this._outputRuns[n],
            t = e.text.slice(0, u);
          a.push(new B(t, e.sgrState));
        }
        a.push(new B(e, r));
        const l = s - (t + e.length);
        if (l) {
          const e = this._outputRuns[i],
            t = e.text.slice(-l);
          a.push(new B(t, e.sgrState));
        }
        this._outputRuns.splice(n, i - n + 1, ...a),
          this._outputRuns.length > 1 &&
            (this._outputRuns = B.optimizeOutputRuns(this._outputRuns)),
          (this._totalLength = this._outputRuns.reduce(
            (e, t) => e + t.text.length,
            0,
          ));
      }
      get id() {
        return this._id;
      }
      get outputRuns() {
        return this._outputRuns;
      }
    }
    class B {
      _id = n();
      _sgrState;
      _text;
      get sgrState() {
        return this._sgrState;
      }
      constructor(e, t) {
        (this._sgrState = t), (this._text = e);
      }
      static optimizeOutputRuns(e) {
        const t = [e[0]];
        for (let r = 1, n = 0; r < e.length; r++) {
          const o = e[r];
          c.equivalent(t[n].sgrState, o.sgrState)
            ? (t[n]._text += o.text)
            : (t[++n] = o);
        }
        return t;
      }
      appendText(e) {
        this._text += e;
      }
      get id() {
        return this._id;
      }
      get format() {
        return this._sgrState;
      }
      get text() {
        return this._text;
      }
    }
    const k = (e, t, r) => {
        const n = p(e, t);
        return Math.max(n, r);
      },
      p = (e, t) => {
        const r = parseInt(e);
        return Number.isNaN(r) ? t : r;
      },
      _ = (e) => {
        const t = Math.max(Math.min(255, e), 0).toString(16);
        return 2 === t.length ? t : "0" + t;
      };
  })(0, r.exports)),
  void 0 !== t && (e.exports = t);
var n = r.exports;
export { n as default };
//# sourceMappingURL=/sm/e2bb81b6893b38ca5911532123780d53bdf6e15fbe7b44eb87ce76582ffdd9ab.map
