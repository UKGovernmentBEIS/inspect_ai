from inspect_ai.solver import Plan, chain_of_thought, generate, plan


@plan
def cot() -> Plan:
    return Plan([chain_of_thought(), generate()])
