# MathVista: Evaluating Mathematical Reasoning in Visual Contexts

[MathVista](https://arxiv.org/pdf/2310.02255) to evaluate model performance in answering mathematics problems that have a visual component. Each problem has an associated image which is required to solve the problem. The dataset is made up of 6,141 questions from 28 existing multimodal datasets as well as 3 new datasets created for MathVista, where each dataset contains different styles of questions. There are both multiple-choice questions and free-form questions, where the free-form questions ask for a response in the form of an integer, floating-point number, or list.

## Execution
Here is an example from the dataset:

**Question:** The derivative of f(x) at x=2 is ____ that at x=5

**Choices:** "larger than", "equal to", "smaller than"

**Image:**

![Image for example question](example_image.png)

**Correct answer:** "equal to"

## Evaluation
For multiple choice questions the model is prompted to answer with a single letter answer, it is given the question, the image, and the choices and asked to answer. For free-form questions the model is given the question, the image, and told the format in which to give the answer and is asked to answer.

N.B. It is expected that the images required for solving the questions are available in a subdirectory called `images` from which the file `mathvista.py` is being run. The images can be downloaded from [HuggingFace](https://huggingface.co/datasets/AI4Math/MathVista) where it is available in a zipped format `images.zip` - it must be unzipped before being used.
