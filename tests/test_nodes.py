"""
Tests for step modules.
"""


class TestFetchAndProcessHistory:
    """Tests for fetch_and_process_history step."""

    def test_importable(self):
        from dango.steps.fetch_history import fetch_and_process_history

        assert fetch_and_process_history is not None

    def test_is_async(self):
        import asyncio

        from dango.steps.fetch_history import fetch_and_process_history

        assert asyncio.iscoroutinefunction(fetch_and_process_history)


class TestCallDiscordAgent:
    """Tests for call_discord_agent step."""

    def test_importable(self):
        from dango.steps.call_agent import call_discord_agent

        assert call_discord_agent is not None

    def test_is_async(self):
        import asyncio

        from dango.steps.call_agent import call_discord_agent

        assert asyncio.iscoroutinefunction(call_discord_agent)


class TestExtractAndRenderTables:
    """Tests for extract_and_render_tables step."""

    def test_importable(self):
        from dango.steps.table_steps import extract_and_render_tables

        assert extract_and_render_tables is not None

    def test_is_async(self):
        import asyncio

        from dango.steps.table_steps import extract_and_render_tables

        assert asyncio.iscoroutinefunction(extract_and_render_tables)

    def test_parse_table(self):
        from dango.steps.table_steps import _parse_table

        table_text = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = _parse_table(table_text)
        assert result["valid"] is True
        assert result["headers"] == ["A", "B"]
        assert result["rows"] == [["1", "2"]]

    def test_parse_table_invalid(self):
        from dango.steps.table_steps import _parse_table

        result = _parse_table("| A |\n|---|")
        assert result["valid"] is False


class TestSendDiscordResponse:
    """Tests for send_discord_response step."""

    def test_importable(self):
        from dango.steps.send_response import send_discord_response

        assert send_discord_response is not None

    def test_is_async(self):
        import asyncio

        from dango.steps.send_response import send_discord_response

        assert asyncio.iscoroutinefunction(send_discord_response)


class TestBuildInstructions:
    """Tests for build_instructions utility."""

    def test_disabled_returns_base(self):
        from dango.utils.build_instructions import build_instructions

        result = build_instructions(
            base_prompt="Base prompt",
            author_name="Alice",
            unique_users=set(),
            enable_contextual=False,
        )
        assert result == "Base prompt"

    def test_enabled_includes_author(self):
        from dango.utils.build_instructions import build_instructions

        result = build_instructions(
            base_prompt="Base prompt",
            author_name="Alice",
            unique_users=set(),
            enable_contextual=True,
        )
        assert "Alice" in result
        assert "Base prompt" in result


class TestCreateDiscordWorkflow:
    """Tests for create_discord_workflow factory."""

    def test_creates_workflow(self, monkeypatch):
        import dango.workflow as workflow_module

        # Building the agents needs FAST_MODEL; skip it to keep the test
        # env-independent.
        monkeypatch.setattr(workflow_module, "get_agents", lambda: None)

        wf = workflow_module.create_discord_workflow()
        assert wf is not None
        assert wf.name == "DiscordAIPipeline"
