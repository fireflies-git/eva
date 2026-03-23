# Eva

AI Assistant selfbot for Discord.

## Run

```bash
uv run eva
```

## Settings

```bash
uv run eva settings show
uv run eva settings set account-mode standalone
```

- `assistant`: owner/selfbot-style behavior, no planned follow-up splitting
- `standalone`: bot-account behavior, replies to all DMs and only to mentions/prefixes/replies in servers, with delayed follow-up splitting

## Runtime Helpers

CLI flags:

```bash
uv run eva --setup-env
uv run eva --show-logs --lines 120
uv run eva --show-env-path
uv run eva --tray  # Windows only
```

## Quality checks

```bash
uv run lint
uv run tests
```
