import logging

from inspect_ai._util.constants import PKG_NAME
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import Model, ModelAPI
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo


def test_is_rate_limit_deprecation(caplog):
    # class which implements deprecated api
    class TestAPI(ModelAPI):
        def __init__(self) -> None:
            super().__init__("model")

        async def generate(
            self,
            input: list[ChatMessage],
            tools: list[ToolInfo],
            tool_choice: ToolChoice,
            config: GenerateConfig,
        ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
            return ModelOutput.from_content("model", "foo")

        def is_rate_limit(self, ex: BaseException) -> bool:
            return True

    # add our logging handler to the caplog handler
    logger = logging.getLogger(PKG_NAME)
    logger.propagate = True
    try:
        # confirm that the deprecated api is called and triggers a warning
        model = Model(TestAPI(), GenerateConfig())
        assert model.should_retry(Exception()) is True
        assert any(
            "deprecated is_rate_limit() method" in record.message
            for record in caplog.records
        ), "Expected warning not found in logs"
    finally:
        logger.propagate = False
