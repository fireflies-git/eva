CHECK_MARK = "✔"
X_MARK = "✖"
WARNING_MARK = "ⓘ"
ARROW_MARK = "➤"
BULLET_MARK = "●"
STAR_MARK = "✦"
PROMPT_MARK = "➜"

MAX_SEARCH_RESULTS = 5
MAX_QUERY_CONTEXT_MESSAGES = 3
MAX_SEARCH_DECISION_CONTEXT_MESSAGES = 5
MAX_SEARCH_REPLY_CONTEXT_MESSAGES = 5

DEFAULT_MAX_HISTORY_MESSAGES = 30
DEFAULT_RESPONSE_CONTEXT_MESSAGES = 40

REPLY_MAX_TOKENS = 4096
SEARCH_REPLY_MAX_TOKENS = 4096
SEARCH_REWRITE_MAX_TOKENS = 64

LOADING_MESSAGES: tuple[str, ...] = (
    "<a:loading:1478829628498903272>  Thinking...",
    "<a:loading:1478829628498903272>  On it...",
    "<a:loading:1478829628498903272>  Processing...",
    "<a:loading:1478829628498903272>  Give me a sec...",
    "<a:loading:1478829628498903272>  Working on it...",
    "<a:loading:1478829628498903272>  Let me check...",
    "<a:loading:1478829628498903272>  I'll get right on that...",
    "<a:loading:1478829628498903272>  Hang on...",
    "<a:loading:1478829628498903272>  Almost done...",
    "<a:loading:1478829628498903272>  Just a moment...",
    "<a:loading:1478829628498903272>  One moment please...",
)

DISCORD_MESSAGE_LIMIT = 2000
