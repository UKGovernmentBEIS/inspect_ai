# PubMedQA

A Dataset for Biomedical Research Question Answering

## Paper

Title: PubMedQA: A Dataset for Biomedical Research Question Answering

Authors: Qiao Jin, Bhuwan Dhingra, Zhengping Liu, William W. Cohen, Xinghua Lu

Abstract: https://arxiv.org/abs/1909.06146

Homepage: https://pubmedqa.github.io/

PubMedQA is a biomedical question answering (QA) dataset collected from
PubMed abstracts. The task of PubMedQA is to answer research questions with
yes/no/maybe (e.g.: Do preoperative statins reduce atrial fibrillation after
coronary artery bypass grafting?) using the corresponding abstracts. PubMedQA
has 1k expert-annotated, 61.2k unlabeled and 211.3k artificially generated QA
instances.

Each PubMedQA instance is composed of

1. a question which is either an existing research article title or derived from
   one,
2. a context which is the corresponding abstract without its conclusion,
3. a long answer, which is the conclusion of the abstract and, presumably,
   answers the research question, and
4. a yes/no/maybe answer which summarizes the conclusion.

PubMedQA datasets consist of 3 different subsets:

1. PubMedQA Labeled (PQA-L): A labeled PubMedQA subset consists of 1k manually
   annotated yes/no/maybe QA data collected from PubMed articles.
2. PubMedQA Artificial (PQA-A): An artificially labelled PubMedQA subset
   consists of 211.3k PubMed articles with automatically generated questions
   from the statement titles and yes/no answer labels generated using a simple
   heuristic.
3. PubMedQA Unlabeled (PQA-U): An unlabeled PubMedQA subset consists of 61.2k
   context-question pairs data collected from PubMed articles.

### Citation:

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

The [original dataset](https://huggingface.co/datasets/qiaojin/PubMedQA) is
available on HuggingFace.
A [lightly reshaped version](https://huggingface.co/datasets/bigbio/pubmed_qa)
of the dataset was released by BioBio. This implementation uses the BigBio
release of the dataset, as the original release incorrectly uses all 1000
labeled samples as the test set, which should in fact only be 500.
See [this GitHub issue](https://github.com/EleutherAI/lm-evaluation-harness/issues/886).

The BigBio release actually provides both versions of the dataset - "source" and
"bigbio_qa". The "source" subsets contain the original qiaojin version, but do
not include sample ids. The "bigbio_qa" subsets contain the reshaped version of
the same data, but with sample ids included. The "bigbio_qa" version of the
labeled test set is used in this implementation. The following subsets are
available, with their respective splits:

- `'pubmed_qa_labeled_fold{i}_[source|bigbio_qa]' for i in {0..9}`: Each of
  these 10 cross-validation folds takes the 1000 samples from PubMedQA
  Labeled  (PQA-L) and splits them into the same 500 samples for the test set,
  and different sets of 450 and 50 samples from the remaining 500 for the
  training and validation sets, respectively.
    - 'test': 500 samples, common across all folds. **This is the test set used
      for the benchmark.**
    - 'train': 450 samples
    - 'validation': 50 samples
- `'pubmed_qa_artificial_[source|bigbio_qa]'`: PubMedQA Artificial (PQA-A)
    - 'train': 200,000 samples
    - 'validation': 11,269 samples
- `'pubmed_qa_unlabeled_[source|bigbio_qa]'`: PubMedQA Unlabeled (PQA-U)
    - 'train': 61,249 samples

## Execution
Here is an example from the dataset (cropped for brevity):

```
Context: Gallbladder carcinoma is characterized by delayed diagnosis, 
ineffective treatment and poor prognosis. ... 

Question: Is external palliative radiotherapy for gallbladder carcinoma effective?

A) yes
B) no
C) maybe
```

## Evaluation
The model is prompted with an abstract and a question. The model is required to
answer the question with a yes, no, or maybe. The standard `multiple_choice`
solver is used with a prompt template based on the
default `MultipleChoice.SINGLE_ANSWER`, which allows using the in-built `choice`
scorer for evaluation.
 