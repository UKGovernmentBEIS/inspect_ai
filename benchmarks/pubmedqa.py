"""
PubMedQA: A Dataset for Biomedical Research Question Answering

Qiao Jin, Bhuwan Dhingra, Zhengping Liu, William W. Cohen, Xinghua Lu

https://arxiv.org/abs/1909.06146

PubMedQA is a novel biomedical question answering (QA) dataset collected from
PubMed abstracts. The task of PubMedQA is to answer research questions with
yes/no/maybe (e.g.: Do preoperative statins reduce atrial fibrillation after
coronary artery bypass grafting?) using the corresponding abstracts. PubMedQA
has 1k expert-annotated, 61.2k unlabeled and 211.3k artificially generated QA
instances.

Each PubMedQA instance is composed of
    (1) a question which is either an existing research article title or
        derived from one,
    (2) a context which is the corresponding abstract without its conclusion,
    (3) a long answer, which is the conclusion of the abstract and, presumably,
        answers the research question, and
    (4) a yes/no/maybe answer which summarizes the conclusion.

Homepage: https://pubmedqa.github.io/

```
@inproceedings{jin2019pubmedqa,
    title={PubMedQA: A Dataset for Biomedical Research Question Answering},
    author={Jin, Qiao and Dhingra, Bhuwan and Liu, Zhengping and Cohen, William and Lu, Xinghua},
    booktitle={Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing (EMNLP-IJCNLP)},
    pages={2567--2577},
    year={2019}
}
```

# eval pubmedqa validation set
# inspect eval pubmedqa.py
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import choice
from inspect_ai.solver import multiple_choice

"""
qiaojin/PubMedQA
Dataset structure:
{
    "21645374": {
        "QUESTION": "Do mitochondria play a role in remodelling lace plant leaves during programmed cell death?",
        "CONTEXTS": [
            "Programmed cell death (PCD) is the regulated death of cells within an organism. The lace plant (Aponogeton madagascariensis) produces perforations in its leaves through PCD. The leaves of the plant consist of a latticework of longitudinal and transverse veins enclosing areoles. PCD occurs in the cells at the center of these areoles and progresses outwards, stopping approximately five cells from the vasculature. The role of mitochondria during PCD has been recognized in animals; however, it has been less studied during PCD in plants.",
            "The following paper elucidates the role of mitochondrial dynamics during developmentally regulated PCD in vivo in A. madagascariensis. A single areole within a window stage leaf (PCD is occurring) was divided into three areas based on the progression of PCD; cells that will not undergo PCD (NPCD), cells in early stages of PCD (EPCD), and cells in late stages of PCD (LPCD). Window stage leaves were stained with the mitochondrial dye MitoTracker Red CMXRos and examined. Mitochondrial dynamics were delineated into four categories (M1-M4) based on characteristics including distribution, motility, and membrane potential (\u0394\u03a8m). A TUNEL assay showed fragmented nDNA in a gradient over these mitochondrial stages. Chloroplasts and transvacuolar strands were also examined using live cell imaging. The possible importance of mitochondrial permeability transition pore (PTP) formation during PCD was indirectly examined via in vivo cyclosporine A (CsA) treatment. This treatment resulted in lace plant leaves with a significantly lower number of perforations compared to controls, and that displayed mitochondrial dynamics similar to that of non-PCD cells."
        ],
        "LABELS": [
            "BACKGROUND",
            "RESULTS"
        ],
        "MESHES": [
            "Alismataceae",
            "Apoptosis",
            "Cell Differentiation",
            "Mitochondria",
            "Plant Leaves"
        ],
        "YEAR": "2011",
        "reasoning_required_pred": "yes",
        "reasoning_free_pred": "yes",
        "final_decision": "yes",
        "LONG_ANSWER": "Results depicted mitochondrial dynamics in vivo as PCD progresses within the lace plant, and highlight the correlation of this organelle with other organelles during developmental PCD. To the best of our knowledge, this is the first report of mitochondria and chloroplasts moving on transvacuolar strands to form a ring structure surrounding the nucleus during developmental PCD. Also, for the first time, we have shown the feasibility for the use of CsA in a whole plant system. Overall, our findings implicate the mitochondria as playing a critical and early role in developmentally regulated PCD in the lace plant."
    },
    ...
}
"""


TEMPLATE_FROM_PAPER = """
The following are multiple choice questions (with answers) about medical knowledge.

{{few_shot_examples}}

Answer the following question given the context (reply with one of the options):
**Context:** {{context}}

**Question:** {{question}}

{{answer_choices}}
**Answer:**(
"""

choices = {
    "yes": "A",
    "no": "B",
    "maybe": "C",
}


def record_to_sample(record) -> Sample:
    abstract = record['context']
    question = record["question"]
    return Sample(
        input=f"**Context:** {abstract}\n**Question:** {question}",
        target=choices[record["answer"][0].lower()],  # provided as e.g. ['yes']
        id=record["id"],
        choices=record["choices"],  # always ['yes, 'no', 'maybe']
    )


TEMPLATE = r"""
The following are multiple choice questions (with answers) about medical knowledge.

Answer the following question given the context.
The entire content of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of {letters}.

{question}

{choices}
""".strip()


"""
DatasetDict({
    train: Dataset({
        features: ['QUESTION', 'CONTEXTS', 'LABELS', 'MESHES', 'YEAR', 'reasoning_required_pred', 'reasoning_free_pred', 'final_decision', 'LONG_ANSWER'],
        num_rows: 450
    })
    validation: Dataset({
        features: ['QUESTION', 'CONTEXTS', 'LABELS', 'MESHES', 'YEAR', 'reasoning_required_pred', 'reasoning_free_pred', 'final_decision', 'LONG_ANSWER'],
        num_rows: 50
    })
    test: Dataset({
        features: ['QUESTION', 'CONTEXTS', 'LABELS', 'MESHES', 'YEAR', 'reasoning_required_pred', 'reasoning_free_pred', 'final_decision', 'LONG_ANSWER'],
        num_rows: 500
    })
})
"""


@task
def pubmedqa():
    dataset = hf_dataset(
        path="bigbio/pubmed_qa",
        # Note: Each of 10 folds has a different `train` and `validation` set,
        # but all 10 have the same `test` set.
        name="pubmed_qa_labeled_fold0_bigbio_qa",
        sample_fields=record_to_sample,
        trust=True,
        split="train",
        # split="test",
        # shuffle=True,
        limit=100,
    )

    return Task(
        dataset=dataset,
        plan=[multiple_choice(template=TEMPLATE)],
        scorer=choice(),
    )
