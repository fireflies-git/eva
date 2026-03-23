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

## Quality checks

```bash
uv run lint
uv run test
```
