# Batchers



```code
          ┌──────────────────┐
          │     Batcher      │
          └─────────┬────────┘
                    │
          ┌─────────┴────────┐
          │                  │
┌─────────┴────────┐    ┌────┴───────────────┐
│ AnthropicBatcher │    │     FileBatcher    │
└──────────────────┘    └─────┬──────┬───────┘
                              │      │
                              │      └─────────────────┐
                              │                        │
                    ┌─────────┴───────────┐    ┌───────┴──────────┐
                    │     GoogleBatcher   │    │  OpenAIBatcher   │
                    └─────────────────────┘    └───────┬──────────┘
                                                       │
                                               ┌───────┴──────────┐
                                               │ TogetherBatcher  │
                                               └──────────────────┘
```


## Overview
The batcher classes provide a unified interface for batching requests to different model providers. The inheritance structure is as follows:

- Batcher: Abstract base class for all batchers.
- AnthropicBatcher: Handles inline batching for Anthropic models (requests are sent directly, not via files).
- FileBatcher: Base class for batchers that use file-based batching (requests are written to files and processed in bulk).
  - GoogleBatcher: Implements file-based batching for Google models.
  - OpenAIBatcher: Implements file-based batching for OpenAI models.
    - TogetherBatcher: Specialization for Together AI, inherits from OpenAIBatcher.

## File-based vs Inline Approaches
- File-based batchers (GoogleBatcher, OpenAIBatcher, TogetherBatcher):
  - Requests are accumulated and written to files.
  - The provider processes the file in bulk, returning results for all requests at once.
  - Useful for providers that support batch file processing and can handle large numbers of requests efficiently.
- Inline batcher (AnthropicBatcher):
  - Requests are sent directly via API calls, without intermediate files.
  - Suitable for providers that do not support file-based batching or where immediate response is preferred.
