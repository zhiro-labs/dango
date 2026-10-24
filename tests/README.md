# Test Suite

Tests for the Dango Discord AI agent. Everything runs offline: Discord, the
attachment CDN and the model are replaced by in-memory fakes.

## Running Tests

```bash
uv run pytest -q
```

Run one file or one test:

```bash
uv run pytest tests/test_flows.py -v
uv run pytest tests/test_flows.py -k deep_round_trip -v
```

Tests are not run by CI yet (the GitHub workflows only build the Docker
image and the docs), so run them before committing.

## End-to-end flows

`test_flows.py` drives whole flows with real code everywhere except the
outside world:

- **Messages**: a message goes through `ChatCog.on_message` and the real Agno
  workflow (fetch history → call agent → render tables → send) to a reply in
  a fake channel. The model is a `ScriptedModel`: queue replies with
  `model.reply(...)` / `model.fail(...)` and inspect what it was sent via
  `model.calls`.
- **Setup**: the web setup wizard and dashboard write `data/config.yaml` and
  `config/runtime.yml`, `app_config.inject_config_to_env()` turns them into
  env vars, and the bot built from that env answers messages.

Each test runs in its own temp working directory with a clean environment.
To write a new flow test, use the `make_world` fixture:

```python
def test_something(make_world):
    w = make_world({"DEEP_MODEL": "google:gemini-2.5-pro"})  # extra env
    w.model.reply("Hello!")
    sent = w.say(w.alice, "hi", mention_bot=True)     # messages the bot sent
    assert sent[0].content == "Hello!"
    assert w.model.last.input[-1].content == "Alice: @Dango hi"
```

`fake_discord.py` holds the fakes (guild, members, text/DM channels,
messages, slash-command interactions, CDN). Files the bot sends are stored in
the fake CDN, so later history reads download them back as on Discord.

## Test Files

| File | Covers |
|---|---|
| `test_flows.py` | End-to-end message and setup flows |
| `test_call_agent.py` | The LLM step: models, tools, routing, trimming, retry, fallback, error replies |
| `test_agent_errors.py` | Classifying provider errors |
| `test_slash_commands.py` | `/deep` and `/skill` |
| `test_message_batching.py` | Merging rapid messages (virtual clock) |
| `test_media.py` | Image and sticker downloads from history |
| `test_runtime_config.py` | `runtime.yml` writing and escaping |
| `test_runtime_web.py` | `runtime.yml` shared by the dashboard and the bot |
| `test_web_security.py` | Dashboard Host/Origin guard |
| `test_web_escaping.py` | HTML escaping in dashboard fragments |
| `test_extensions.py` | Custom commands and tools (`custom/*.py`) |
| `test_nodes.py`, `test_imports.py`, `test_utils.py` | Smaller unit and import checks |
