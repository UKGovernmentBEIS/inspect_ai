# MMMU: A Massive Multi-discipline Multimodal Understanding and Reasoning Benchmark for Expert AGI

[MMMU](https://arxiv.org/abs/2311.16502) is a benchmark for evaluating multi-modal models on college-level tasks across a variety of subjects. 11.5k problems are gathered across 30 subjects and image types. Around 93% of questions in the evaluation dataset are multiple-choice, with the remainder being open-ended. GPT-4o is reported to achieve 63-69% accuracy for MMMU.

## Execution
Here is an example from the dataset:
```
Question: The double-tiered columns allowed for all of the following EXCEPT (<image 1>)
Option:
A) barrel-vaulted roofing
B) decorative rhythm and repetition
C) a higher roof to make up for the short columns
D) the entrance of light and air into the hall
```
![alt text](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/benchmarks/mmmu/image.jpg?raw=true)

The model is required to choose the correct answer from the given options and attached image. In this case, the correct answer is A) barrel-vaulted roofing.

## Evaluation
All evaluation is zero shot. For multiple-choice questions, one question, four options and up to seven images are provided. For open-ended questions, the four options are omitted. [Prompts](https://github.com/MMMU-Benchmark/MMMU/blob/main/eval/configs/llava1.5.yaml) follow those used by the original authors. [Micro-averaged accuracy](https://github.com/MMMU-Benchmark/MMMU/blob/main/eval/utils/eval_utils.py#L245) is used in the original paper, while this implementation simply returns Inspect's accuracy metric for each of the multiple-choice and open-ended tasks.

## TODO
Implement micro-averaged accuracy (calculate average accuracy per subject, multiply by (number of samples / total samples), sum weighted accuracies). Although, for the validation set, all subjects have the same number of samples.

If [possible](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e12c1d274024db1761363aa4786a24b4426901b6/src/inspect_ai/_util/content.py#L14), test performance against Gemini and Claude models.
