import { i as __toESM, r as __require, t as __commonJSMin } from "./rolldown-runtime.js";
import { n as require_react, r as require_jsx_runtime, t as require_compiler_runtime } from "./compiler-runtime.js";
import { a as clsx, i as useComponentIcons, n as AnsiDisplay_module_default, t as ToolButton } from "./ToolButton.js";
//#region ../../node_modules/.pnpm/ansi-output@0.0.9/node_modules/ansi-output/dist/ansi-output.js
var require_ansi_output = /* @__PURE__ */ __commonJSMin(((exports, module) => {
	(function(factory) {
		if (typeof module === "object" && typeof module.exports === "object") {
			var v = factory(__require, exports);
			if (v !== void 0) module.exports = v;
		} else if (typeof define === "function" && define.amd) define(["require", "exports"], factory);
	})(function(require, exports$1) {
		"use strict";
		Object.defineProperty(exports$1, "__esModule", { value: true });
		exports$1.ANSIOutput = exports$1.ANSIColor = exports$1.ANSIFont = exports$1.ANSIStyle = void 0;
		/**
		* The counter used to generate identifiers.
		*/
		let counter = 0;
		/**
		* Generates an identifier.
		* @returns The identifier.
		*/
		const generateId = () => {
			return `${++counter}`.padStart(16, "0");
		};
		/**
		* ANSIStyle enumeration.
		*/
		var ANSIStyle;
		(function(ANSIStyle) {
			ANSIStyle["Bold"] = "ansiBold";
			ANSIStyle["Dim"] = "ansiDim";
			ANSIStyle["Italic"] = "ansiItalic";
			ANSIStyle["Underlined"] = "ansiUnderlined";
			ANSIStyle["SlowBlink"] = "ansiSlowBlink";
			ANSIStyle["RapidBlink"] = "ansiRapidBlink";
			ANSIStyle["Hidden"] = "ansiHidden";
			ANSIStyle["CrossedOut"] = "ansiCrossedOut";
			ANSIStyle["Fraktur"] = "ansiFraktur";
			ANSIStyle["DoubleUnderlined"] = "ansiDoubleUnderlined";
			ANSIStyle["Framed"] = "ansiFramed";
			ANSIStyle["Encircled"] = "ansiEncircled";
			ANSIStyle["Overlined"] = "ansiOverlined";
			ANSIStyle["Superscript"] = "ansiSuperscript";
			ANSIStyle["Subscript"] = "ansiSubscript";
		})(ANSIStyle || (exports$1.ANSIStyle = ANSIStyle = {}));
		/**
		* ANSIFont enumeration.
		*/
		var ANSIFont;
		(function(ANSIFont) {
			ANSIFont["AlternativeFont1"] = "ansiAlternativeFont1";
			ANSIFont["AlternativeFont2"] = "ansiAlternativeFont2";
			ANSIFont["AlternativeFont3"] = "ansiAlternativeFont3";
			ANSIFont["AlternativeFont4"] = "ansiAlternativeFont4";
			ANSIFont["AlternativeFont5"] = "ansiAlternativeFont5";
			ANSIFont["AlternativeFont6"] = "ansiAlternativeFont6";
			ANSIFont["AlternativeFont7"] = "ansiAlternativeFont7";
			ANSIFont["AlternativeFont8"] = "ansiAlternativeFont8";
			ANSIFont["AlternativeFont9"] = "ansiAlternativeFont9";
		})(ANSIFont || (exports$1.ANSIFont = ANSIFont = {}));
		/**
		* SGRColor enumeration.
		*/
		var ANSIColor;
		(function(ANSIColor) {
			ANSIColor["Black"] = "ansiBlack";
			ANSIColor["Red"] = "ansiRed";
			ANSIColor["Green"] = "ansiGreen";
			ANSIColor["Yellow"] = "ansiYellow";
			ANSIColor["Blue"] = "ansiBlue";
			ANSIColor["Magenta"] = "ansiMagenta";
			ANSIColor["Cyan"] = "ansiCyan";
			ANSIColor["White"] = "ansiWhite";
			ANSIColor["BrightBlack"] = "ansiBrightBlack";
			ANSIColor["BrightRed"] = "ansiBrightRed";
			ANSIColor["BrightGreen"] = "ansiBrightGreen";
			ANSIColor["BrightYellow"] = "ansiBrightYellow";
			ANSIColor["BrightBlue"] = "ansiBrightBlue";
			ANSIColor["BrightMagenta"] = "ansiBrightMagenta";
			ANSIColor["BrightCyan"] = "ansiBrightCyan";
			ANSIColor["BrightWhite"] = "ansiBrightWhite";
		})(ANSIColor || (exports$1.ANSIColor = ANSIColor = {}));
		/**
		* ANSIOutput class.
		*/
		class ANSIOutput {
			/**
			* Gets or sets the parser state.
			*/
			_parserState = ParserState.BufferingOutput;
			/**
			* Gets or sets the control sequence that's being parsed.
			*/
			_controlSequence = "";
			/**
			* Gets or sets the SGR state.
			*/
			_sgrState = void 0;
			/**
			* Gets or sets the current set of output lines.
			*/
			_outputLines = [];
			/**
			* Gets or sets the output line.
			*/
			_outputLine = 0;
			/**
			* Gets or sets the output column.
			*/
			_outputColumn = 0;
			/**
			* Gets or sets the buffer.
			*/
			_buffer = "";
			/**
			* Gets or sets a value which indicates whether there is a pending newline.
			*/
			_pendingNewline = false;
			/**
			* Gets the output lines.
			*/
			get outputLines() {
				this.flushBuffer();
				return this._outputLines;
			}
			/**
			* Processes output and returns the ANSIOutput lines of the output.
			* @param output The output to process.
			* @returns The ANSIOutput lines of the output.
			*/
			static processOutput(output) {
				const ansiOutput = new ANSIOutput();
				ansiOutput.processOutput(output);
				return ansiOutput.outputLines;
			}
			/**
			* Processes output.
			* @param output The output to process.
			*/
			processOutput(output) {
				for (let i = 0; i < output.length; i++) {
					if (this._pendingNewline) {
						this.flushBuffer();
						this._outputLine++;
						this._outputColumn = 0;
						this._pendingNewline = false;
					}
					const char = output.charAt(i);
					if (this._parserState === ParserState.BufferingOutput) {
						if (char === "\x1B") {
							this.flushBuffer();
							this._parserState = ParserState.ControlSequenceStarted;
						} else if (char === "") {
							this.flushBuffer();
							this._parserState = ParserState.ParsingControlSequence;
						} else this.processCharacter(char);
					} else if (this._parserState === ParserState.ControlSequenceStarted) {
						if (char === "[") this._parserState = ParserState.ParsingControlSequence;
						else {
							this._parserState = ParserState.BufferingOutput;
							this.processCharacter(char);
						}
					} else if (this._parserState === ParserState.ParsingControlSequence) {
						this._controlSequence += char;
						if (char.match(/^[A-Za-z]$/)) this.processControlSequence();
					}
				}
				this.flushBuffer();
			}
			/**
			* Flushes the buffer to the output line.
			*/
			flushBuffer() {
				for (let i = this._outputLines.length; i < this._outputLine + 1; i++) this._outputLines.push(new OutputLine());
				if (this._buffer) {
					this._outputLines[this._outputLine].insert(this._buffer, this._outputColumn, this._sgrState);
					this._outputColumn += this._buffer.length;
					this._buffer = "";
				}
			}
			/**
			* Processes a character.
			* @param char The character.
			*/
			processCharacter(char) {
				switch (char) {
					case "\n":
						this._pendingNewline = true;
						break;
					case "\r":
						this.flushBuffer();
						this._outputColumn = 0;
						break;
					default: this._buffer += char;
				}
			}
			/**
			* Processes a control sequence.
			*/
			processControlSequence() {
				switch (this._controlSequence.charAt(this._controlSequence.length - 1)) {
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
					case "m": this.processSGR();
				}
				this._controlSequence = "";
				this._parserState = ParserState.BufferingOutput;
			}
			/**
			* Processes a CUU (Cursor Up) control sequence.
			*/
			processCUU() {
				const match = this._controlSequence.match(/^([0-9]*)A$/);
				if (match) this._outputLine = Math.max(this._outputLine - rangeParam(match[1], 1, 1), 0);
			}
			/**
			* Processes a CUD (Cursor Down) control sequence.
			*/
			processCUD() {
				const match = this._controlSequence.match(/^([0-9]*)B$/);
				if (match) this._outputLine = this._outputLine + rangeParam(match[1], 1, 1);
			}
			/**
			* Processes a CUF (Cursor Forward) control sequence.
			*/
			processCUF() {
				const match = this._controlSequence.match(/^([0-9]*)C$/);
				if (match) this._outputColumn = this._outputColumn + rangeParam(match[1], 1, 1);
			}
			/**
			* Processes a CUB (Cursor Backward) control sequence.
			*/
			processCUB() {
				const match = this._controlSequence.match(/^([0-9]*)D$/);
				if (match) this._outputColumn = Math.max(this._outputColumn - rangeParam(match[1], 1, 1), 0);
			}
			/**
			* Processes a CUP (Cursor Position) control sequence.
			*/
			processCUP() {
				const match = this._controlSequence.match(/^([0-9]*)(?:;?([0-9]*))H$/);
				if (match) {
					this._outputLine = rangeParam(match[1], 1, 1) - 1;
					this._outputColumn = rangeParam(match[2], 1, 1) - 1;
				}
			}
			/**
			* Processes an ED (Erase in Display) control sequence.
			*/
			processED() {
				const match = this._controlSequence.match(/^([0-9]*)J$/);
				if (match) switch (getParam(match[1], 0)) {
					case 0:
						this._outputLines[this._outputLine].clearToEndOfLine(this._outputColumn);
						for (let i = this._outputLine + 1; i < this._outputLines.length; i++) this._outputLines[i].clearEntireLine();
						break;
					case 1:
						this._outputLines[this._outputLine].clearToBeginningOfLine(this._outputColumn);
						for (let i = 0; i < this._outputLine; i++) this._outputLines[i].clearEntireLine();
						break;
					case 2: for (let i = 0; i < this._outputLines.length; i++) this._outputLines[i].clearEntireLine();
				}
			}
			/**
			* Processes an EL (Erase in Line) control sequence.
			*/
			processEL() {
				const match = this._controlSequence.match(/^([0-9]*)K$/);
				if (match) {
					const outputLine = this._outputLines[this._outputLine];
					switch (getParam(match[1], 0)) {
						case 0:
							outputLine.clearToEndOfLine(this._outputColumn);
							break;
						case 1:
							outputLine.clearToBeginningOfLine(this._outputColumn);
							break;
						case 2: outputLine.clearEntireLine();
					}
				}
			}
			/**
			* Processes an SGR (Select Graphic Rendition) control sequence.
			*/
			processSGR() {
				const sgrState = this._sgrState ? this._sgrState.copy() : new SGRState();
				const sgrParams = this._controlSequence.slice(0, -1).split(";").map((sgrParam) => sgrParam === "" ? SGRParam.Reset : parseInt(sgrParam, 10));
				for (let index = 0; index < sgrParams.length; index++) {
					const sgrParam = sgrParams[index];
					/**
					* Process SetForeground, SetBackground, or SetUnderline. Contrary to information you
					* will find on the web, these parameters can be combined with other parameters. As an
					* example:
					*
					* For the 256-color palette:
					* console.log('\x1b[31;38;5;196mThis will be red\x1b[m');
					* console.log('\x1b[31;38;5;20mThis will be blue\x1b[m')
					*
					* For RGB:
					* console.log('\x1b[31;38;2;255;0;0mThis will be red\x1b[m');
					* console.log('\x1b[31;38;2;0;0;255mThis will be blue\x1b[m');
					*/
					const processSetColor = () => {
						if (index + 1 === sgrParams.length) return;
						switch (sgrParams[++index]) {
							case SGRParamColor.Color256: {
								if (index + 1 === sgrParams.length) return;
								const colorIndex = sgrParams[++index];
								switch (colorIndex) {
									case SGRParamIndexedColor.Black: return ANSIColor.Black;
									case SGRParamIndexedColor.Red: return ANSIColor.Red;
									case SGRParamIndexedColor.Green: return ANSIColor.Green;
									case SGRParamIndexedColor.Yellow: return ANSIColor.Yellow;
									case SGRParamIndexedColor.Blue: return ANSIColor.Blue;
									case SGRParamIndexedColor.Magenta: return ANSIColor.Magenta;
									case SGRParamIndexedColor.Cyan: return ANSIColor.Cyan;
									case SGRParamIndexedColor.White: return ANSIColor.White;
									case SGRParamIndexedColor.BrightBlack: return ANSIColor.BrightBlack;
									case SGRParamIndexedColor.BrightRed: return ANSIColor.BrightRed;
									case SGRParamIndexedColor.BrightGreen: return ANSIColor.BrightGreen;
									case SGRParamIndexedColor.BrightYellow: return ANSIColor.BrightYellow;
									case SGRParamIndexedColor.BrightBlue: return ANSIColor.BrightBlue;
									case SGRParamIndexedColor.BrightMagenta: return ANSIColor.BrightMagenta;
									case SGRParamIndexedColor.BrightCyan: return ANSIColor.BrightCyan;
									case SGRParamIndexedColor.BrightWhite: return ANSIColor.BrightWhite;
									default:
										if (colorIndex % 1 !== 0) return;
										if (colorIndex >= 16 && colorIndex <= 231) {
											let colorNumber = colorIndex - 16;
											let blue = colorNumber % 6;
											colorNumber = (colorNumber - blue) / 6;
											let green = colorNumber % 6;
											colorNumber = (colorNumber - green) / 6;
											let red = colorNumber;
											blue = Math.round(blue * 255 / 5);
											green = Math.round(green * 255 / 5);
											red = Math.round(red * 255 / 5);
											return "#" + twoDigitHex(red) + twoDigitHex(green) + twoDigitHex(blue);
										} else if (colorIndex >= 232 && colorIndex <= 255) {
											const rgb = Math.round((colorIndex - 232) / 23 * 255);
											const grayscale = twoDigitHex(rgb);
											return "#" + grayscale + grayscale + grayscale;
										} else return;
								}
							}
							case SGRParamColor.ColorRGB: {
								const rgb = [
									0,
									0,
									0
								];
								for (let i = 0; i < 3 && index + 1 < sgrParams.length; i++) rgb[i] = sgrParams[++index];
								return "#" + twoDigitHex(rgb[0]) + twoDigitHex(rgb[1]) + twoDigitHex(rgb[2]);
							}
						}
					};
					switch (sgrParam) {
						case SGRParam.Reset:
							sgrState.reset();
							break;
						case SGRParam.Bold:
							sgrState.setStyle(ANSIStyle.Bold);
							break;
						case SGRParam.Dim:
							sgrState.setStyle(ANSIStyle.Dim);
							break;
						case SGRParam.Italic:
							sgrState.setStyle(ANSIStyle.Italic);
							break;
						case SGRParam.Underlined:
							sgrState.setStyle(ANSIStyle.Underlined, ANSIStyle.DoubleUnderlined);
							break;
						case SGRParam.SlowBlink:
							sgrState.setStyle(ANSIStyle.SlowBlink, ANSIStyle.RapidBlink);
							break;
						case SGRParam.RapidBlink:
							sgrState.setStyle(ANSIStyle.RapidBlink, ANSIStyle.SlowBlink);
							break;
						case SGRParam.Reversed:
							sgrState.setReversed(true);
							break;
						case SGRParam.Hidden:
							sgrState.setStyle(ANSIStyle.Hidden);
							break;
						case SGRParam.CrossedOut:
							sgrState.setStyle(ANSIStyle.CrossedOut);
							break;
						case SGRParam.PrimaryFont:
							sgrState.setFont();
							break;
						case SGRParam.AlternativeFont1:
							sgrState.setFont(ANSIFont.AlternativeFont1);
							break;
						case SGRParam.AlternativeFont2:
							sgrState.setFont(ANSIFont.AlternativeFont2);
							break;
						case SGRParam.AlternativeFont3:
							sgrState.setFont(ANSIFont.AlternativeFont3);
							break;
						case SGRParam.AlternativeFont4:
							sgrState.setFont(ANSIFont.AlternativeFont4);
							break;
						case SGRParam.AlternativeFont5:
							sgrState.setFont(ANSIFont.AlternativeFont5);
							break;
						case SGRParam.AlternativeFont6:
							sgrState.setFont(ANSIFont.AlternativeFont6);
							break;
						case SGRParam.AlternativeFont7:
							sgrState.setFont(ANSIFont.AlternativeFont7);
							break;
						case SGRParam.AlternativeFont8:
							sgrState.setFont(ANSIFont.AlternativeFont8);
							break;
						case SGRParam.AlternativeFont9:
							sgrState.setFont(ANSIFont.AlternativeFont9);
							break;
						case SGRParam.Fraktur:
							sgrState.setStyle(ANSIStyle.Fraktur);
							break;
						case SGRParam.DoubleUnderlined:
							sgrState.setStyle(ANSIStyle.DoubleUnderlined, ANSIStyle.Underlined);
							break;
						case SGRParam.NormalIntensity:
							sgrState.deleteStyles(ANSIStyle.Bold, ANSIStyle.Dim);
							break;
						case SGRParam.NotItalicNotFraktur:
							sgrState.deleteStyles(ANSIStyle.Italic, ANSIStyle.Fraktur);
							break;
						case SGRParam.NotUnderlined:
							sgrState.deleteStyles(ANSIStyle.Underlined, ANSIStyle.DoubleUnderlined);
							break;
						case SGRParam.NotBlinking:
							sgrState.deleteStyles(ANSIStyle.SlowBlink, ANSIStyle.RapidBlink);
							break;
						case SGRParam.ProportionalSpacing: break;
						case SGRParam.NotReversed:
							sgrState.setReversed(false);
							break;
						case SGRParam.Reveal:
							sgrState.deleteStyles(ANSIStyle.Hidden);
							break;
						case SGRParam.NotCrossedOut:
							sgrState.deleteStyles(ANSIStyle.CrossedOut);
							break;
						case SGRParam.ForegroundBlack:
							sgrState.setForegroundColor(ANSIColor.Black);
							break;
						case SGRParam.ForegroundRed:
							sgrState.setForegroundColor(ANSIColor.Red);
							break;
						case SGRParam.ForegroundGreen:
							sgrState.setForegroundColor(ANSIColor.Green);
							break;
						case SGRParam.ForegroundYellow:
							sgrState.setForegroundColor(ANSIColor.Yellow);
							break;
						case SGRParam.ForegroundBlue:
							sgrState.setForegroundColor(ANSIColor.Blue);
							break;
						case SGRParam.ForegroundMagenta:
							sgrState.setForegroundColor(ANSIColor.Magenta);
							break;
						case SGRParam.ForegroundCyan:
							sgrState.setForegroundColor(ANSIColor.Cyan);
							break;
						case SGRParam.ForegroundWhite:
							sgrState.setForegroundColor(ANSIColor.White);
							break;
						case SGRParam.SetForeground: {
							const foregroundColor = processSetColor();
							if (foregroundColor) sgrState.setForegroundColor(foregroundColor);
							break;
						}
						case SGRParam.DefaultForeground:
							sgrState.setForegroundColor();
							break;
						case SGRParam.BackgroundBlack:
							sgrState.setBackgroundColor(ANSIColor.Black);
							break;
						case SGRParam.BackgroundRed:
							sgrState.setBackgroundColor(ANSIColor.Red);
							break;
						case SGRParam.BackgroundGreen:
							sgrState.setBackgroundColor(ANSIColor.Green);
							break;
						case SGRParam.BackgroundYellow:
							sgrState.setBackgroundColor(ANSIColor.Yellow);
							break;
						case SGRParam.BackgroundBlue:
							sgrState.setBackgroundColor(ANSIColor.Blue);
							break;
						case SGRParam.BackgroundMagenta:
							sgrState.setBackgroundColor(ANSIColor.Magenta);
							break;
						case SGRParam.BackgroundCyan:
							sgrState.setBackgroundColor(ANSIColor.Cyan);
							break;
						case SGRParam.BackgroundWhite:
							sgrState.setBackgroundColor(ANSIColor.White);
							break;
						case SGRParam.SetBackground: {
							const backgroundColor = processSetColor();
							if (backgroundColor) sgrState.setBackgroundColor(backgroundColor);
							break;
						}
						case SGRParam.DefaultBackground:
							sgrState.setBackgroundColor();
							break;
						case SGRParam.ForegroundBrightBlack:
							sgrState.setForegroundColor(ANSIColor.BrightBlack);
							break;
						case SGRParam.ForegroundBrightRed:
							sgrState.setForegroundColor(ANSIColor.BrightRed);
							break;
						case SGRParam.ForegroundBrightGreen:
							sgrState.setForegroundColor(ANSIColor.BrightGreen);
							break;
						case SGRParam.ForegroundBrightYellow:
							sgrState.setForegroundColor(ANSIColor.BrightYellow);
							break;
						case SGRParam.ForegroundBrightBlue:
							sgrState.setForegroundColor(ANSIColor.BrightBlue);
							break;
						case SGRParam.ForegroundBrightMagenta:
							sgrState.setForegroundColor(ANSIColor.BrightMagenta);
							break;
						case SGRParam.ForegroundBrightCyan:
							sgrState.setForegroundColor(ANSIColor.BrightCyan);
							break;
						case SGRParam.ForegroundBrightWhite:
							sgrState.setForegroundColor(ANSIColor.BrightWhite);
							break;
						case SGRParam.BackgroundBrightBlack:
							sgrState.setBackgroundColor(ANSIColor.BrightBlack);
							break;
						case SGRParam.BackgroundBrightRed:
							sgrState.setBackgroundColor(ANSIColor.BrightRed);
							break;
						case SGRParam.BackgroundBrightGreen:
							sgrState.setBackgroundColor(ANSIColor.BrightGreen);
							break;
						case SGRParam.BackgroundBrightYellow:
							sgrState.setBackgroundColor(ANSIColor.BrightYellow);
							break;
						case SGRParam.BackgroundBrightBlue:
							sgrState.setBackgroundColor(ANSIColor.BrightBlue);
							break;
						case SGRParam.BackgroundBrightMagenta:
							sgrState.setBackgroundColor(ANSIColor.BrightMagenta);
							break;
						case SGRParam.BackgroundBrightCyan:
							sgrState.setBackgroundColor(ANSIColor.BrightCyan);
							break;
						case SGRParam.BackgroundBrightWhite: sgrState.setBackgroundColor(ANSIColor.BrightWhite);
					}
				}
				if (!SGRState.equivalent(sgrState, this._sgrState)) this._sgrState = sgrState;
			}
		}
		exports$1.ANSIOutput = ANSIOutput;
		/**
		* SGRParam enumeration.
		*/
		var SGRParam;
		(function(SGRParam) {
			SGRParam[SGRParam["Reset"] = 0] = "Reset";
			SGRParam[SGRParam["Bold"] = 1] = "Bold";
			SGRParam[SGRParam["Dim"] = 2] = "Dim";
			SGRParam[SGRParam["Italic"] = 3] = "Italic";
			SGRParam[SGRParam["Underlined"] = 4] = "Underlined";
			SGRParam[SGRParam["SlowBlink"] = 5] = "SlowBlink";
			SGRParam[SGRParam["RapidBlink"] = 6] = "RapidBlink";
			SGRParam[SGRParam["Reversed"] = 7] = "Reversed";
			SGRParam[SGRParam["Hidden"] = 8] = "Hidden";
			SGRParam[SGRParam["CrossedOut"] = 9] = "CrossedOut";
			SGRParam[SGRParam["PrimaryFont"] = 10] = "PrimaryFont";
			SGRParam[SGRParam["AlternativeFont1"] = 11] = "AlternativeFont1";
			SGRParam[SGRParam["AlternativeFont2"] = 12] = "AlternativeFont2";
			SGRParam[SGRParam["AlternativeFont3"] = 13] = "AlternativeFont3";
			SGRParam[SGRParam["AlternativeFont4"] = 14] = "AlternativeFont4";
			SGRParam[SGRParam["AlternativeFont5"] = 15] = "AlternativeFont5";
			SGRParam[SGRParam["AlternativeFont6"] = 16] = "AlternativeFont6";
			SGRParam[SGRParam["AlternativeFont7"] = 17] = "AlternativeFont7";
			SGRParam[SGRParam["AlternativeFont8"] = 18] = "AlternativeFont8";
			SGRParam[SGRParam["AlternativeFont9"] = 19] = "AlternativeFont9";
			SGRParam[SGRParam["Fraktur"] = 20] = "Fraktur";
			SGRParam[SGRParam["DoubleUnderlined"] = 21] = "DoubleUnderlined";
			SGRParam[SGRParam["NormalIntensity"] = 22] = "NormalIntensity";
			SGRParam[SGRParam["NotItalicNotFraktur"] = 23] = "NotItalicNotFraktur";
			SGRParam[SGRParam["NotUnderlined"] = 24] = "NotUnderlined";
			SGRParam[SGRParam["NotBlinking"] = 25] = "NotBlinking";
			SGRParam[SGRParam["ProportionalSpacing"] = 26] = "ProportionalSpacing";
			SGRParam[SGRParam["NotReversed"] = 27] = "NotReversed";
			SGRParam[SGRParam["Reveal"] = 28] = "Reveal";
			SGRParam[SGRParam["NotCrossedOut"] = 29] = "NotCrossedOut";
			SGRParam[SGRParam["ForegroundBlack"] = 30] = "ForegroundBlack";
			SGRParam[SGRParam["ForegroundRed"] = 31] = "ForegroundRed";
			SGRParam[SGRParam["ForegroundGreen"] = 32] = "ForegroundGreen";
			SGRParam[SGRParam["ForegroundYellow"] = 33] = "ForegroundYellow";
			SGRParam[SGRParam["ForegroundBlue"] = 34] = "ForegroundBlue";
			SGRParam[SGRParam["ForegroundMagenta"] = 35] = "ForegroundMagenta";
			SGRParam[SGRParam["ForegroundCyan"] = 36] = "ForegroundCyan";
			SGRParam[SGRParam["ForegroundWhite"] = 37] = "ForegroundWhite";
			SGRParam[SGRParam["SetForeground"] = 38] = "SetForeground";
			SGRParam[SGRParam["DefaultForeground"] = 39] = "DefaultForeground";
			SGRParam[SGRParam["BackgroundBlack"] = 40] = "BackgroundBlack";
			SGRParam[SGRParam["BackgroundRed"] = 41] = "BackgroundRed";
			SGRParam[SGRParam["BackgroundGreen"] = 42] = "BackgroundGreen";
			SGRParam[SGRParam["BackgroundYellow"] = 43] = "BackgroundYellow";
			SGRParam[SGRParam["BackgroundBlue"] = 44] = "BackgroundBlue";
			SGRParam[SGRParam["BackgroundMagenta"] = 45] = "BackgroundMagenta";
			SGRParam[SGRParam["BackgroundCyan"] = 46] = "BackgroundCyan";
			SGRParam[SGRParam["BackgroundWhite"] = 47] = "BackgroundWhite";
			SGRParam[SGRParam["SetBackground"] = 48] = "SetBackground";
			SGRParam[SGRParam["DefaultBackground"] = 49] = "DefaultBackground";
			SGRParam[SGRParam["DisableProportionalSpacing"] = 50] = "DisableProportionalSpacing";
			SGRParam[SGRParam["Framed"] = 51] = "Framed";
			SGRParam[SGRParam["Encircled"] = 52] = "Encircled";
			SGRParam[SGRParam["Overlined"] = 53] = "Overlined";
			SGRParam[SGRParam["NotFramedNotEncircled"] = 54] = "NotFramedNotEncircled";
			SGRParam[SGRParam["NotOverlined"] = 55] = "NotOverlined";
			SGRParam[SGRParam["SetUnderline"] = 58] = "SetUnderline";
			SGRParam[SGRParam["DefaultUnderline"] = 59] = "DefaultUnderline";
			SGRParam[SGRParam["IdeogramUnderlineOrRightSideLine"] = 60] = "IdeogramUnderlineOrRightSideLine";
			SGRParam[SGRParam["IdeogramDoubleUnderlineOrDoubleRightSideLine"] = 61] = "IdeogramDoubleUnderlineOrDoubleRightSideLine";
			SGRParam[SGRParam["IdeogramOverlineOrLeftSideLine"] = 62] = "IdeogramOverlineOrLeftSideLine";
			SGRParam[SGRParam["IdeogramDoubleOverlineOrDoubleLeftSideLine"] = 63] = "IdeogramDoubleOverlineOrDoubleLeftSideLine";
			SGRParam[SGRParam["IdeogramStressMarking"] = 64] = "IdeogramStressMarking";
			SGRParam[SGRParam["NoIdeogramAttributes"] = 65] = "NoIdeogramAttributes";
			SGRParam[SGRParam["Superscript"] = 73] = "Superscript";
			SGRParam[SGRParam["Subscript"] = 74] = "Subscript";
			SGRParam[SGRParam["NotSuperscriptNotSubscript"] = 75] = "NotSuperscriptNotSubscript";
			SGRParam[SGRParam["ForegroundBrightBlack"] = 90] = "ForegroundBrightBlack";
			SGRParam[SGRParam["ForegroundBrightRed"] = 91] = "ForegroundBrightRed";
			SGRParam[SGRParam["ForegroundBrightGreen"] = 92] = "ForegroundBrightGreen";
			SGRParam[SGRParam["ForegroundBrightYellow"] = 93] = "ForegroundBrightYellow";
			SGRParam[SGRParam["ForegroundBrightBlue"] = 94] = "ForegroundBrightBlue";
			SGRParam[SGRParam["ForegroundBrightMagenta"] = 95] = "ForegroundBrightMagenta";
			SGRParam[SGRParam["ForegroundBrightCyan"] = 96] = "ForegroundBrightCyan";
			SGRParam[SGRParam["ForegroundBrightWhite"] = 97] = "ForegroundBrightWhite";
			SGRParam[SGRParam["BackgroundBrightBlack"] = 100] = "BackgroundBrightBlack";
			SGRParam[SGRParam["BackgroundBrightRed"] = 101] = "BackgroundBrightRed";
			SGRParam[SGRParam["BackgroundBrightGreen"] = 102] = "BackgroundBrightGreen";
			SGRParam[SGRParam["BackgroundBrightYellow"] = 103] = "BackgroundBrightYellow";
			SGRParam[SGRParam["BackgroundBrightBlue"] = 104] = "BackgroundBrightBlue";
			SGRParam[SGRParam["BackgroundBrightMagenta"] = 105] = "BackgroundBrightMagenta";
			SGRParam[SGRParam["BackgroundBrightCyan"] = 106] = "BackgroundBrightCyan";
			SGRParam[SGRParam["BackgroundBrightWhite"] = 107] = "BackgroundBrightWhite";
		})(SGRParam || (SGRParam = {}));
		/**
		* SGRParamColor enumeration.
		*/
		var SGRParamColor;
		(function(SGRParamColor) {
			SGRParamColor[SGRParamColor["Color256"] = 5] = "Color256";
			SGRParamColor[SGRParamColor["ColorRGB"] = 2] = "ColorRGB";
		})(SGRParamColor || (SGRParamColor = {}));
		/**
		* SGRParamIndexedColor enumeration.
		*/
		var SGRParamIndexedColor;
		(function(SGRParamIndexedColor) {
			SGRParamIndexedColor[SGRParamIndexedColor["Black"] = 0] = "Black";
			SGRParamIndexedColor[SGRParamIndexedColor["Red"] = 1] = "Red";
			SGRParamIndexedColor[SGRParamIndexedColor["Green"] = 2] = "Green";
			SGRParamIndexedColor[SGRParamIndexedColor["Yellow"] = 3] = "Yellow";
			SGRParamIndexedColor[SGRParamIndexedColor["Blue"] = 4] = "Blue";
			SGRParamIndexedColor[SGRParamIndexedColor["Magenta"] = 5] = "Magenta";
			SGRParamIndexedColor[SGRParamIndexedColor["Cyan"] = 6] = "Cyan";
			SGRParamIndexedColor[SGRParamIndexedColor["White"] = 7] = "White";
			SGRParamIndexedColor[SGRParamIndexedColor["BrightBlack"] = 8] = "BrightBlack";
			SGRParamIndexedColor[SGRParamIndexedColor["BrightRed"] = 9] = "BrightRed";
			SGRParamIndexedColor[SGRParamIndexedColor["BrightGreen"] = 10] = "BrightGreen";
			SGRParamIndexedColor[SGRParamIndexedColor["BrightYellow"] = 11] = "BrightYellow";
			SGRParamIndexedColor[SGRParamIndexedColor["BrightBlue"] = 12] = "BrightBlue";
			SGRParamIndexedColor[SGRParamIndexedColor["BrightMagenta"] = 13] = "BrightMagenta";
			SGRParamIndexedColor[SGRParamIndexedColor["BrightCyan"] = 14] = "BrightCyan";
			SGRParamIndexedColor[SGRParamIndexedColor["BrightWhite"] = 15] = "BrightWhite";
		})(SGRParamIndexedColor || (SGRParamIndexedColor = {}));
		/**
		* ParserState enumeration.
		*/
		var ParserState;
		(function(ParserState) {
			ParserState[ParserState["BufferingOutput"] = 0] = "BufferingOutput";
			ParserState[ParserState["ControlSequenceStarted"] = 1] = "ControlSequenceStarted";
			ParserState[ParserState["ParsingControlSequence"] = 2] = "ParsingControlSequence";
		})(ParserState || (ParserState = {}));
		/**
		* SGRState class.
		*/
		class SGRState {
			/**
			* Gets or sets the styles.
			*/
			_styles;
			/**
			* Gets or sets the foreground color.
			*/
			_foregroundColor;
			/**
			* Gets or sets the background color.
			*/
			_backgroundColor;
			/**
			* Gets or sets the underlined color.
			*/
			_underlinedColor;
			/**
			* Gets or sets a value which indicates whether the foreground and background colors are
			* reversed.
			*/
			_reversed;
			/**
			* Gets or sets the font.
			*/
			_font;
			/**
			* Resets the SGRState.
			*/
			reset() {
				this._styles = void 0;
				this._foregroundColor = void 0;
				this._backgroundColor = void 0;
				this._underlinedColor = void 0;
				this._reversed = void 0;
				this._font = void 0;
			}
			/**
			* Creates a copy of the SGRState.
			* @returns The copy of the SGRState.
			*/
			copy() {
				const copy = new SGRState();
				if (this._styles && this._styles.size) {
					const styles = /* @__PURE__ */ new Set();
					this._styles.forEach((style) => styles.add(style));
					copy._styles = styles;
				}
				copy._foregroundColor = this._foregroundColor;
				copy._backgroundColor = this._backgroundColor;
				copy._underlinedColor = this._underlinedColor;
				copy._reversed = this._reversed;
				copy._font = this._font;
				return copy;
			}
			/**
			* Sets a style.
			* @param style The style to set.
			* @param stylesToDelete The styles to delete.
			*/
			setStyle(style, ...stylesToDelete) {
				if (this._styles) for (const style of stylesToDelete) this._styles.delete(style);
				else this._styles = /* @__PURE__ */ new Set();
				this._styles.add(style);
			}
			/**
			* Deletes styles.
			* @param stylesToDelete The styles to delete.
			*/
			deleteStyles(...stylesToDelete) {
				if (this._styles) {
					for (const style of stylesToDelete) this._styles.delete(style);
					if (!this._styles.size) this._styles = void 0;
				}
			}
			/**
			* Sets the foreground color.
			* @param color The foreground color.
			*/
			setForegroundColor(color) {
				if (!this._reversed) this._foregroundColor = color;
				else this._backgroundColor = color;
			}
			/**
			* Sets the background color.
			* @param color The background color.
			*/
			setBackgroundColor(color) {
				if (!this._reversed) this._backgroundColor = color;
				else this._foregroundColor = color;
			}
			/**
			* Sets reversed.
			* @param reversed A value which indicates whether the foreground and background colors are
			* reversed.
			*/
			setReversed(reversed) {
				if (reversed) {
					if (!this._reversed) {
						this._reversed = true;
						this.reverseForegroundAndBackgroundColors();
					}
				} else if (this._reversed) {
					this._reversed = void 0;
					this.reverseForegroundAndBackgroundColors();
				}
			}
			/**
			* Sets the font.
			* @param font The font.
			*/
			setFont(font) {
				this._font = font;
			}
			/**
			*
			* @param left
			* @param right
			* @returns
			*/
			static equivalent(left, right) {
				const setReplacer = (_, value) => value instanceof Set ? !value.size ? void 0 : [...value] : value;
				return left === right || JSON.stringify(left, setReplacer) === JSON.stringify(right, setReplacer);
			}
			/**
			* Gets the styles.
			*/
			get styles() {
				return !this._styles ? void 0 : [...this._styles];
			}
			/**
			* Gets the foreground color.
			*/
			get foregroundColor() {
				if (this._backgroundColor && !this._foregroundColor) switch (this._backgroundColor) {
					case ANSIColor.Black:
					case ANSIColor.BrightBlack:
					case ANSIColor.Red:
					case ANSIColor.BrightRed: return ANSIColor.White;
					case ANSIColor.Green:
					case ANSIColor.BrightGreen:
					case ANSIColor.Yellow:
					case ANSIColor.BrightYellow:
					case ANSIColor.Blue:
					case ANSIColor.BrightBlue:
					case ANSIColor.Magenta:
					case ANSIColor.BrightMagenta:
					case ANSIColor.Cyan:
					case ANSIColor.BrightCyan:
					case ANSIColor.White:
					case ANSIColor.BrightWhite: return ANSIColor.Black;
				}
				return this._foregroundColor;
			}
			/**
			* Gets the background color.
			*/
			get backgroundColor() {
				return this._backgroundColor;
			}
			/**
			* Gets the underlined color.
			*/
			get underlinedColor() {
				return this._underlinedColor;
			}
			/**
			* Gets the font.
			*/
			get font() {
				return this._font;
			}
			/**
			* Reverses the foreground and background colors.
			*/
			reverseForegroundAndBackgroundColors() {
				const foregroundColor = this._foregroundColor;
				this._foregroundColor = this._backgroundColor;
				this._backgroundColor = foregroundColor;
			}
		}
		/**
		* OutputLine class.
		*/
		class OutputLine {
			/**
			* Gets the identifier.
			*/
			_id = generateId();
			/**
			* Gets or sets the output runs.
			*/
			_outputRuns = [];
			/**
			* Gets or sets the total length.
			*/
			_totalLength = 0;
			/**
			* Clears the entire output line.
			*/
			clearEntireLine() {
				if (this._totalLength) this._outputRuns = [new OutputRun(" ".repeat(this._totalLength))];
			}
			/**
			* Clears to the end of the output line.
			* @param column The column at which to clear from.
			*/
			clearToEndOfLine(column) {
				column = Math.max(column, 0);
				if (column >= this._totalLength) return;
				if (column === 0) {
					this.clearEntireLine();
					return;
				}
				let leftOffset = 0;
				let leftOutputRun;
				let leftOutputRunIndex = void 0;
				for (let index = 0; index < this._outputRuns.length; index++) {
					const outputRun = this._outputRuns[index];
					if (column < leftOffset + outputRun.text.length) {
						leftOutputRun = outputRun;
						leftOutputRunIndex = index;
						break;
					}
					leftOffset += outputRun.text.length;
				}
				if (leftOutputRun === void 0 || leftOutputRunIndex === void 0) return;
				const leftTextLength = column - leftOffset;
				const erasureText = " ".repeat(this._totalLength - column);
				const outputRuns = [];
				if (!leftTextLength) outputRuns.push(new OutputRun(erasureText));
				else {
					const leftText = leftOutputRun.text.slice(0, leftTextLength);
					outputRuns.push(new OutputRun(leftText, leftOutputRun.sgrState));
					outputRuns.push(new OutputRun(erasureText));
				}
				this.outputRuns.splice(leftOutputRunIndex, this._outputRuns.length - leftOutputRunIndex, ...outputRuns);
			}
			/**
			* Clears to the beginning of the output line.
			* @param column The column at which to clear from.
			*/
			clearToBeginningOfLine(column) {
				column = Math.max(column, 0);
				if (column === 0) return;
				if (column >= this._totalLength) {
					this.clearEntireLine();
					return;
				}
				let rightOffset = 0;
				let rightOutputRun;
				let rightOutputRunIndex = void 0;
				for (let index = this._outputRuns.length - 1; index >= 0; index--) {
					const outputRun = this._outputRuns[index];
					if (column >= rightOffset - outputRun.text.length) {
						rightOutputRun = outputRun;
						rightOutputRunIndex = index;
						break;
					}
					rightOffset -= outputRun.text.length;
				}
				if (rightOutputRun === void 0 || rightOutputRunIndex === void 0) return;
				const rightTextLength = rightOffset - column;
				const erasureText = " ".repeat(column);
				const outputRuns = [new OutputRun(erasureText)];
				if (rightTextLength) {
					const rightOutputRunText = rightOutputRun.text.slice(-rightTextLength);
					outputRuns.push(new OutputRun(rightOutputRunText, rightOutputRun.sgrState));
				}
				this.outputRuns.splice(0, this._outputRuns.length - rightOutputRunIndex, ...outputRuns);
			}
			/**
			* Inserts text into the output line.
			* @param text The text to insert.
			* @param column The column at which to insert the text.
			* @param sgrState The SGR state.
			*/
			insert(text, column, sgrState) {
				if (!text.length) return;
				if (column === this._totalLength) {
					this._totalLength += text.length;
					if (this._outputRuns.length) {
						const lastOutputRun = this._outputRuns[this._outputRuns.length - 1];
						if (SGRState.equivalent(lastOutputRun.sgrState, sgrState)) {
							lastOutputRun.appendText(text);
							return;
						}
					}
					this._outputRuns.push(new OutputRun(text, sgrState));
					return;
				}
				if (column > this._totalLength) {
					const spacer = " ".repeat(column - this._totalLength);
					this._totalLength += spacer.length + text.length;
					if (!sgrState && this._outputRuns.length) {
						const lastOutputRun = this._outputRuns[this._outputRuns.length - 1];
						if (!lastOutputRun.sgrState) {
							lastOutputRun.appendText(spacer);
							lastOutputRun.appendText(text);
							return;
						}
					}
					if (!sgrState) this._outputRuns.push(new OutputRun(spacer + text));
					else {
						this._outputRuns.push(new OutputRun(spacer));
						this._outputRuns.push(new OutputRun(text, sgrState));
					}
				}
				let leftOffset = 0;
				let leftOutputRunIndex = void 0;
				for (let index = 0; index < this._outputRuns.length; index++) {
					const outputRun = this._outputRuns[index];
					if (column < leftOffset + outputRun.text.length) {
						leftOutputRunIndex = index;
						break;
					}
					leftOffset += outputRun.text.length;
				}
				if (leftOutputRunIndex === void 0) {
					this._outputRuns.push(new OutputRun(text, sgrState));
					return;
				}
				if (column + text.length >= this._totalLength) {
					const leftTextLength = column - leftOffset;
					const outputRuns = [];
					if (!leftTextLength) outputRuns.push(new OutputRun(text, sgrState));
					else {
						const leftOutputRun = this._outputRuns[leftOutputRunIndex];
						const leftText = leftOutputRun.text.slice(0, leftTextLength);
						if (SGRState.equivalent(leftOutputRun.sgrState, sgrState)) outputRuns.push(new OutputRun(leftText + text, sgrState));
						else {
							outputRuns.push(new OutputRun(leftText, leftOutputRun.sgrState));
							outputRuns.push(new OutputRun(text, sgrState));
						}
					}
					this.outputRuns.splice(leftOutputRunIndex, 1, ...outputRuns);
					this._totalLength = leftOffset + leftTextLength + text.length;
					return;
				}
				let rightOffset = this._totalLength;
				let rightOutputRunIndex = void 0;
				for (let index = this._outputRuns.length - 1; index >= 0; index--) {
					const outputRun = this._outputRuns[index];
					if (column + text.length > rightOffset - outputRun.text.length) {
						rightOutputRunIndex = index;
						break;
					}
					rightOffset -= outputRun.text.length;
				}
				if (rightOutputRunIndex === void 0) {
					this._outputRuns.push(new OutputRun(text, sgrState));
					return;
				}
				const outputRuns = [];
				const leftOutputRunTextLength = column - leftOffset;
				if (leftOutputRunTextLength) {
					const leftOutputRun = this._outputRuns[leftOutputRunIndex];
					const leftOutputRunText = leftOutputRun.text.slice(0, leftOutputRunTextLength);
					outputRuns.push(new OutputRun(leftOutputRunText, leftOutputRun.sgrState));
				}
				outputRuns.push(new OutputRun(text, sgrState));
				const rightOutputRunTextLength = rightOffset - (column + text.length);
				if (rightOutputRunTextLength) {
					const rightOutputRun = this._outputRuns[rightOutputRunIndex];
					const rightOutputRunText = rightOutputRun.text.slice(-rightOutputRunTextLength);
					outputRuns.push(new OutputRun(rightOutputRunText, rightOutputRun.sgrState));
				}
				this._outputRuns.splice(leftOutputRunIndex, rightOutputRunIndex - leftOutputRunIndex + 1, ...outputRuns);
				if (this._outputRuns.length > 1) this._outputRuns = OutputRun.optimizeOutputRuns(this._outputRuns);
				this._totalLength = this._outputRuns.reduce((totalLength, outputRun) => totalLength + outputRun.text.length, 0);
			}
			/**
			* Gets the identifier.
			*/
			get id() {
				return this._id;
			}
			/**
			* Gets the output runs.
			*/
			get outputRuns() {
				return this._outputRuns;
			}
		}
		/**
		* OutputRun class.
		*/
		class OutputRun {
			/**
			* Gets the identifier.
			*/
			_id = generateId();
			/**
			* Gets the SGR state.
			*/
			_sgrState;
			/**
			* Gets or sets the text.
			*/
			_text;
			get sgrState() {
				return this._sgrState;
			}
			/**
			* Constructor.
			* @param text The text.
			* @param sgrState The SGR state.
			*/
			constructor(text, sgrState) {
				this._sgrState = sgrState;
				this._text = text;
			}
			/**
			* Optimizes a an array of output runs by combining adjacent output runs with equivalent SGR
			* states.
			* @param outputRunsIn The output runs to optimize.
			* @returns The optimized output runs.
			*/
			static optimizeOutputRuns(outputRunsIn) {
				const outputRunsOut = [outputRunsIn[0]];
				for (let i = 1, o = 0; i < outputRunsIn.length; i++) {
					const outputRun = outputRunsIn[i];
					if (SGRState.equivalent(outputRunsOut[o].sgrState, outputRun.sgrState)) outputRunsOut[o]._text += outputRun.text;
					else outputRunsOut[++o] = outputRun;
				}
				return outputRunsOut;
			}
			/**
			* Appends text to the end of the output run.
			* @param text The text to append.
			*/
			appendText(text) {
				this._text += text;
			}
			/**
			* Gets the identifier.
			*/
			get id() {
				return this._id;
			}
			/**
			* Gets the format.
			*/
			get format() {
				return this._sgrState;
			}
			/**
			* Gets the text.
			*/
			get text() {
				return this._text;
			}
		}
		/**
		* Gets and ranges a parameter value.
		* @param value The value.
		* @param defaultValue The default value.
		* @param minValue The minimum value.
		* @returns The ranged parameter value.
		*/
		const rangeParam = (value, defaultValue, minValue) => {
			const param = getParam(value, defaultValue);
			return Math.max(param, minValue);
		};
		/**
		* Gets a parameter value.
		* @param value The value.
		* @param defaultValue The default value.
		* @returns The parameter value.
		*/
		const getParam = (value, defaultValue) => {
			const param = parseInt(value);
			return Number.isNaN(param) ? defaultValue : param;
		};
		/**
		* Converts a number to a two-digit hex string representing the value.
		* @param value The value.
		* @returns A two digit hex string representing the value.
		*/
		const twoDigitHex = (value) => {
			const hex = Math.max(Math.min(255, value), 0).toString(16);
			return hex.length === 2 ? hex : "0" + hex;
		};
	});
}));
//#endregion
//#region ../../packages/react/src/components/AnsiDisplayRich.module.css
var import_jsx_runtime = require_jsx_runtime();
var import_react = /* @__PURE__ */ __toESM(require_react(), 1);
var import_compiler_runtime = require_compiler_runtime();
var import_ansi_output = require_ansi_output();
var AnsiDisplayRich_module_default = {
	container: "_container_f35vk_1",
	toggle: "_toggle_f35vk_1"
};
//#endregion
//#region ../../packages/react/src/components/AnsiDisplayRich.tsx
var RichANSIDisplay = (t0) => {
	const $ = (0, import_compiler_runtime.c)(18);
	const { output, style, className } = t0;
	const icons = useComponentIcons();
	const [showRaw, setShowRaw] = (0, import_react.useState)(false);
	let t1;
	if ($[0] !== className || $[1] !== icons.code || $[2] !== output || $[3] !== showRaw || $[4] !== style) {
		const ansiOutput = new import_ansi_output.ANSIOutput();
		ansiOutput.processOutput(output);
		const getUniformBackgroundColor = () => {
			const backgroundColorCounts = /* @__PURE__ */ new Map();
			let totalLinesWithBackground = 0;
			for (const line of ansiOutput.outputLines) {
				let lineBackgroundColor = void 0;
				for (const run of line.outputRuns) if (run.format?.backgroundColor) {
					lineBackgroundColor = run.format.backgroundColor;
					break;
				}
				if (lineBackgroundColor) {
					totalLinesWithBackground++;
					backgroundColorCounts.set(lineBackgroundColor, (backgroundColorCounts.get(lineBackgroundColor) || 0) + 1);
				}
			}
			if (totalLinesWithBackground === 0) return;
			const backgroundColorPercentages = /* @__PURE__ */ new Map();
			for (const [color, count] of backgroundColorCounts.entries()) backgroundColorPercentages.set(color, count / totalLinesWithBackground);
			let dominantColor = void 0;
			let maxPercentage = 0;
			for (const [color_0, percentage] of backgroundColorPercentages.entries()) if (percentage > maxPercentage) {
				maxPercentage = percentage;
				dominantColor = color_0;
			}
			return maxPercentage > .8 ? dominantColor : void 0;
		};
		const uniformBackgroundColor = getUniformBackgroundColor();
		const backgroundStyle = uniformBackgroundColor ? computeForegroundBackgroundColor(kBackground, uniformBackgroundColor) : {};
		const firstOutputIndex = ansiOutput.outputLines.findIndex(_temp);
		let t2;
		if ($[6] !== className) {
			t2 = clsx(AnsiDisplay_module_default.ansiDisplayContainer, AnsiDisplayRich_module_default.container, className);
			$[6] = className;
			$[7] = t2;
		} else t2 = $[7];
		let t3;
		if ($[8] !== style) {
			t3 = { ...style };
			$[8] = style;
			$[9] = t3;
		} else t3 = $[9];
		let t4;
		if ($[10] === Symbol.for("react.memo_cache_sentinel")) {
			t4 = clsx(AnsiDisplayRich_module_default.toggle, "text-size-smallest");
			$[10] = t4;
		} else t4 = $[10];
		let t5;
		if ($[11] !== showRaw) {
			t5 = () => setShowRaw(!showRaw);
			$[11] = showRaw;
			$[12] = t5;
		} else t5 = $[12];
		const t6 = showRaw ? "Show rendered output" : "Show raw output";
		let t7;
		if ($[13] !== icons.code || $[14] !== showRaw || $[15] !== t5 || $[16] !== t6) {
			t7 = /*#__PURE__*/ (0, import_jsx_runtime.jsx)(ToolButton, {
				className: t4,
				icon: icons.code,
				label: "",
				latched: showRaw,
				onClick: t5,
				title: t6
			});
			$[13] = icons.code;
			$[14] = showRaw;
			$[15] = t5;
			$[16] = t6;
			$[17] = t7;
		} else t7 = $[17];
		t1 = /*#__PURE__*/ (0, import_jsx_runtime.jsxs)("div", {
			className: t2,
			style: t3,
			children: [t7, showRaw ? /*#__PURE__*/ (0, import_jsx_runtime.jsx)("pre", {
				className: clsx(AnsiDisplay_module_default.ansiDisplay, AnsiDisplay_module_default.ansiDisplayRaw),
				children: output
			}) : /*#__PURE__*/ (0, import_jsx_runtime.jsx)("div", {
				className: clsx(AnsiDisplay_module_default.ansiDisplay),
				style: backgroundStyle,
				children: ansiOutput.outputLines.map((line_1, index) => /*#__PURE__*/ (0, import_jsx_runtime.jsx)("div", { children: !line_1.outputRuns.length ? firstOutputIndex !== -1 && index > firstOutputIndex ? /*#__PURE__*/ (0, import_jsx_runtime.jsx)("br", {}) : null : line_1.outputRuns.map(_temp2) }, index))
			})]
		});
		$[0] = className;
		$[1] = icons.code;
		$[2] = output;
		$[3] = showRaw;
		$[4] = style;
		$[5] = t1;
	} else t1 = $[5];
	return t1;
};
var kForeground = 0;
var kBackground = 1;
var OutputRun = (t0) => {
	const $ = (0, import_compiler_runtime.c)(5);
	const { run } = t0;
	let t1;
	if ($[0] !== run) {
		t1 = computeCSSProperties(run);
		$[0] = run;
		$[1] = t1;
	} else t1 = $[1];
	let t2;
	if ($[2] !== run.text || $[3] !== t1) {
		t2 = /*#__PURE__*/ (0, import_jsx_runtime.jsx)("span", {
			style: t1,
			children: run.text
		});
		$[2] = run.text;
		$[3] = t1;
		$[4] = t2;
	} else t2 = $[4];
	return t2;
};
var computeCSSProperties = (outputRun) => {
	return !outputRun.format ? {} : {
		...computeStyles(outputRun.format.styles || []),
		...computeForegroundBackgroundColor(kForeground, outputRun.format.foregroundColor),
		...computeForegroundBackgroundColor(kBackground, outputRun.format.backgroundColor)
	};
};
var computeStyles = (styles) => {
	let cssProperties = {};
	styles.forEach((style) => {
		switch (style) {
			case import_ansi_output.ANSIStyle.Bold:
				cssProperties = {
					...cssProperties,
					fontWeight: "bold"
				};
				break;
			case import_ansi_output.ANSIStyle.Dim:
				cssProperties = {
					...cssProperties,
					fontWeight: "lighter"
				};
				break;
			case import_ansi_output.ANSIStyle.Italic:
				cssProperties = {
					...cssProperties,
					fontStyle: "italic"
				};
				break;
			case import_ansi_output.ANSIStyle.Underlined:
				cssProperties = {
					...cssProperties,
					textDecorationLine: "underline",
					textDecorationStyle: "solid"
				};
				break;
			case import_ansi_output.ANSIStyle.SlowBlink:
				cssProperties = {
					...cssProperties,
					animation: "ansi-display-run-blink 1s linear infinite"
				};
				break;
			case import_ansi_output.ANSIStyle.RapidBlink:
				cssProperties = {
					...cssProperties,
					animation: "ansi-display-run-blink 0.5s linear infinite"
				};
				break;
			case import_ansi_output.ANSIStyle.Hidden:
				cssProperties = {
					...cssProperties,
					visibility: "hidden"
				};
				break;
			case import_ansi_output.ANSIStyle.CrossedOut:
				cssProperties = {
					...cssProperties,
					textDecorationLine: "line-through",
					textDecorationStyle: "solid"
				};
				break;
			case import_ansi_output.ANSIStyle.DoubleUnderlined: cssProperties = {
				...cssProperties,
				textDecorationLine: "underline",
				textDecorationStyle: "double"
			};
		}
	});
	return cssProperties;
};
var computeForegroundBackgroundColor = (colorType, color) => {
	switch (color) {
		case void 0: return {};
		case import_ansi_output.ANSIColor.Black:
		case import_ansi_output.ANSIColor.Red:
		case import_ansi_output.ANSIColor.Green:
		case import_ansi_output.ANSIColor.Yellow:
		case import_ansi_output.ANSIColor.Blue:
		case import_ansi_output.ANSIColor.Magenta:
		case import_ansi_output.ANSIColor.Cyan:
		case import_ansi_output.ANSIColor.White:
		case import_ansi_output.ANSIColor.BrightBlack:
		case import_ansi_output.ANSIColor.BrightRed:
		case import_ansi_output.ANSIColor.BrightGreen:
		case import_ansi_output.ANSIColor.BrightYellow:
		case import_ansi_output.ANSIColor.BrightBlue:
		case import_ansi_output.ANSIColor.BrightMagenta:
		case import_ansi_output.ANSIColor.BrightCyan:
		case import_ansi_output.ANSIColor.BrightWhite: if (colorType === kForeground) return { color: `var(--${color})` };
		else return { background: `var(--${color})` };
		default: if (colorType === kForeground) return { color };
		else return { background: color };
	}
};
function _temp(line_0) {
	return line_0.outputRuns.length > 0;
}
function _temp2(outputRun) {
	return /*#__PURE__*/ (0, import_jsx_runtime.jsx)(OutputRun, { run: outputRun }, outputRun.id);
}
//#endregion
export { RichANSIDisplay as default };

//# sourceMappingURL=AnsiDisplayRich.js.map