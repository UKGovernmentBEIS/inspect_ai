import { Value2 } from "../../../../@types/log";
import { ScoreDescriptor } from "../types";
import { booleanScoreDescriptor } from "./BooleanScoreDescriptor";
import { categoricalScoreDescriptor } from "./CategoricalScoreDescriptor";
import { numericScoreDescriptor } from "./NumericScoreDescriptor";
import { objectScoreDescriptor } from "./ObjectScoreDescriptor";
import { otherScoreDescriptor } from "./OtherScoreDescriptor";
import { passFailScoreDescriptor } from "./PassFailScoreDescriptor";

type ScorerTypes = string | number | boolean | object;
interface ScoreCategorizer {
  describe: (
    values: Value2[],
    types?: ScorerTypes[],
  ) => ScoreDescriptor | undefined;
}

export const getScoreDescriptorForValues = (
  uniqScoreValues: Value2[],
  uniqScoreTypes: ScorerTypes[],
): ScoreDescriptor | undefined => {
  for (const categorizer of scoreCategorizers) {
    const scoreDescriptor = categorizer.describe(
      uniqScoreValues,
      uniqScoreTypes,
    );
    if (scoreDescriptor) {
      return scoreDescriptor;
    }
  }
};

const scoreCategorizers: ScoreCategorizer[] = [
  {
    describe: (_values: Value2[], types?: ScorerTypes[]) => {
      if (types && types.length === 1 && types[0] === "boolean") {
        return booleanScoreDescriptor();
      }
    },
  },
  {
    describe: (values: Value2[], _types?: ScorerTypes[]) => {
      if (
        values.length === 2 &&
        values.every((val) => {
          return val === 1 || val === 0;
        })
      ) {
        return numericScoreDescriptor(values);
      }
    },
  },
  {
    describe: (values: Value2[], types?: ScorerTypes[]) => {
      if (
        types &&
        types[0] === "string" &&
        types.length === 1 &&
        values.length < 5 &&
        !values.find((val) => {
          return val !== "I" && val !== "C" && val !== "P" && val !== "N";
        })
      ) {
        return passFailScoreDescriptor(values);
      }
    },
  },
  {
    describe: (values: Value2[], types?: ScorerTypes[]) => {
      if (
        values.length < 10 &&
        types &&
        types.length === 1 &&
        types[0] === "string"
      ) {
        return categoricalScoreDescriptor(values);
      }
    },
  },
  {
    describe: (values: Value2[], types?: ScorerTypes[]) => {
      if (types && types.length !== 0 && types[0] === "number") {
        return numericScoreDescriptor(values);
      }
    },
  },
  {
    describe: (values: Value2[], types?: ScorerTypes[]) => {
      if (types && types.length !== 0 && types[0] === "object") {
        return objectScoreDescriptor(values);
      }
    },
  },
  {
    describe: (_values: Value2[], _types?: ScorerTypes[]) => {
      return otherScoreDescriptor();
    },
  },
];
