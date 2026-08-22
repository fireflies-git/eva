# Plan: Social joins + AI friend-request review + NopeCHA

## Context

Eva is a **discord-py-self** selfbot. There is no live friend/invite code (only stale `social_commands` bytecode). `discord.Client` already supports:

- `accept_invite(url)`
- `Relationship.accept()` / `delete()` for incoming requests
- `captcha_handler` → transparent `X-Captcha-Key` retry on `CaptchaRequired`
- `on_relationship_add` + `fetch_user_profile`

NopeCHA free tier: **100 solves/day**, Token API at `https://api.nopecha.com/token`, **no key** (IP quota). Non-residential IPs may get `403 BannedUser`.

---

## 1. NopeCHA captcha solver (IP free tier)

**New:** `src/eva/captcha/nopecha.py` (+ thin `__init__.py`)

- `NopeCHAClient` via existing `aiohttp` (no new dep):
  - POST job → poll GET until token or timeout
  - Optional `api_key` (omit for IP free tier)
- Map `discord.CaptchaRequired`:
  - `hcaptcha` → `type=hcaptcha`
  - `recaptcha` / `recaptcha_enterprise` → `type=recaptcha2`
  - sitekey from exception; `url=https://discord.com`
  - pass `rqdata` in token `data` when present
- Errors: `NopeCHAError` (no credit, banned IP, timeout, unsupported service)
- **Wire in** `create_discord_client(..., captcha_handler=...)` so join/accept retries automatically

**Config** (`config.py`, `.env.example`):

- `NOPECHA_API_KEY` optional (empty = IP free tier)
- `NOPECHA_ENABLED` default `true`
- small timeouts/poll knobs in `constants.py`

---

## 2. Admin join command

**Restore** `src/eva/discord/social_commands.py` (pattern from old bytecode + `terminal_commands.py`):

| Command | Who | Behavior |
|---------|-----|----------|
| `eva join <invite>` | owner / `ALLOWED_ADMIN_IDS` | `client.accept_invite(url)` |

- Protocol `SocialClient` with `accept_invite`
- Outcomes via `CommandOutcome`
- If captcha fails after handler: clear warning (not silent fail)
- Dispatch from `handlers._dispatch_commands` (admin-gated like terminal)

**Join target after ship:** admin runs

```text
eva join https://discord.gg/4SQQMjGjg
```

(Plan mode cannot join live; that is the post-implement step.)

---

## 3. Friend requests → AI DM admins → yes/no

**Not** blind auto-accept. Flow:

```text
on_relationship_add (incoming)
  → fetch_user_profile (bio, display name, username, badges/legacy name, mutuals if available)
  → AI crafts short review + recommendation
  → DM each admin (ALLOWED_ADMIN_IDS + owner account if reachable)
  → store pending decision
  → admin replies yes/no (or accept/deny)
  → accept() or delete()  [captcha via NopeCHA]
  → confirm to responding admin; cancel other pendings for that user
```

**New pieces:**

| Module | Role |
|--------|------|
| `src/eva/state/pending_friend_requests.py` | In-memory pending by requester_id; TTL; first admin reply wins |
| `src/eva/ai/friend_request_review.py` | Small AI helper: profile text → DM body (judgment + “should I accept?”) |
| `src/eva/prompts/friend_request.py` | Prompt text only |
| `src/eva/discord/friend_requests.py` | Profile serialize, DM fan-out, yes/no parse, accept/deny |
| `client.py` | `on_relationship_add` → handler |
| `handlers.py` | Early DM confirmation path (before whitelist gate for **admins in DMs**), mirror account-update confirm |

**DM reply parsing** (reuse style of `_parse_account_update_confirmation`):

- accept: `yes`, `y`, `accept`
- deny: `no`, `n`, `deny`, `reject`
- optional: `eva friends accept` / `eva friends deny` as admin commands for stuck pendings

**Gates:**

- Only `RelationshipType.incoming_request`
- Ignore bots if desired
- If all admin DMs fail → log + leave request pending (manual later)
- Captcha on accept → NopeCHA; on total failure notify admin

---

## 4. Wiring (`app.py`)

- Build `NopeCHAClient` when enabled; pass captcha handler into `create_discord_client`
- Build `FriendRequestReviewService` + `PendingFriendRequestStore`
- Pass into `SelfbotMessageHandler` + client relationship event
- Start/close aiohttp session with other clients

---

## 5. Tests (unit, fakes)

- `tests/unit/test_social_commands.py` — join admin/usage/error; non-admin denied
- `tests/unit/test_nopecha_client.py` — service map, poll success, no-credit/banned
- `tests/unit/test_friend_requests.py` — profile → pending; yes accepts; no denies; first admin wins; malformed reply ignored
- Config: optional NopeCHA fields load cleanly

Run: `uv run lint`, `uv run pytest -q`, `uv run pyright`

---

## 6. Out of scope / risks

- **Selfbot + captcha solving** is high ban-risk (already true for Eva)
- Free NopeCHA: **100/day**, IP may be blocked on datacenter hosts
- Discord may still require phone/email after “solved” captcha — surface that error to admin
- No auto-join on startup; join only via admin command (including your invite)

---

## Implementation order

1. NopeCHA client + `captcha_handler` on Discord client
2. `eva join` + handler dispatch
3. Friend-request pipeline (event → profile → AI DM → pending → yes/no)
4. Tests + lint/typecheck
5. **You:** set env if needed, restart Eva, run
   `eva join https://discord.gg/4SQQMjGjg`
   and send a test friend request to verify DM flow

---

## Files touched (expected)

- **New:** `src/eva/captcha/*`, `src/eva/discord/social_commands.py`, `src/eva/discord/friend_requests.py`, `src/eva/ai/friend_request_review.py`, `src/eva/prompts/friend_request.py`, `src/eva/state/pending_friend_requests.py`, matching tests
- **Edit:** `client.py`, `handlers.py`, `app.py`, `config.py`, `.env.example`, maybe `constants.py` / `state/__init__.py`
