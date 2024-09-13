## Evals

This directory contains Inspect eval implementations for a variety of papers and benchmarks. Datasets for evals are not embedded in the repository but are rather downloaded either directly from their source URL or via Hugging Face datasets. To use Hugging Face datasets please install the datasets package with `pip install datasets`.

| Benchmark                                                                                       | Reference                            |                                                  Code | Dataset      |
|-----------------------------|--------------|--------------:|--------------|
| MMLU: Measuring Massive Multitask Language Understanding                                        | <https://arxiv.org/abs/2009.03300>   |                                    [mmlu.py](mmlu/mmlu.py) | Download     |
| MMLU-Pro: A More Robust and Challenging Multi-Task Language Understanding Benchmark             | <https://arxiv.org/abs/2406.01574>   |                   [mmlu_pro.py](mmlu_pro/mmlu_pro.py) | HuggingFace  |
| MATH: Measuring Mathematical Problem Solving With the MATH Dataset                              | <https://arxiv.org/abs/2103.03874>   |          [mathematics.py](mathematics/mathematics.py) | Download     |
| GPQA: A Graduate-Level Google-Proof Q&A Benchmark                                               | <https://arxiv.org/abs/2311.12022>   |                                    [gpqa.py](gpqa/gpqa.py) | Download     |
| ARC: AI2 Reasoning Challenge                                                                    | <https://arxiv.org/abs/1803.05457>   |                                      [arc.py](arc/arc.py) | Hugging Face |
| GSM8K: Training Verifiers to Solve Math Word Problems                                           | <https://arxiv.org/abs/2110.14168>   |                                  [gsm8k.py](gsm8k/gsm8k.py) | Hugging Face |
| HellaSwag: Can a Machine Really Finish Your Sentence?                                           | <https://arxiv.org/abs/1905.07830>   |                          [hellaswag.py](hellaswag/hellaswag.py) | Hugging Face |
| PIQA: Physical Interaction: Question Answering                                                  | <https://arxiv.org/abs/1911.11641>   |                                    [piqa.py](piqa/piqa.py) | Hugging Face |
| BoolQ: Exploring the Surprising Difficulty of Natural Yes/No Questions                          | <https://arxiv.org/abs/1905.10044>   |                                  [boolq.py](boolq/boolq.py) | Hugging Face |
| TruthfulQA: Measuring How Models Mimic Human Falsehoods                                         | <https://arxiv.org/abs/2109.07958v2> |                        [truthfulqa.py](truthfulqa/truthfulqa.py) | Hugging Face |
| HumanEval: Evaluating Large Language Models Trained on Code                                     | <https://arxiv.org/abs/2107.03374>   |                [humaneval.py](humaneval/humaneval.py) | Hugging Face |
| DROP: A Reading Comprehension Benchmark Requiring Discrete Reasoning Over Paragraphs            | <https://arxiv.org/abs/1903.00161>   |                               [drop.py](drop/drop.py) | Hugging Face |
| WINOGRANDE: An Adversarial Winograd Schema Challenge at Scale                                   | <https://arxiv.org/abs/1907.10641>   |             [winogrande.py](winogrande/winogrande.py) | Hugging Face |
| RACE-H: A benchmark for testing reading comprehension and reasoning abilities of neural models. | <https://arxiv.org/abs/1704.04683>   |                         [race-h.py](race-h/race-h.py) | Hugging Face |
| MMMU: A Massive Multi-discipline Multimodal Understanding and Reasoning Benchmark.              | <https://arxiv.org/abs/2311.16502>   |                               [mmmu.py](mmmu/mmmu.py) | Hugging Face |
| CommonsenseQA: A Question Answering Challenge Targeting Commonsense Knowledge                   | <https://arxiv.org/abs/1811.00937> | [commonsense_qa.py](commonsense_qa/commonsense_qa.py) | Hugging Face |
| XSTest: A benchmark for identifying exaggerated safety behaviours in LLM's                      | <https://arxiv.org/abs/2308.01263>   |                         [xstest.py](xstest/xstest.py) | Hugging Face |
| MathVista: Evaluating Mathematical Reasoning in Visual Contexts                                 | <https://arxiv.org/abs/2310.02255>   |                [mathvista.py](mathvista/mathvista.py) | Hugging Face |
| SQuAD: A Reading Comprehension Benchmark requiring reasoning over Wikipedia articles | <https://arxiv.org/pdf/1806.03822>   |             [squad.py](squad/squad.py) | Hugging Face |
| IFEval: Instruction-Following Evaluation for Large Language Models                 | <https://arxiv.org/abs/2311.07911> |   [ifeval.py](ifeval/ifeval.py) | Hugging Face |
| AGIEval: A Human-Centric Benchmark for Evaluating Foundation Models                 | <https://arxiv.org/abs/2304.06364> |   [agieval_en.py](agieval/agieval_en.py) | Download |
| PubMedQA: A Dataset for Biomedical Research Question Answering                                  | <https://arxiv.org/abs/1909.06146>   |                   [pubmedqa.py](pubmedqa/pubmedqa.py) | Hugging Face
| MBPP: Mostly Basic Python Problems                                                              | <https://arxiv.org/abs/2108.07732>   |   [mbpp.py](mbpp/mbpp.py) | Hugging Face |
