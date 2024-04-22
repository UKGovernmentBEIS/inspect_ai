from inspect_ai._util.registry import registry_info
from inspect_ai.solver import Plan, chain_of_thought, generate, plan


@plan(fancy=True)
def my_plan() -> Plan:
    return Plan(steps=[chain_of_thought(), generate()])


def test_plan_registration():
    plan = my_plan()
    assert registry_info(plan).name == "my_plan"


def test_plan_attribs():
    plan = my_plan()
    assert registry_info(plan).metadata["attribs"]["fancy"] is True
