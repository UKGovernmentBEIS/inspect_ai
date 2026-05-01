# inspect_ai.viewer – Inspect

## Viewer

### ViewerConfig

Top-level viewer configuration.

`scanner_result_view` keys are fnmatch-style glob patterns (`"*"`, `"audit_*"`, exact names). Pass a ScannerResultView to apply a single configuration to every scanner.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/a4257f7045c7e4a8915d9aff7af064ceb4bf2618/src/inspect_ai/viewer/_config.py#L58)

``` python
class ViewerConfig(BaseModel)
```

#### Attributes

`scanner_result_view` [ScannerResultView](../reference/inspect_ai.viewer.html.md#scannerresultview) \| dict\[str, [ScannerResultView](../reference/inspect_ai.viewer.html.md#scannerresultview)\]  
Glob-keyed map from scanner name pattern to its sidebar config. May also be a bare [ScannerResultView](../reference/inspect_ai.viewer.html.md#scannerresultview).

## Scanner Results

### ScannerResultView

How the scann results should render the results.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/a4257f7045c7e4a8915d9aff7af064ceb4bf2618/src/inspect_ai/viewer/_config.py#L43)

``` python
class ScannerResultView(BaseModel)
```

#### Attributes

`fields` list\[[ScannerResultField](../reference/inspect_ai.viewer.html.md#scannerresultfield) \| [MetadataField](../reference/inspect_ai.viewer.html.md#metadatafield) \| str\] \| None  
Ordered list of sections to render. List order is render order; `None` means fall back to the built-in default order.

`exclude_fields` list\[[ScannerResultField](../reference/inspect_ai.viewer.html.md#scannerresultfield) \| [MetadataField](../reference/inspect_ai.viewer.html.md#metadatafield) \| str\]  
Fields to suppress. For a [ScannerResultField](../reference/inspect_ai.viewer.html.md#scannerresultfield) entry, the matching section is removed from the resolved `fields` list (useful to subtract from the default order). For a [MetadataField](../reference/inspect_ai.viewer.html.md#metadatafield) entry, the key is additionally removed from the generic `metadata` section’s dump.

## Fields

### MetadataField

A metadata key promoted out of metadata into a top level value.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/a4257f7045c7e4a8915d9aff7af064ceb4bf2618/src/inspect_ai/viewer/_config.py#L28)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/a4257f7045c7e4a8915d9aff7af064ceb4bf2618/src/inspect_ai/viewer/_config.py#L6)

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
