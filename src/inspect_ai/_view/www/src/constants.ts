// Model constants
export const kModelNone = "none/none";

// Workspace tab constants
export const kLogViewSamplesTabId = "samples";
export const kLogViewJsonTabId = "json";
export const kLogViewInfoTabId = "info";
export const kLogViewModelsTabId = "models";
export const kLogViewTaskTabId = "task";

export const kWorkspaceTabs = [
  kLogViewSamplesTabId,
  kLogViewJsonTabId,
  kLogViewInfoTabId,
  kLogViewModelsTabId,
  kLogViewTaskTabId,
];

// Sample tab constants
export const kSampleMessagesTabId = `messages`;
export const kSampleTranscriptTabId = `transcript`;
export const kSampleScoringTabId = `scoring`;
export const kSampleMetdataTabId = `metadata`;
export const kSampleErrorTabId = `error`;
export const kSampleErrorRetriesTabId = `retry-errors`;
export const kSampleJsonTabId = `json`;

export const kSampleTabIds = [
  kSampleMessagesTabId,
  kSampleTranscriptTabId,
  kSampleScoringTabId,
  kSampleMetdataTabId,
  kSampleErrorTabId,
  kSampleErrorRetriesTabId,
  kSampleJsonTabId,
];

// Scoring constants
export const kScoreTypePassFail = "passfail";
export const kScoreTypeCategorical = "categorical";
export const kScoreTypeNumeric = "numeric";
export const kScoreTypeOther = "other";
export const kScoreTypeObject = "object";
export const kScoreTypeBoolean = "boolean";

// Sorting constants
export const kSampleAscVal = "sample-asc";
export const kSampleDescVal = "sample-desc";
export const kEpochAscVal = "epoch-asc";
export const kEpochDescVal = "epoch-desc";
export const kScoreAscVal = "score-asc";
export const kScoreDescVal = "score-desc";
export const kDefaultSort = kSampleAscVal;
