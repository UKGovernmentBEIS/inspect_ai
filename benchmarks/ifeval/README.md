# IFEval

[IFEval](https://arxiv.org/pdf/2311.07911) is a benchmark to evaluate a model's performance on synthesizing programs from docstrings. This implementation uses an installable package from a [fork](https://github.com/josejg/instruction_following_eval) of the official implementation.

Before starting, please install the requirements under the [`requirements.txt`](requirements.txt) file.

## Execution
Here is an example prompt from the dataset:
```
Write a 300+ word summary of the wikipedia page "https://en.wikipedia.org/wiki/Raymond_III,_Count_of_Tripoli". Do not use any commas and highlight at least 3 sections that has titles in markdown format, for example *highlighted section part 1*, *highlighted section part 2*, *highlighted section part 3*.
```
The model then completes a simple generation task to complete the sequence.

## Evaluation
Once a generation is completed, the sequence is tested to evaluate the model's instruction following performance. There are a total of 25 verifiable instructions which can be further explored in the paper.

The example prompt above comes accompanied with three verifiable instructions, though this number varies depending on the data point. These are `["punctuation:no_comma", "detectable_format:number_highlighted_sections", "length_constraints:number_words"]`.

The evaluation then measures accuracy across prompt-level and instruction-level hierarchies as well as a strict and loose accuracy criteria. We define these terms more concretely below:

### Strict Accuracy
For a given response and a single instruction, this is simply 
```math
\text{is\_followed}(\text{resp}, \text{inst}) = \begin{cases} 
\text{True,} & \text{if instruction is followed.} \\
\text{False,} & \text{otherwise.}
\end{cases}
```

### Loose Accuracy
In this case, we define it using
```math
\text{is\_followed}_{\text{loose}}(\text{resp}, \text{inst}) = \text{Any}\left(\text{is\_followed}(\text{transform}_t(\text{resp}), \text{inst}) \text{ for } t = 1, 2, \ldots\right)
```

Here, there are a few transformations defined for the input response:

1. Remove commonly seen font modifiers in the markdown syntax, especially `*` and `**`.
2. Remove the first line of the response, so that we skip intros like “Sure, here it is:”.
3. Remove the last line of the response, so that we skip outros like “Hope it helps.”.

We take the powerset of these transformations (including the identity transformation) to have a total of eight transformations that we apply to the input response.

### Prompt-level
Per input response, we will only have a single boolean output evaluating the accuracy (both in the case of strict and loose accuracy).

### Instruction-level
This one enumerates over the instructions as opposed the input responses. Continuing from our running example, the output for the `["punctuation:no_comma", "detectable_format:number_highlighted_sections", "length_constraints:number_words"]` instruction set would be `[True, True, True]` if all the instructions pass. The accuracy is then calculated over all instructions and the entire dataset.

## Final Accuracy
This is simply an average of prompt-level-strict, prompt-level-loose, instruction-level-strict, instruction-level-loose.
