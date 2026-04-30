import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from parallax.compiler.provider import CompilerProvider
from parallax.compiler.anthropic_provider import AnthropicCompilerProvider
from parallax.shared.schemas import ContractSchema, RawMarketData


def _sample_market() -> RawMarketData:
    return RawMarketData(
        platform="polymarket",
        market_id="abc",
        title="Will X happen before Dec 31?",
        description="This market resolves YES if X happens before Dec 31.",
        resolution_criteria="Resolves YES if X; NO otherwise.",
        outcomes=["Yes", "No"],
        outcome_prices=[0.6, 0.4],
        deadline=datetime(2025, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        raw_payload={},
    )


def _sample_contract() -> ContractSchema:
    return ContractSchema(
        yes_conditions=["X happens before Dec 31"],
        no_conditions=["X does not happen before Dec 31"],
        exclusions=[],
        ambiguity_terms=[],
        counterexamples=[],
        compiler_confidence=0.9,
    )


class TestCompilerProviderABC:
    def test_is_abstract(self):
        """CompilerProvider cannot be instantiated directly."""
        with pytest.raises(TypeError):
            CompilerProvider()


class TestAnthropicCompilerProvider:
    def test_version_string(self):
        provider = AnthropicCompilerProvider(api_key="test")
        assert provider.version.startswith("anthropic-")

    @pytest.mark.anyio
    async def test_compile_returns_contract_schema(self):
        contract = _sample_contract()
        mock_response = MagicMock()
        mock_response.parsed_output = contract

        with patch(
            "parallax.compiler.anthropic_provider.anthropic.AsyncAnthropic"
        ) as MockClient:
            mock_client = MockClient.return_value
            mock_client.messages.parse = AsyncMock(return_value=mock_response)

            provider = AnthropicCompilerProvider(api_key="test")
            result = await provider.compile(_sample_market())

        assert isinstance(result, ContractSchema)
        assert result.compiler_confidence == 0.9
        assert result.yes_conditions == ["X happens before Dec 31"]

    @pytest.mark.anyio
    async def test_compile_passes_market_content(self):
        mock_response = MagicMock()
        mock_response.parsed_output = _sample_contract()

        with patch(
            "parallax.compiler.anthropic_provider.anthropic.AsyncAnthropic"
        ) as MockClient:
            mock_client = MockClient.return_value
            mock_client.messages.parse = AsyncMock(return_value=mock_response)

            provider = AnthropicCompilerProvider(api_key="test")
            await provider.compile(_sample_market())

        call_kwargs = mock_client.messages.parse.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        user_msg = call_kwargs["messages"][0]["content"]
        assert "Will X happen before Dec 31?" in user_msg
        assert "Resolves YES if X" in user_msg

    @pytest.mark.anyio
    async def test_compile_uses_cached_system_prompt(self):
        mock_response = MagicMock()
        mock_response.parsed_output = _sample_contract()

        with patch(
            "parallax.compiler.anthropic_provider.anthropic.AsyncAnthropic"
        ) as MockClient:
            mock_client = MockClient.return_value
            mock_client.messages.parse = AsyncMock(return_value=mock_response)

            provider = AnthropicCompilerProvider(api_key="test")
            await provider.compile(_sample_market())

        system = mock_client.messages.parse.call_args.kwargs["system"]
        assert isinstance(system, list)
        assert system[0]["cache_control"] == {"type": "ephemeral"}
