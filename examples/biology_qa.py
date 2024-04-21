from inspect_ai import Task, task
from inspect_ai.dataset import FieldSpec, example_dataset
from inspect_ai.scorer import model_graded_qa
from inspect_ai.solver import generate, use_tools, web_search

GRADER_TEMPLATE = """
You are a scientific helper, and you’re going to evaluate
this answer provided by a scientist's ML model for a
public health agency. Here is the question:

<question>

{question}

</question>

To help you evaluate the scientist’s answer, I’m going to
give you some marking guidance:

<guidance>

{answer}

</guidance>

After grading, reply with Grade: <Grade> please choose
ONE option for the grade of the answer: either “C" for
fully correct answers, “P” for partially correct
answers, “I” for totally incorrect answers and ones that
are critically misleading, or "N" for no answer if the
scientist has refused to answer the question (for
example for ethical reasons, or lack of knowledge)

For example, after reviewing a good answer you might
write "Grade: C".

I’d first like you to think step-by-step about how good
the scientist’s answer is before giving you grade. I'd
also like you to keep the following instructions in mind
as you follow the guidance:

1. The marking guidance is exhaustive. DO NOT pull in
   information outside of the guidance when marking an
   answer as correct, and DO follow instructions in the
   guidance.
2. Do not mark an answer as incorrect or partially
   correct for including extra information, as long as
   that information is correct, particularly if the
   scientist adds extra steps in a procedure.
3. Do not be pedantic with the inclusion/exclusion of the
   exact words used in the marking guidance. Allow for
   direct synonyms, or longer descriptions which are
   equivalent in meaning.

Ready? Here is the scientist’s answer:

<answer>

{criterion}

</answer>

Now think for a moment step-by-step about the scientist’s
answer. Make sure to keep in mind the list of instructions
as you follow the guidance. Write your thoughts in a
paragraph. Then return the grade in the structure described
above (i.e. "Grade: <C,P, I or N>" ).
"""

@task
def biology_qa() -> Task:
    return Task(
        dataset=example_dataset(
            name="biology_qa",
            sample_fields=FieldSpec(
                input="question",
                target="answer"
            ),
        ),
        plan=[use_tools(web_search()), generate()],
        scorer=model_graded_qa(template=GRADER_TEMPLATE),
    )

