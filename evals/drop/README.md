# DROP: A Reading Comprehension Benchmark Requiring Discrete Reasoning Over Paragraphs

[DROP](https://arxiv.org/pdf/1903.00161) is a crowdsourced, adversarially-created, 96k reading comprehension benchmark, in which a system must resolve references in a question, perhaps to multiple input positions, and perform discrete operations over them.

## Execution
Here is an example from the dataset:
```python
Passage:  The Eagles began their season at Bank of America Stadium for a Week 1 duel with the Carolina Panthers.  Philadelphia trailed early in the first quarter as Panthers running back DeAngelo Williams ran 11 yards for a Carolina touchdown on their first drive.  The Eagles answered with a 49-yard field goal from kicker David Akers. In the second quarter, Philadelphia exploded with points as defensive end Victor Abiamiri returned a fumble 2 yards for a touchdown, wide receiver DeSean Jackson returned a punt 85 yards for a touchdown, and quarterback Donovan McNabb completed a 9-yard TD pass to tight end Brent Celek and a 4-yard touchdown pass to running back Brian Westbrook. Carolina ended the period with kicker John Kasay booting a 22-yard field goal. In the third quarter, the Eagles closed out their scoring with McNabb scoring on a 3-yard touchdown run.  However, he was hit late by several Carolina tacklers who cracked his ribs on the right side, knocking him out of the game. Kevin Kolb came in for McNabb and closed out the game for the victorious Eagles.

Question: How many yards was the longest scoring play of the first quarter?
```
The model is tasked to answer the question by referring to multiple parts in the passage.

## Evaluation
The prompts are based on OpenAI's [simple-evals](https://github.com/openai/simple-evals/blob/main/drop_eval.py#L261C13-L283C91) and the evaluation is performed based on the F1-score calculation logic implemented in EleutherAI's [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/tasks/drop/utils.py#L64C1-L73C40).
