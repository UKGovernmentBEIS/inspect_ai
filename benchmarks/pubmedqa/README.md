# PubMedQA

Title: PubMedQA: A Dataset for Biomedical Research Question Answering
Authors: Qiao Jin, Bhuwan Dhingra, Zhengping Liu, William W. Cohen, Xinghua Lu

Abstract: https://arxiv.org/abs/1909.06146

Homepage: https://pubmedqa.github.io/

PubMedQA is a novel biomedical question answering (QA) dataset collected from
PubMed abstracts. The task of PubMedQA is to answer research questions with
yes/no/maybe (e.g.: Do preoperative statins reduce atrial fibrillation after
coronary artery bypass grafting?) using the corresponding abstracts. PubMedQA
has 1k expert-annotated, 61.2k unlabeled and 211.3k artificially generated QA
instances.

Each PubMedQA instance is composed of
1. a question which is either an existing research article title or
    derived from one, 
2. a context which is the corresponding abstract without its conclusion,
3. a long answer, which is the conclusion of the abstract and, presumably,
    answers the research question, and
4. a yes/no/maybe answer which summarizes the conclusion.

PubMedQA datasets comprise of 3 different subsets:
1. PubMedQA Labeled (PQA-L): A labeled PubMedQA subset comprises of 1k manually annotated yes/no/maybe QA data collected from PubMed articles.
2. PubMedQA Artificial (PQA-A): An artificially labelled PubMedQA subset comprises of 211.3k PubMed articles with automatically generated questions from the statement titles and yes/no answer labels generated using a simple heuristic. 
3. PubMedQA Unlabeled (PQA-U): An unlabeled PubMedQA subset comprises of 61.2k context-question pairs data collected from PubMed articles.

## Citation:
```bibtex
@inproceedings{jin2019pubmedqa,
    title={PubMedQA: A Dataset for Biomedical Research Question Answering},
    author={Jin, Qiao and Dhingra, Bhuwan and Liu, Zhengping and Cohen, William and Lu, Xinghua},
    booktitle={Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing (EMNLP-IJCNLP)},
    pages={2567--2577},
    year={2019}
}
```

## Implementation
The [original dataset](https://huggingface.co/datasets/qiaojin/PubMedQA) is available on HuggingFace.
A [lightly reshaped version](https://huggingface.co/datasets/bigbio/pubmed_qa) of the dataset was released by BioBio.
This implementation uses the BigBio version of the dataset, as the original version
incorrectly uses all 1000 labeled samples as the test set, which should in fact only be 500.
See [this GitHub issue](https://github.com/EleutherAI/lm-evaluation-harness/issues/886).

The BigBio release provides two versions of the dataset - "source" and "bigbio". 
The "source" dataset contains the original qiaojin version, but does not include
sample ids. The "bigbio" dataset contains a lightly reshaped version of the same
data, but with sample ids. The "bigbio" dataset is used in this implementation.

