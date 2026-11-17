# Eva

AI Assistant selfbot for Discord.

## Run

```bash
uv run eva
```

## DeepSeek

Eva defaults to the DeepSeek API:

```bash
API_KEY=your-deepseek-key
API_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-v4-flash
```

`SPLIT_MODEL_NAME` and `TOS_MODEL_NAME` remain optional and default to
`MODEL_NAME`. GLM-5.3-Flash is still supported by pointing `API_BASE_URL` and
`MODEL_NAME` at Z.AI; the GLM reasoning settings (`MODEL_REASONING_EFFORT`,
`MODEL_CLEAR_THINKING`) only apply to `glm-5.3-flash*` models.

Run the provider smoke check without connecting to Discord:

```bash
uv run eva model-check
uv run eva model-check --video-url https://example.invalid/video.mp4
```

The check validates text, tools, reasoning parsing, image data, and file data.
Video input is checked only when `--video-url` is supplied. Discord media is
ephemeral and bounded to 8 attachments and 50 MiB total; images are under 5 MiB
and 6000×6000 pixels, while files and videos are capped at 20 MiB each. Images
and files use data URLs. Videos use validated provider-fetched URLs.

## Settings

```bash
uv run eva settings show
uv run eva settings set account-mode standalone
```

- `assistant`: owner/selfbot-style behavior, no planned follow-up splitting
- `standalone`: bot-account behavior, replies to all non-empty messages in 1:1 DMs, but requires `eva`, the bot username, a Discord mention, or a tracked reply in servers and group chats, with delayed follow-up splitting

### DeepSeek Vision

To let Eva read Discord image attachments, configure a vision-capable DeepSeek model:

```env
API_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-v4-flash-vision-exp
```

Eva exposes an `inspect_attached_images` tool to its normal agent/tool loop whenever a current,
replied-to, or recent cached image is available. The initial model request stays text-only; Eva
decides independently whether visual evidence is needed and only then runs a separate DeepSeek
vision pass. Explicit wording such as `eva what does this say?` can help, but no special
`describe`/`read` command is required, and ordinary text requests with attachments do not send
image bytes to DeepSeek.

Eva keeps recent image bytes only in bounded, channel-scoped memory. The cache is cleared by
`eva clear` and is lost when Eva restarts; image bytes are never written to `STATE_DIR` or local
chat history. Supported inline images are JPEG, PNG, GIF, and WebP; Eva keeps no more than four
images per message and enforces bounded per-image, request, and process-memory limits.

Friend request application commands (admin-only):

- `eva review [@user]` accepts a pending request and opens a named application group with the reviewing admin; without a mention, it uses the most recent request
- `eva accept [@user]` accepts a request without opening an application group (or confirms it is already accepted); without a mention, it uses the most recent request
- `eva deny [@user]` denies a request; without a mention, it uses the most recent request
- In an admin DM with a pending request, reply `y` to accept, `r` to accept and open an application group, or `n` to deny
- Accepting an applicant from their named application group removes the other participants and makes Eva leave, deleting the closed group
- The existing `eva friends accept|deny @user` commands remain supported
- Pending requests are persisted under `STATE_DIR` and admins are notified again after Eva restarts

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
- These run inside Eva's dedicated terminal working directory, which defaults to `/tmp/eva-terminal`.
- Explicit terminal commands are limited to the owner/admin command path.
- Normal AI replies can also call a policy-controlled `run_terminal_command` tool.
- Autonomous calls run without an interactive approval prompt for the owner and configured admins.
- The default runner is read-only, uses a dedicated temporary work directory, strips secrets, blocks network access, and rejects shell chaining, redirects, installers, and writes.

Relevant env vars:

```bash
TERMINAL_ENABLED=true
TERMINAL_AUTONOMOUS_ENABLED=true
TERMINAL_WORKDIR=/tmp/eva-terminal
TERMINAL_SHELL=/bin/sh
TERMINAL_TIMEOUT_SECONDS=15
TERMINAL_MAX_OUTPUT_CHARS=6000
AUTONOMOUS_TOOL_SCOPE=owner_admin
TERMINAL_COMMAND_MODE=allowlist
TERMINAL_NETWORK_ENABLED=false
OUTBOUND_ALLOWED_HOSTS=
```

`OUTBOUND_ALLOWED_HOSTS` is optional. When set, every configured API, image,
download, browser, and documentation request must use one of the exact
hostnames listed there.

## CAPTCHA Solving

NopeCHA is enabled by default for Discord CAPTCHA challenges. The API key is
optional; leave `NOPECHA_API_KEY` empty for keyless solving or set it for a
keyed account. Set `NOPECHA_ENABLED=false` to disable the integration. CAPTCHA
challenge data is sent to NopeCHA when a challenge occurs.

## Download Command

- `eva dl <url>`
- `eva download <url>`
- Supports any site `yt-dlp` can handle.
- Available to any user who can send Eva a message.
- Uses the current guild upload limit when available.
- In DMs, Eva falls back to a default 10 MiB upload limit.
- If the downloaded file is too large for Discord, the command fails with an error.

## Yuri Command

- `eva yuri`
- Sends one random image from the local `yuri.db` SQLite database as a Discord attachment.
- The database is read from `STATE_DIR/yuri.db` (the default is `./yuri.db`) and is kept out of version control.
- The command does not use the whitelist: DMs and group chats may receive NSFW rows, while server channels receive only rows marked SFW.
- NSFW rows are labeled and uploaded as Discord spoiler attachments.

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
