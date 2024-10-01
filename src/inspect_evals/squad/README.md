# SQuAD
Here, we implement the evaluation for the Stanford Question Answering Dataset (SQuAD) v2.0, which is currently formulated as a single task which adopts the built-in F1 and Exact Match scorers.

[SQuAD (v2.0)](https://arxiv.org/pdf/1806.03822) is a benchmark for testing machine reading comprehension and reasoning abilities, combining the 100,000+ answerable questions from the [SQuAD v1.1](https://arxiv.org/abs/1606.05250) dataset with 50,000+ unanswerable questions, written adversarially by crowdworkers to look similar to answerable ones.

To perform well, systems must not only answer questions when possible, providing an answer which matches between 1 to 3 of the target answers in response to a question based on a paragraph from a provided Wikipedia articles, but also determine when no answer is supported by the paragraph, despite plausibility, and abstain from answering. 

The questions are designed to vary lexically and syntactically from the provided paragraphs, and thus, answering them requires advanced reasoning capabilities.


## Execution

### Example 1
Here is an example from the dataset which presents an answerable question:
```
Context: Super Bowl 50 was an American football game to determine the champion of the National Football League (NFL) for the 2015 season. The American Football Conference (AFC) champion Denver Broncos defeated the National Football Conference (NFC) champion Carolina Panthers 24–10 to earn their third Super Bowl title. The game was played on February 7, 2016, at Levi's Stadium in the San Francisco Bay Area at Santa Clara, California. As this was the 50th Super Bowl, the league emphasized the "golden anniversary" with various gold-themed initiatives, as well as temporarily suspending the tradition of naming each Super Bowl game with Roman numerals (under which the game would have been known as "Super Bowl L"), so that the logo could prominently feature the Arabic numerals 50.

Question: If Roman numerals were used, what would Super Bowl 50 have been called?

Answer(s): [ Super Bowl L, L, Super Bowl L ]
```
The model is tasked to answer the question by referring to the context, potentially requiring mutliple-sentence reasoning.

### Example 2

Here is an example from the dataset which presents an unanswerable question:
```
Context: The Normans (Norman: Nourmands; French: Normands; Latin: Normanni) were the people who in the 10th and 11th centuries gave their name to Normandy, a region in France. They were descended from Norse ("Norman" comes from "Norseman") raiders and pirates from Denmark, Iceland and Norway who, under their leader Rollo, agreed to swear fealty to King Charles III of West Francia. Through generations of assimilation and mixing with the native Frankish and Roman-Gaulish populations, their descendants would gradually merge with the Carolingian-based cultures of West Francia. The distinct cultural and ethnic identity of the Normans emerged initially in the first half of the 10th century, and it continued to evolve over the succeeding centuries.

Question: Who did King Charles III swear fealty to?

Answer: [ ]
```
The model is tasked with determining that the question is not answerable.


## Evaluation
The model is prompted with the Wikipedia paragraph acting as the context, and the corresponding question. It is required to attempt to answer the question, only using the context provided and no outside information, and if it deems the question to be unanswerable, should abstain from answering by returning 'unanswerable'.


The prompt template takes inspiration from the following OpenAI examples:
- [fine_tuned_qa example](https://github.com/openai/openai-cookbook/blob/627a11cb2f2c7a174c42c724c2e8a9737f79e6e1/examples/fine-tuned_qa/ft_retrieval_augmented_generation_qdrant.ipynb)
- [unsolvable_questions example](https://github.com/openai/evals/blob/234bcde34b5951233681455faeb92baaaef97573/evals/registry/data/unsolvable_questions/convert.js)

Similarly to this [LM Evaluation Harness example](https://github.com/LZY-the-boys/lm-evaluation-harness-fast/blob/master/lm_eval/tasks/squad.py#L91C9-L91C22), if a question is unanswerable, the target is transformed from an empty array to the string 'unanswerable', to simplify comparison and use of the built-in scorers.

The evaluation performed, in particular the F1-score calculation logic, draws from the official SQuAD v2 [evaluation script](https://worksheets.codalab.org/rest/bundles/0x6b567e1cf2e041ec80d7098f031c5c9e/contents/blob/), as well as EleutherAI's lm-evaluation-harness for the [DROP benchmark](https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/tasks/drop/utils.py#L64C1-L73C40) and the [SuperGLUE benchmark](https://github.com/EleutherAI/lm-evaluation-harness/blob/ebe7226ebfb8d11a9fb8d6b53eb65891f895c633/lm_eval/tasks/super_glue/record/t5_utils.py).
