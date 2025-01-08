from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import system_message
from inspect_ai.solver._basic_agent import basic_agent
from inspect_ai.tool import computer

SYSTEM_MESSAGE = """
Before each step, please clearly explain your intent for performing a tool action: "I expect tool command X to ...".

After each step, carefully evaluate the resulting screenshot to see if the command achieved the right outcome.

Explicitly show your thinking: "I have evaluated step X..." If not correct, try again. Only when
you confirm a step was executed correctly should you move on to the next one.

Note that launching applications from the bottom task bar requires a single left click.
"""


@task
def computer_task():
    return Task(
        dataset=[
            Sample(
                input="Use the computer tool to find the contents of the file '/tmp/flag.txt'. When you've found it, report its contents.",
                target="Frunobulax",
                files={"/tmp/flag.txt": "flag.txt"},
            ),
            Sample(
                input="Use the computer tool and open the spreadsheet '/tmp/moonWeight.ods`. Enter your weight as 156 lbs. Report the result from cell B2. Important: If the 'Tip of the Day' dialog appears, you'll need to close it before proceeding. Important: You may need to install a spreadsheet using a command like 'sudo apt-get install -y libreoffice'.",
                target="26",
                files={"/tmp/moonWeight.ods": "moonWeight.ods"},
            ),
            Sample(
                input="Use the computer tool to launch a terminal. Type 'Trudging across the tundra. Mile after Mile.' into the terminal. Important: Make sure that the terminal window is active before typing. When you are done, please use the submit tool to record the result of hitting enter in the terminal after entering that text.",
                target="bash: Trudging: command not found",
            ),
            Sample(
                input="Use the computer tool to launch a calculator. Calculate 123 x 456. Report the result.",
                target="56088",
            ),
            Sample(
                input='Draw a smiley face with a paint program. When you are done, submit("Art is in the eye of the beholder"). Important: In XPaint, you need to create a new canvas before you can draw.',
                target="Art is in the eye of the beholder",
            ),
            # Sample(
            #     input='Draw a smiley face with a paint program.  The face should be a solid yellow circle on a light gray background with solid black circles for eyes. The mouth should be a curved black line. When you are done, submit("Art is in the eye of the beholder"). Important: In XPaint, you need to create a new canvas before you can draw. Also, in XPaint, the toolbar contains the following tools on each row. 1. Pencil, Dynamic Pencil, Dot Pencil 2. Brush, Spray, Smear 3. Segment, Polygonal Line, Arc 4. Arrowhead, Text, Erase 5. Box, Filled Box, Box Region 6. Oval, Filled Oval, Oval Region 7. Freehand Shape, Filled Freehand Shape, Freehand Shape Region 8. Polygon, Filled Polygon, Polygon Region 9. Spline Curve, Filled Spline Curve, Spline Curve Region 10. Fill, Gradient Fill, Fractal Fill',
            #     target='Art is in the eye of the beholder',
            # ),
        ],
        solver=basic_agent(
            init=system_message(SYSTEM_MESSAGE),
            tools=[computer()],
            max_messages=100,
        ),
        scorer=includes(),
        sandbox="docker",
    )
