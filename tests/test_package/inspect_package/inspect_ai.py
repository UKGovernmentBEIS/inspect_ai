from inspect_ai.model import modelapi


@modelapi(name="custom")
def custom():
    # delayed import allows us to only resolve the imports in
    # .modelapi.custom when the modelapi is referneced (helpful
    # if the modelapi provider has dependencies we don't want to
    # require unless the provider is actually used)
    from .modelapi.custom import CustomModelAPI

    return CustomModelAPI
