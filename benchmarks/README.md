## Benchmarks

This directory contains evals for several benchmarks, including:

| Benchmark                                                          | Reference                          |                             Code |
|------------------------|------------------------|-----------------------:|
| MMLU: Measuring Massive Multitask Language Understanding           | <https://arxiv.org/abs/2009.03300> |               [mmlu.py](mmlu.py) |
| MATH: Measuring Mathematical Problem Solving With the MATH Dataset | <https://arxiv.org/abs/2103.03874> | [mathematics.py](mathematics.py) |
| GPQA: A Graduate-Level Google-Proof Q&A Benchmark                  | <https://arxiv.org/abs/2311.12022> |               [gpqa.py](gpqa.py) |
| ARC: AI2 Reasoning Challenge                                       | <https://arxiv.org/abs/1803.05457> |                 [arc.py](arc.py) |
| GSM8K: Training Verifiers to Solve Math Word Problems              | <https://arxiv.org/abs/2110.14168> |             [gsm8k.py](gsm8k.py) |
| HellaSwag: Can a Machine Really Finish Your Sentence?              | <https://arxiv.org/abs/1905.07830> |     [hellaswag.py](hellaswag.py) |

The datasets for ARC, GSM8K, and HellaSwag are read from Hugging Face, so require the installation of the **datasets** package:

``` bash
$ pip install datasets
```

The datasets for MMLU and MATH are stored using [Git-LFS](https://git-lfs.com/). Once you have downloaded and installed LFS, switch to the repo source directory and run the following commands to sync the data from LFS:

``` bash
$ cd inspect_ai
$ git lfs fetch --all
$ git lfs pull
```