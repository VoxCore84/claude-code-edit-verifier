# Smart Edit Verifier for Claude Code

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue) ![License: MIT](https://img.shields.io/github/license/VoxCore84/claude-code-edit-verifier) ![GitHub release](https://img.shields.io/github/v/release/VoxCore84/claude-code-edit-verifier)

**Catches Failed Edits Before They Compound**

A PostToolUse hook that reads the file back after every `Edit` operation to verify the edit actually applied. Prevents the silent-failure cascade where Claude builds on top of an edit that never landed.

## The Problem

Claude Code's `Edit` tool sometimes silently fails. The tool reports success, but the file didn't actually change. Common causes:

- **Wrong match**: `old_string` matched a different occurrence than intended, or didn't match at all due to whitespace/encoding differences.
- **Encoding mismatch**: The file uses a different encoding than expected, causing the match to fail silently.
- **Race condition**: Another process modified the file between the match and the write.
- **Partial match**: The edit targeted text that was already changed by a previous edit in the same session.

When this happens, every subsequent edit builds on the wrong file state. By the time you notice, the damage has compounded across multiple operations and the file is in an inconsistent state that's painful to untangle.

## The Solution

This hook runs automatically after every `Edit` operation. It reads the file back and performs two checks:

1. **new_string is present** -- confirms the intended content actually landed in the file.
2. **old_string is gone** -- confirms the original content was replaced, not left behind.

If either check fails, the hook returns a `block` decision that surfaces the problem immediately, before Claude moves on to the next operation.

## The False-Alarm Fix

This hook improves on [mvanhorn's PR #32755](https://github.com/anthropics/claude-code/pull/32755), which introduced the core idea of post-edit verification. The original PR checked whether `old_string` still existed in the file after the edit -- but this produced false alarms in a common scenario:

**The substring problem**: You edit one occurrence of a string that legitimately appears multiple times in the file. The edit succeeds on the target occurrence, but `old_string` still exists at other locations. The original PR would flag this as a failure every time.

**Our fix**: We only flag `old_string`'s continued presence when `new_string` is *also* missing. If the edit succeeded, `new_string` will be in the file, and we skip the alarm -- even if `old_string` appears elsewhere. This eliminates the most common source of false positives while still catching actual failures.

| Scenario | PR #32755 | This hook |
|----------|-----------|-----------|
| Edit succeeded, old_string appears elsewhere | FALSE ALARM | No alert |
| Edit failed, old_string still there, new_string missing | Alert | Alert |
| Edit failed, new_string missing entirely | Alert | Alert |
| replace_all used but old_string still present | Alert | Alert |

The one edge case this won't catch: an edit that targeted occurrence #2 but accidentally hit occurrence #1 instead, where both old and new strings now coexist. This is rare in practice and would require comparing exact positions, which adds complexity without meaningful benefit.

## Installation

### 1. Copy the script

Place `edit-verifier.py` somewhere accessible. For example:

```
~/.claude/hooks/edit-verifier.py
```

Or clone this repo and point to it directly.

### 2. Add the hook to your settings

Add to your `.claude/settings.json` (user-level) or `.claude/settings.json` in your project root (project-level):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python ~/.claude/hooks/edit-verifier.py"
          }
        ]
      }
    ]
  }
}
```

> **Windows users**: Use the full path with forward slashes, e.g. `python C:/Users/you/.claude/hooks/edit-verifier.py`.

### 3. (Optional) Configure the threshold

By default, edits where `new_string` is fewer than 3 non-whitespace characters are skipped (too small to verify reliably). Change this with the `EDIT_VERIFY_MIN_CHARS` environment variable:

```bash
export EDIT_VERIFY_MIN_CHARS=5
```

## How It Works

```
Edit tool completes
        |
        v
  Is tool_name "Edit"? --no--> exit (pass-through)
        |
       yes
        |
        v
  Is new_string < min_chars? --yes--> exit (too small to verify)
        |
       no
        |
        v
  Did Edit report failure? --yes--> exit (already handled)
        |
       no
        |
        v
  Read file back (utf-8 -> system -> latin1)
        |
        v
  Failed to read? --yes--> BLOCK: "could not read file"
        |
       no
        |
        v
  Is new_string in file? --no--> BLOCK: "new content missing"
        |
       yes
        |
        v
  Is old_string in file?
        |
       yes
        |
        v
  Was replace_all used? --yes--> BLOCK: "old content still present"
        |
       no
        |
        v
  Is new_string missing? --yes--> BLOCK: "possible edit failure"
        |
       no
        |
        v
  exit (edit verified OK)
```

## What It Catches

| Failure Mode | Detection |
|---|---|
| Edit silently didn't apply | new_string missing from file |
| Wrong occurrence edited (replace_all) | old_string still present after replace_all |
| Wrong occurrence edited (single) | old_string present AND new_string missing |
| File encoding mismatch | Encoding fallback chain fails, or content doesn't match |
| File moved/deleted/locked | Cannot read file after edit |

## What It Doesn't Catch

- Edits where `new_string` is too short (below `EDIT_VERIFY_MIN_CHARS` threshold). These are skipped to avoid noise.
- An edit that hit the wrong occurrence when both old and new strings coexist at different positions. This is rare and would require position tracking.
- Edits to binary files. The hook reads files as text.

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `EDIT_VERIFY_MIN_CHARS` | `3` | Minimum non-whitespace characters in `new_string` to trigger verification. Set higher to reduce noise on trivial edits, lower for stricter checking. |

## Encoding Support

The hook tries three encodings in order:

1. **UTF-8** -- covers most modern source files
2. **System default** (`None` in Python) -- respects locale settings
3. **Latin-1** -- never fails, catches Windows-1252 and similar legacy encodings

If all three fail to read the file, the hook blocks with a decode error.

## Based On

[PR #32755](https://github.com/anthropics/claude-code/pull/32755) by [mvanhorn](https://github.com/mvanhorn) -- introduced the concept of post-edit file verification for Claude Code. This hook extends that idea with configurable thresholds, smarter old_string checking, and Windows encoding compatibility.

## License

MIT -- see [LICENSE](LICENSE).

---

Built by [VoxCore84](https://github.com/VoxCore84)
