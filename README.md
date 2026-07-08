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

## Terminal Access

- Explicit commands:
  - `eva shell <command>`
  - `eva exec <command>`
- These run inside Eva's Docker container working directory, which defaults to `/app`.
- Explicit terminal commands are limited to the owner/admin command path.
- Normal AI replies can also call a `run_terminal_command` tool — unrestricted arbitrary shell (curl, ping, pipes, redirects) so Eva can check files, hit endpoints, or poke at the home network herself.

Relevant env vars:

```bash
TERMINAL_ENABLED=true
TERMINAL_AUTONOMOUS_ENABLED=true
TERMINAL_WORKDIR=/app
TERMINAL_SHELL=/bin/sh
TERMINAL_TIMEOUT_SECONDS=15
TERMINAL_MAX_OUTPUT_CHARS=6000
```

## Download Command

- `eva dl <url>`
- `eva download <url>`
- Supports any site `yt-dlp` can handle.
- Uses the current guild upload limit when available.
- In DMs, Eva falls back to a default 10 MiB upload limit.
- If the downloaded file is too large for Discord, the command fails with an error.

## Channel Memory

- Eva keeps separate local in-memory chat history per channel.
- `eva clear`
- Owner/admin only.
- Clears the current channel's in-memory conversation state.

## Quality checks

```bash
uv run lint
uv run tests
```
