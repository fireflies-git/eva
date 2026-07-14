from __future__ import annotations

import re

_CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)

_LANGUAGE_EXTENSIONS: dict[str, str] = {
    "py": ".py",
    "python": ".py",
    "js": ".js",
    "javascript": ".js",
    "ts": ".ts",
    "typescript": ".ts",
    "jsx": ".jsx",
    "tsx": ".tsx",
    "html": ".html",
    "css": ".css",
    "scss": ".scss",
    "json": ".json",
    "jsonc": ".jsonc",
    "yaml": ".yaml",
    "yml": ".yml",
    "toml": ".toml",
    "xml": ".xml",
    "md": ".md",
    "markdown": ".md",
    "rs": ".rs",
    "rust": ".rs",
    "go": ".go",
    "java": ".java",
    "kt": ".kt",
    "kotlin": ".kt",
    "swift": ".swift",
    "c": ".c",
    "cpp": ".cpp",
    "c++": ".cpp",
    "cxx": ".cpp",
    "h": ".h",
    "hpp": ".hpp",
    "cs": ".cs",
    "csharp": ".cs",
    "rb": ".rb",
    "ruby": ".rb",
    "php": ".php",
    "sql": ".sql",
    "sh": ".sh",
    "bash": ".sh",
    "shell": ".sh",
    "zsh": ".sh",
    "ps1": ".ps1",
    "powershell": ".ps1",
    "bat": ".bat",
    "cmd": ".cmd",
    "lua": ".lua",
    "r": ".r",
    "scala": ".scala",
    "dart": ".dart",
    "dockerfile": ".dockerfile",
    "docker": ".dockerfile",
    "ini": ".ini",
    "cfg": ".cfg",
    "env": ".env",
    "diff": ".diff",
    "patch": ".patch",
    "txt": ".txt",
    "text": ".txt",
    "makefile": "",
    "make": "",
    "log": ".log",
}


def extract_code_blocks(text: str) -> tuple[str, list[tuple[str, bytes]]]:
    attachments: list[tuple[str, bytes]] = []

    if not text:
        return text, attachments

    def _replace(match: re.Match[str]) -> str:
        lang = match.group(1).strip().lower() if match.group(1) else ""
        code = match.group(2)
        if not code.strip():
            return match.group(0)

        ext = _LANGUAGE_EXTENSIONS.get(lang, ".txt")
        idx = len(attachments)
        if idx == 0:
            filename = f"code{ext}"
        else:
            filename = f"code_{idx + 1}{ext}"

        attachments.append((filename, code.encode("utf-8")))
        return f"[`{filename}`]"

    result = _CODE_BLOCK_RE.sub(_replace, text)

    if not attachments:
        return text, attachments

    result = re.sub(r"\n{3,}", "\n\n", result)

    return result, attachments
