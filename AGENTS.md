# AGENTS.md

This file is the repo-specific operating guide for future code generation and maintenance in Eva.

The goal is not generic Python cleanliness. The goal is to keep this codebase easy to extend without
breaking trigger behavior, AI routing, search behavior, typing, or prompt composition.

## Core Quality Bar

Every meaningful change should keep the repo passing:

```bash
uv run lint
uv run tests
uv run pytest -q
uv run pyright
```

`ruff` and `pyright` are complementary here:
- `ruff` keeps style, imports, and common bug patterns clean
- `pyright` is the type gate

Do not treat one as a replacement for the other.

## Clean Code Style

This repo prefers boring, explicit, readable code over clever code.

The standard to aim for:
- small functions with one job
- early returns over deep nesting
- explicit names over abbreviated names
- helpers for repeated logic
- thin orchestration, thick domain helpers
- behavior encoded in Python, not hidden in prompt wording

### Prefer small focused helpers

If a function is doing parsing, authorization, formatting, and state mutation all at once,
split it.

Good:

```python
def _parse_target_id(*, content: str, parts: list[str]) -> int | None:
    mention_match = _MENTION_RE.search(content)
    if mention_match is not None:
        return int(mention_match.group(1))
    if len(parts) >= 3 and parts[2].isdigit():
        return int(parts[2])
    return None
```

Bad:

```python
async def handle_command(...) -> bool:
    ...
    if mention_match is not None:
        ...
    elif len(parts) >= 3 and parts[2].isdigit():
        ...
    else:
        ...
    if subcommand == "add":
        ...
    else:
        ...
```

### Prefer early returns

Reduce indentation whenever possible.

Good:

```python
if not decision.should_generate:
    return None

if not prompt:
    raise ImageClientError("Image prompt is empty")
```

Bad:

```python
if decision.should_generate:
    if prompt:
        ...
```

### Keep orchestration readable

Top-level flow functions should read like a checklist.

Good `handlers.py` / `orchestrator.py` style:
- gather inputs
- call one helper per step
- handle failures clearly
- persist only after success

Bad:
- inline parsing
- inline formatting
- inline permission logic
- inline HTTP-specific behavior

### Name things by responsibility

Prefer names that tell the reader what layer a function belongs to.

Good:
- `parse_trigger`
- `handle_whitelist_command`
- `fetch_reply_context`
- `deliver_owner_response`
- `build_image_generation_prompt`

Avoid vague names like:
- `process`
- `handle`
- `run`
- `do_stuff`

unless the surrounding type already makes the role obvious.

### Keep branches symmetrical

When two branches do similar work, keep the structure aligned.

Good:
- owner flow and whitelisted-user flow both gather context, call the orchestrator, deliver, then persist

Bad:
- one branch updates history before delivery
- the other updates history after delivery
- one branch chunks responses in a helper and the other hand-rolls it inline

### Prefer explicit data shaping at boundaries

When crossing a boundary between layers, normalize data once.

Examples:
- API JSON -> dataclass / typed object in client code
- Discord trigger text -> `TriggerDecision`
- AI reply -> `ReplyOutput`

Do not leak raw dicts or partially normalized payloads deep into the app.

### Extract repeated strings and tiny policy knobs when shared

If the same small limit or status string matters in multiple places, move it to
`src/eva/constants.py`.

Good:

```python
MAX_IMAGE_URLS = 4
MAX_SEARCH_RESULTS = 5
```

Bad:

```python
for image in results.images[:4]:
    ...
```

But keep large prompt bodies and one-off regexes local to their modules unless they are reused.

### Write comments sparingly

Comments should explain non-obvious intent, not restate code.

Good:

```python
# If upload/download failed, fall back to URLs so Discord can still render embeds.
```

Bad:

```python
# Loop through images
for image in images:
```

### Make invalid states obvious

If something should not happen, fail clearly near the boundary where it becomes invalid.

Examples:
- malformed image API payload -> reject in `src/eva/images/client.py`
- empty image prompt -> reject in `src/eva/images/service.py`
- invalid YES/NO model output -> parse to `None`, then handle explicitly

Do not silently reinterpret obviously bad states unless that fallback is an intentional product decision.

### Prefer consistency over local cleverness

If there is already an established pattern in the repo, follow it even if another pattern would also work.

Examples:
- use prompt helpers under `src/eva/prompts/*`
- use protocols at service boundaries
- use targeted unit tests with small fakes
- use markdown-friendly output shaping in the orchestrator

New code should feel like it belongs next to the surrounding file.

## Common Commands

Use the repo commands that actually exist today:

```bash
uv run eva
uv run lint
uv run tests
uv run pyright
uv run build
```

Notes:
- For a fresh environment with dev tooling, run `uv sync --group dev`.
- `uv run tests` is the packaged test command from `pyproject.toml`.
- `uv run pytest -q` is still useful for targeted or ad hoc test runs.
- Keep docs, workflows, and scripts aligned. If a command name changes in `pyproject.toml`,
  update `README.md`, `AGENTS.md`, and CI in the same change.

## Repo Shape

The repo is intentionally split by responsibility:

- `src/eva/cli.py`
  Thin command wrappers for lint, test, and build entry points.
- `src/eva/logging.py`
  Logging setup only.
- `src/eva/app.py`
  Composition root only. Wire dependencies here. Do not put behavior here.
- `src/eva/config.py`
  Environment loading, parsing, validation, and `Settings`.
- `src/eva/constants.py`
  Shared code-level constants and tuning knobs.
- `src/eva/discord/*`
  Discord-facing behavior, split by concern:
  - `client.py`: Discord client/event wiring only
  - `handlers.py`: orchestration facade only
  - `triggers.py`: prefix / mention / tracked-reply trigger decisions
  - `commands.py`: whitelist command parsing and authorization
  - `context.py`: Discord read-side context fetches
  - `delivery.py`: Discord write-side send/edit/reply behavior
  - `formatting.py`: Discord output chunking / loading text
  - `code_attachments.py`: extract fenced code blocks into Discord file attachments
- `src/eva/ai/*`
  AI transport, orchestration, response shaping, moderation/search decision parsing.
- `src/eva/search/*`
  Search detection, query rewriting, search execution, and result normalization.
- `src/eva/images/*`
  Image-generation detection, image API transport, response validation, and asset handling.
- `src/eva/prompts/*`
  Prompt text and prompt composition only, including capabilities/limitations guidance.
- `src/eva/state/*`
  Lightweight persistence/in-memory stores.
- `tests/unit/*`
  Unit-first tests using stubs/fakes, not full integration scaffolding.

Keep file roles sharp. Avoid “convenience” code that blurs module boundaries.

## Where Code Belongs

### Put behavior in the owning layer

- Command-line entry points for lint/tests/build:
  `src/eva/cli.py`
- Logging configuration:
  `src/eva/logging.py`
- Trigger parsing and tracked-reply detection:
  `src/eva/discord/triggers.py`
- Discord client event registration and handoff to the handler:
  `src/eva/discord/client.py`
- Whitelist command parsing and admin checks:
  `src/eva/discord/commands.py`
- Channel history reads and reply-context fetches:
  `src/eva/discord/context.py`
- Send/edit/reply behavior and delivery result handling:
  `src/eva/discord/delivery.py`
- Code block extraction into file attachments:
  `src/eva/discord/code_attachments.py`
- Top-level Discord flow orchestration only:
  `src/eva/discord/handlers.py`
- Prompt wording, tone, security rules, search-response format:
  `src/eva/prompts/*`
- Capability and limitation prompt text:
  `src/eva/prompts/capabilities.py`
- Search-vs-normal routing and moderation sequencing:
  `src/eva/ai/orchestrator.py`
- Model payload construction and output shaping:
  `src/eva/ai/respond.py`
- Search execution and result fetching:
  `src/eva/search/service.py`
- Search query rewriting:
  `src/eva/search/query_builder.py`
- Search detection, search rewrite, and search API handling:
  `src/eva/search/*`
- Image detection, image API validation, and image asset download handling:
  `src/eva/images/*`

### Keep `app.py` thin

`src/eva/app.py` should stay a wiring file:
- construct clients/services/stores
- pass them into the handler
- start/stop async resources

Do not add business logic or trigger logic there.

### Keep `discord/client.py` thin

`src/eva/discord/client.py` should stay focused on Discord client setup:
- create the Discord client
- register event handlers
- log connection state
- hand message events off to `SelfbotMessageHandler`

Do not add authorization, trigger parsing, or reply-generation logic there.

### Keep `cli.py` as command wrappers

`src/eva/cli.py` should stay a thin command shim:
- translate script entry points into subprocess calls
- preserve passthrough args
- exit with the underlying command status

Do not add application business logic there.

### Keep `handlers.py` as the orchestration facade

`src/eva/discord/handlers.py` should coordinate the flow, not own every detail.

Good responsibilities for `handlers.py`:
- authorization gate
- calling whitelist command handling
- calling trigger parsing
- calling context fetch helpers
- invoking reply generation
- deciding when to persist history / tracked message IDs

Move detailed logic out when it belongs elsewhere:
- trigger syntax rules -> `triggers.py`
- command parsing / admin checks -> `commands.py`
- Discord read-side fetches -> `context.py`
- Discord write-side delivery -> `delivery.py`
- chunk formatting -> `formatting.py`
- Discord event wiring -> `client.py`

## Constants vs Config

### Put things in `src/eva/constants.py` when they are:

- reused across modules
- small numeric limits
- small shared status strings/marks
- internal tuning knobs likely to change over time

Good examples:
- token caps
- search context window sizes
- default history/context counts
- Discord message limits
- loading messages

### Keep things local when they are module-specific

Do **not** dump these into `constants.py`:
- large prompt bodies
- regexes only used in one module
- one-off parsing helpers
- config validation bounds that only matter in one file

### Keep env/config behavior in `src/eva/config.py`

If a value should be user-configurable via `.env` or `Settings`, it belongs in `config.py` even if it
has a constant default backing it.

Rule of thumb:
- internal tuning knob -> `constants.py`
- environment-driven behavior -> `config.py`

## Typing Rules

### Prefer protocols over concrete classes at service boundaries

If a caller only needs a method contract, annotate the dependency with a `Protocol`, not a concrete
implementation.

Follow existing patterns like:
- `ChatCompletionClient` in `src/eva/ai/client.py`
- small protocols in `src/eva/ai/orchestrator.py`

This keeps tests easy to write and avoids pyright friction with fakes.

### Prefer `Sequence[...]` for read-only collections

If a function only reads from a collection, annotate it as `Sequence[...]`, not `list[...]`.

This repo already uses `Sequence[ChatMessage]` in several places to avoid pyright invariance issues.

### Preserve `TypedDict` shapes

`ChatMessage` is a `TypedDict` in `src/eva/ai/schemas.py`.

When building message arrays, annotate them explicitly:

```python
messages: list[ChatMessage] = [...]
```

Do not let inference collapse them into `list[dict[str, str]]`.

### Avoid broad `Any` unless there is no cleaner option

Use small stubs, protocols, or `cast(...)` in tests before falling back to loose typing.

## Discord Layer Rules

Keep the Discord layer split by responsibility. Do not collapse the extracted modules back into one file.

### Read/write boundaries matter

- Discord read-side operations belong in `src/eva/discord/context.py`
- Discord write-side operations belong in `src/eva/discord/delivery.py`
- Flow coordination belongs in `src/eva/discord/handlers.py`

If a change only affects how we fetch context, keep it in `context.py`.
If a change only affects how we send/edit/reply, keep it in `delivery.py`.

### Trigger policy lives in `triggers.py`

Do not spread trigger rules across prompts, app wiring, or search logic.

### Preserve the trigger order

Keep the current flow in this order:

1. sender authorization
2. whitelist/admin command handling
3. reply-trigger detection
4. prefix/mention parsing
5. reply generation

Changing the order can create privilege leaks or make command text fall through into the AI path.

### `parse_trigger()` is the single source of truth

If you add new trigger syntaxes:
- add them in `parse_trigger()`
- add tests in `tests/unit/test_triggering.py`

Do not add ad hoc `startswith(...)` checks elsewhere in the handler or command code.

### Keep authorization separate from trigger syntax

A valid trigger format should never imply permission.

Always keep the owner/whitelist gate as an early return in `on_message()`.

### Admin IDs bypass the whitelist gate

The current top-level message gate treats hardcoded admins as allowed users even if they are not in
`whitelist.json`.

That means:
- owner -> always allowed
- `ALLOWED_ADMIN_IDS` -> allowed to chat and use commands without whitelist membership
- whitelisted users -> allowed
- everyone else -> ignored

If you change admin handling, verify both:
- admin users can still send normal prompts like `eva hello` without being added to the whitelist
- whitelist command permissions still behave the same

### Reply chaining is stateful

Reply chaining depends on `TrackedMessageStore`.

If you change how Eva emits messages, verify reply-triggering still works for:
- owner replies
- whitelisted user replies

### Reply triggers must not invoke image generation

Tracked replies are allowed to continue normal text conversations, but they should not trigger the
image-generation path.

Current rule:
- explicit prefix or leading mention -> image generation may run
- tracked reply trigger -> image generation is disabled, text flow continues normally

If you change trigger semantics, preserve this rule unless image replies are intentionally being redesigned.

### Mention behavior should stay narrow

Only a **leading** mention of the owner account should count as a trigger.

Do not make “mentioned anywhere in the message” a trigger unless you explicitly want more false positives.

### Whitelist command handling belongs in `commands.py`

Keep whitelist command parsing and authorization in `src/eva/discord/commands.py`.

Do not re-implement whitelist parsing inline in `handlers.py`.
If command behavior changes, update `tests/unit/test_whitelist_commands.py`.

### Delivery success should drive persistence

`TrackedMessageStore` and `ChannelHistoryStore` updates should happen only after the primary response was
actually delivered.

Preserve the current rule:
- successful primary delivery -> track IDs and append exchange
- failed primary delivery -> do not pretend the exchange happened

If delivery semantics change, update:
- `tests/unit/test_delivery.py`
- `tests/unit/test_handler_delivery.py`

## Whitelist and Admin Rules

Whitelist behavior is sensitive. Keep it explicit and testable.

If you touch whitelist behavior, document and preserve:
- who can reach the command parser
- who can `list`
- who can `add/remove`
- whether admin IDs are hardcoded or config-driven
- whether admin IDs bypass general chat access as well as whitelist mutation checks

Avoid adding more hardcoded privilege rules inline in the handler. Keep them inside `commands.py` unless
admin behavior is explicitly being redesigned.

## Current Cleanup Targets

These are worth fixing when touching the relevant area. They are real repo issues, not generic style nits.

- `src/eva/discord/commands.py` still contains hardcoded admin IDs (`ALLOWED_ADMIN_IDS`).
  That is acceptable short-term, but it should move to config if admin behavior changes again.
- `src/eva/state/tracked_messages.py` is still unbounded in-memory state.
  Be careful about adding more long-lived runtime memory without an eviction or persistence plan.
- `src/eva/state/whitelist.py` can still diverge between in-memory state and disk state if persistence fails.
  If whitelist durability matters more, make that explicit in the store contract instead of hiding it.

## Prompt Rules

### Keep prompt composition centralized

All system prompt assembly should stay in `src/eva/prompts/builder.py`.

If you add a new prompt section:
- create a focused prompt helper/module
- compose it in `builder.py`

Do not concatenate ad hoc prompt fragments deep inside runtime code.

### Keep prompt concerns separate

- persona/tone -> `src/eva/prompts/persona.py`
- formatting rules -> `src/eva/prompts/formatting.py`
- runtime context -> `src/eva/prompts/context.py`
- security/jailbreak rules -> `src/eva/prompts/security.py`
- search answer formatting -> `src/eva/prompts/search.py`
- image detection and image prompt helpers -> `src/eva/prompts/image.py`

Do not mix these concerns together unless the behavior is intentionally coupled.

### Prompt changes are high leverage

Small wording changes in `persona.py` or `builder.py` can materially change behavior across the whole app.

If you tune tone:
- keep the style consistent
- avoid repeated filler habits
- do not bury behavior-only fixes in prompt text when the real logic belongs in Python

### Image prompt rules belong in `prompts/image.py`

Do not keep image detector system prompts or image prompt-construction templates inline inside
`src/eva/images/detector.py` or `src/eva/images/service.py`.

Keep these separate:
- image detection prompt text
- image-generation prompt construction for referential follow-ups
- Python logic deciding whether reply context is required

## AI, Search, and Image Rules

### Keep transport clients dumb

`OpenAICompatibleClient` and `SerperClient` should mostly do:
- HTTP
- response validation
- normalization

Do **not** move routing, policy, prompt logic, or fallback behavior into transport clients.

The same applies to `src/eva/images/client.py`:
- do HTTP
- normalize the payload
- reject malformed or non-generated image responses
- do not move trigger policy or Discord formatting there

### Keep orchestration explicit

`src/eva/ai/orchestrator.py` owns:
- search vs normal reply routing
- moderation sequencing
- fail-open vs fail-closed behavior at the orchestration level
- final image reply text shaping for Discord
- code-block extraction (after TOS check, before reply return)

If you change fallback behavior, do it deliberately and update tests.

### Parse binary model outputs strictly

Any model call that is supposed to return YES/NO should use strict parsing.

Do not use substring checks like:

```python
"YES" in response.upper()
```

Use `src/eva/ai/parsing.py` and preserve the `bool | None` contract for ambiguous outputs.

### Current fallback policy matters

Today:
- search failures fail closed to a warning message
- moderation model failures fail open by returning `False`
- image API failures fail closed to a warning message
- image download failures fall back to URL-only image results when the payload still looks valid

Treat those as product decisions, not incidental implementation details.

### Search remains a separate mode

Search-grounded answer rules belong in the search prompt and search services.

Do not blend search-specific formatting policy into the general persona prompt.

### Image generation is its own mode with real provider quirks

Image generation should remain separate from both normal chat and search.

Keep these responsibilities distinct:
- `src/eva/images/detector.py`
  decides whether the user explicitly asked for an image
- `src/eva/images/service.py`
  builds the final generation prompt and downloads generated assets
- `src/eva/images/client.py`
  validates whether `/images` really returned generated media
- `src/eva/ai/orchestrator.py`
  decides how to present successful image output in Discord

### `/images` responses must be validated, not trusted blindly

Real upstream behavior is inconsistent.

Observed behavior from live requests:
- successful generated results usually return:
  - `answer` like `Media generated: '...'`
  - `images[0].source == "seedream-router"`
  - `images[0].generation_model == "seedream"`
  - `images[0].prompt == null`
  - `download_url` may be `null`
- some conversational prompts can return HTTP `200` with `image_generation: true` but only web/youtube
  search-style image results and a text answer instead of real generated media

Because of that:
- do not assume `HTTP 200` means “good generated image”
- do not assume `image_generation: true` means the images are valid generated assets
- validate generated image payloads in `src/eva/images/client.py`
- reject non-generated-looking image arrays before they reach Discord delivery logic

### Use `answer` as the primary image description

Do not rely on `images[0].prompt` for user-facing output.

Observed live behavior:
- `answer` is the stable place where the generated description appears
- `images[0].prompt` is often `null`

Current Discord output should be derived from `answer`, with the canned
`Media generated: '...'` wrapper normalized into a blockquote-style description.

### `download_url` is optional

When handling generated images:
- use `download_url or url`
- do not assume a dedicated download URL exists
- preserve graceful fallback when only direct asset URLs are available

### Keep the detector conservative and explicit

The upstream `/images` endpoint can misroute soft conversational requests like:
- “create me a suitable pfp”

These can come back as search-like image collections instead of actual generated media.

So:
- keep image detection conservative
- prefer explicit prompts such as “generate an image of ...”
- do not broaden image triggering with vague heuristics unless you also add stronger validation and tests

## State Rules

State modules should stay small and boring:
- `history.py`
- `tracked_messages.py`
- `whitelist.py`

Do not add business logic to state modules unless the logic is inseparable from persistence/storage semantics.

## Testing Rules

The repo is unit-first and stub-heavy.

Prefer:
- small fake clients
- small fake services
- narrow regression tests

Avoid:
- real Discord/network calls
- giant integration scaffolds for simple branching logic

### When to add tests

Add tests whenever you change:
- trigger parsing
- whitelist/admin behavior
- async/sync contracts
- constructor signatures
- search/mode routing
- image routing or image response validation
- moderation behavior
- typed message construction

### Minimum coverage for new control flow

For any new branch or helper, add:
- one positive case
- one negative case
- one malformed/empty-input case
- one failure-path case if AI/network behavior is involved

For image-related changes, strongly prefer direct tests at the image layer:
- `tests/unit/test_image_detector.py`
- `tests/unit/test_image_client.py`
- `tests/unit/test_image_service.py`
- then one orchestration regression in `tests/unit/test_reply_generation.py` if the Discord-visible output changes

### Prefer helper tests for helper logic

If a Discord behavior can be extracted into a small helper, test that helper directly instead of building
large Discord mocks.

This repo already follows that with helpers like:
- `parse_trigger`
- `is_tracked_reply_trigger`
- `handle_whitelist_command`
- `deliver_owner_response`
- `deliver_reply_response`

## High-Risk Files

Edit these carefully and verify behavior after changes:

- `src/eva/discord/handlers.py`
  Highest-risk orchestration file. Auth, trigger routing, AI calls, and persistence meet here.
- `src/eva/discord/delivery.py`
  Delivery success semantics determine whether replies are tracked and remembered.
- `src/eva/discord/commands.py`
  Authorization and whitelist mutation rules live here.
- `src/eva/prompts/persona.py`
  Tiny changes can noticeably alter style/personality.
- `src/eva/prompts/builder.py`
  Prompt section ordering matters.
- `src/eva/ai/orchestrator.py`
  Search-vs-normal routing and moderation sequencing live here.
- `src/eva/ai/respond.py`
  Prompt payload shape and token budgets live here.
- `src/eva/search/detector.py`
  Small changes affect cost, latency, and whether Eva searches at all.
- `src/eva/images/client.py`
  Response validation here determines whether weird upstream `/images` payloads are treated as success or failure.
- `src/eva/images/service.py`
  Prompt construction and asset download fallback behavior live here.
- `src/eva/prompts/image.py`
  Small wording changes can change when image generation runs and how referential prompts are built.

## Anti-Patterns to Avoid

- adding new trigger rules directly in `on_message()` instead of `parse_trigger()`
- putting Discord behavior in `discord/client.py` instead of `handlers.py`
- re-implementing whitelist parsing in `handlers.py` instead of `commands.py`
- mixing Discord read-side context fetches with send/edit/reply logic in the same helper
- mixing authorization decisions with prompt text
- scattering magic numbers across responder/search modules
- using concrete classes where a protocol is the real dependency
- passing `list[dict[str, str]]` where `ChatMessage` sequences are expected
- parsing model decisions loosely
- catching broad exceptions without logging
- hiding behavior changes only in prompt wording without tests
- letting prompt text become the only enforcement mechanism for routing or safety
- treating any `/images` HTTP 200 payload as a valid generated-image success
- relying on `images[0].prompt` for image reply text
- letting tracked replies invoke image generation

## Practical “Ready to Commit” Checklist

- code is in the right module
- shared small constants are in `constants.py`
- env-driven behavior is in `config.py`
- prompt text lives in `prompts/*`
- transport clients remain transport-focused
- service boundaries use protocols where appropriate
- read-only collections use `Sequence[...]`
- `ChatMessage` lists are typed explicitly where needed
- trigger/whitelist/search changes have targeted unit tests
- image changes have targeted client/service/orchestrator tests
- `uv run lint` passes
- `uv run pytest -q` passes
- `uv run pyright` passes
