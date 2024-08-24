## Benchmarks

This directory contains evals for several benchmarks. Datasets for evals are not embedded in the repository but are rather either downloaded either directly from their source URL or via Hugging Face datasets. To use Hugging Face datasets please install the datasets package with `pip install datasets`.

| Benchmark                                                                                     | Reference                            |                                      Code | Dataset      |
|-----------------------|-----------------|----------------:|-----------------|
| MMLU: Measuring Massive Multitask Language Understanding                                      | <https://arxiv.org/abs/2009.03300>   |                        [mmlu.py](mmlu.py) | Download     |
| MATH: Measuring Mathematical Problem Solving With the MATH Dataset                            | <https://arxiv.org/abs/2103.03874>   |          [mathematics.py](mathematics.py) | Download     |
| GPQA: A Graduate-Level Google-Proof Q&A Benchmark                                             | <https://arxiv.org/abs/2311.12022>   |                        [gpqa.py](gpqa.py) | Download     |
| ARC: AI2 Reasoning Challenge                                                                  | <https://arxiv.org/abs/1803.05457>   |                          [arc.py](arc.py) | Hugging Face |
| GSM8K: Training Verifiers to Solve Math Word Problems                                         | <https://arxiv.org/abs/2110.14168>   |                      [gsm8k.py](gsm8k.py) | Hugging Face |
| HellaSwag: Can a Machine Really Finish Your Sentence?                                         | <https://arxiv.org/abs/1905.07830>   |              [hellaswag.py](hellaswag.py) | Hugging Face |
| PIQA: Physical Interaction: Question Answering                                                | <https://arxiv.org/abs/1911.11641>   |                        [piqa.py](piqa.py) | Hugging Face |
| BoolQ: Exploring the Surprising Difficulty of Natural Yes/No Questions                        | <https://arxiv.org/abs/1905.10044>   |                      [boolq.py](boolq.py) | Hugging Face |
| TruthfulQA: Measuring How Models Mimic Human Falsehoods                                       | <https://arxiv.org/abs/2109.07958v2> |            [truthfulqa.py](truthfulqa.py) | Hugging Face |
| HumanEval: Evaluating Large Language Models Trained on Code                                   | <https://arxiv.org/pdf/2107.03374>   |    [humaneval.py](humaneval/humaneval.py) | Hugging Face |
| DROP: A Reading Comprehension Benchmark Requiring Discrete Reasoning Over Paragraphs          | <https://arxiv.org/pdf/1903.00161>   |                   [drop.py](drop/drop.py) | Hugging Face |
| WINOGRANDE: An Adversarial Winograd Schema Challenge at Scale                                 | <https://arxiv.org/pdf/1907.10641>   | [winogrande.py](winogrande/winogrande.py) | Hugging Face |
| RACE-H: A benchmark for testing reading comprehension and reasoning abilities of neural models. | <https://arxiv.org/abs/1704.04683>   |             [race-h.py](race-h/race-h.py) | Hugging Face |