# inspect_ai.viewer – Inspect

## Viewer

### ViewerConfig

Top-level viewer configuration.

`scanner_result_view` keys are fnmatch-style glob patterns (`"*"`, `"audit_*"`, exact names). Pass a ScannerResultView to apply a single configuration to every scanner.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/a8c7311381ac881c9bdbc9c28818349a4d8af9fd/src/inspect_ai/viewer/_config.py#L80)

``` python
class ViewerConfig(BaseModel)
```

#### Attributes

`scanner_result_view` [ScannerResultView](../reference/inspect_ai.viewer.html.md#scannerresultview) \| dict\[str, [ScannerResultView](../reference/inspect_ai.viewer.html.md#scannerresultview)\]  
Glob-keyed map from scanner name pattern to its sidebar config. May also be a bare [ScannerResultView](../reference/inspect_ai.viewer.html.md#scannerresultview).

`sample_score_view` [SampleScoreView](../reference/inspect_ai.viewer.html.md#samplescoreview) \| None  
Defaults for the sample-header score panel. Honoured only when the user has not explicitly overridden the view or sort in their browser.

## Scanner Results

### ScannerResultView

How the scann results should render the results.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/a8c7311381ac881c9bdbc9c28818349a4d8af9fd/src/inspect_ai/viewer/_config.py#L43)

``` python
class ScannerResultView(BaseModel)
```

#### Attributes

`fields` list\[[ScannerResultField](../reference/inspect_ai.viewer.html.md#scannerresultfield) \| [MetadataField](../reference/inspect_ai.viewer.html.md#metadatafield) \| str\] \| None  
Ordered list of sections to render. List order is render order; `None` means fall back to the built-in default order.

`exclude_fields` list\[[ScannerResultField](../reference/inspect_ai.viewer.html.md#scannerresultfield) \| [MetadataField](../reference/inspect_ai.viewer.html.md#metadatafield) \| str\]  
Fields to suppress. For a [ScannerResultField](../reference/inspect_ai.viewer.html.md#scannerresultfield) entry, the matching section is removed from the resolved `fields` list (useful to subtract from the default order). For a [MetadataField](../reference/inspect_ai.viewer.html.md#metadatafield) entry, the key is additionally removed from the generic `metadata` section’s dump.

## Sample Score View

### SampleScoreView

How the sample-header score panel should render when there are 3 or more scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/a8c7311381ac881c9bdbc9c28818349a4d8af9fd/src/inspect_ai/viewer/_config.py#L69)

``` python
class SampleScoreView(BaseModel)
```

#### Attributes

`view` Literal\['chips', 'grid'\] \| None  
Default rendering mode. `chips` = wrapping pills; `grid` = sortable table. When None, the viewer picks based on score count.

`sort` [SampleScoreViewSort](../reference/inspect_ai.viewer.html.md#samplescoreviewsort) \| None  
Default sort. When None, scores render in their natural order.

### SampleScoreViewSort

Default sort applied to the sample-header score panel.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/a8c7311381ac881c9bdbc9c28818349a4d8af9fd/src/inspect_ai/viewer/_config.py#L58)

``` python
class SampleScoreViewSort(BaseModel)
```

#### Attributes

`column` Literal\['name', 'value'\] \| None  
Column to sort by. `name` = scorer name; `value` = score value. `None` means no sort (display order).

`dir` Literal\['asc', 'desc'\]  
Sort direction.

## Fields

### MetadataField

A metadata key promoted out of metadata into a top level value.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/a8c7311381ac881c9bdbc9c28818349a4d8af9fd/src/inspect_ai/viewer/_config.py#L28)

``` python
class MetadataField(BaseModel)
```

#### Attributes

`key` str  
The `metadata[key]` entry to promote into its own section.

`label` str \| None  
Override the section header text. Defaults to `key` when unset.

`collapsed` bool  
Whether the field should be collapsed by default.

### ScannerResultField

A built-in scanner-result section (e.g. `value`, `explanation`).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/a8c7311381ac881c9bdbc9c28818349a4d8af9fd/src/inspect_ai/viewer/_config.py#L6)

``` python
class ScannerResultField(BaseModel)
```

#### Attributes

`name` Literal\['explanation', 'label', 'value', 'validation', 'answer', 'metadata'\]  
Which built-in section to render.

`label` str \| None  
Override the section header text (e.g. `"Explanation" → "Rationale"`).

`collapsed` bool  
Whether the field should be collapsed by default.
