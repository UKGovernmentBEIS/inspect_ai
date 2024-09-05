# QuAC: A Reading Comprehension Benchmark Requiring Discrete Reasoning Over Dialogs

[QuAC](https://arxiv.org/abs/1808.07036) is a large-scale dataset for Question Answering in Context that contains 14K information-seeking QA dialogs (100K total questions). The dialogs involve two crowd workers: a student who poses questions to learn about a hidden Wikipedia text, and a teacher who answers by providing short excerpts from the text.

## Execution

Here is an example from the dataset:

```
Section: Augusto Pinochet : Intellectual life...

STUDENT: Was he known for being intelligent?
TEACHER: ,→ No, Pinochet was publicly known as a man with a lack of culture.

STUDENT: why did people feel that way?
TEACHER: ,→ reinforced by the fact that he also portrayed himself as a common man

STUDENT: did he have any hobbies?
TEACHER: ,→ Yes, Before wresting power from Allende, Pinochet had written two books.

STUDENT: what is the name of a book written by him?
TEACHER: ,→ Geopolitica (1968) and Campana de Tarapaca (1972).
```

The model is tasked to answer the questions by referring to the dialog history and the hidden passage.

## Evaluation

The evaluation is performed using word-level F1 score, implemented similarly to SQuAD. We are only evaluating on the last question instead of iterating over all questions in the text. 


## TODOS:
- I'm only evaluating on the last question instead of iterating over all questions in the text. 
- Can we skip current state in a custom scorer easily? If not I need to create a workaround or implement that in the core library
- I haven't implemented the Human Equivalence Score for questions (HEQ-Q) and for dialogs (HEQ-D) reported in the paper. However, it seems like other implementations don't have done that either ([GPT-3 Paper](https://paperswithcode.com/paper/language-models-are-few-shot-learners), and [LLama 3 Paper](https://paperswithcode.com/paper/the-llama-3-herd-of-models))
- The paper introduces two new metrics: Human Equivalence Score for questions (HEQ-Q) and for dialogs (HEQ-D), which are not implemented here. 
- I'm evaluating only on the last question of the full text (not the previous questions in the text)
