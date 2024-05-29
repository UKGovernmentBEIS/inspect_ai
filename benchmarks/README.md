## Benchmarks

This directory contains evals for several benchmarks. Datasets for evals are not embedded in the repository but are rather stored using either Git-LFS or Hugging Face (see below for instructions on the additional requirements for reading datasets from these sources).

| Benchmark                                                              | Reference                          |                             Code | Dataset      |
|------------------------------------------------------------------------|------------------------------------|---------------------------------:|--------------|
| MMLU: Measuring Massive Multitask Language Understanding               | <https://arxiv.org/abs/2009.03300> |               [mmlu.py](mmlu.py) | Git-LFS      |
| MATH: Measuring Mathematical Problem Solving With the MATH Dataset     | <https://arxiv.org/abs/2103.03874> | [mathematics.py](mathematics.py) | Git-LFS      |
| GPQA: A Graduate-Level Google-Proof Q&A Benchmark                      | <https://arxiv.org/abs/2311.12022> |               [gpqa.py](gpqa.py) | Hugging Face |
| ARC: AI2 Reasoning Challenge                                           | <https://arxiv.org/abs/1803.05457> |                 [arc.py](arc.py) | Hugging Face |
| GSM8K: Training Verifiers to Solve Math Word Problems                  | <https://arxiv.org/abs/2110.14168> |             [gsm8k.py](gsm8k.py) | Hugging Face |
| HellaSwag: Can a Machine Really Finish Your Sentence?                  | <https://arxiv.org/abs/1905.07830> |     [hellaswag.py](hellaswag.py) | Hugging Face |
| PIQA: Physical Interaction: Question Answering                         | <https://arxiv.org/abs/1911.11641> |               [piqa.py](piqa.py) | Hugging Face |
| BoolQ: Exploring the Surprising Difficulty of Natural Yes/No Questions | <https://arxiv.org/abs/1905.10044> |             [boolq.py](boolq.py) | Hugging Face |

### Git-LFS Datasets

To use these datasets, first download and install [Git-LFS](https://git-lfs.com/). Once you have done this, switch to the repo source directory and run the following commands to sync the data from LFS:

``` bash
$ cd inspect_ai
$ git lfs fetch --all
$ git lfs pull
```

### Hugging Face Datasets

To use these datasets you need to install the **datasets** package as follows:

``` bash
$ pip install datasets
```

