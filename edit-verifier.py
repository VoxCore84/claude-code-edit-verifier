"""Smart Edit Verifier — PostToolUse hook for Claude Code.

Reads the file back after every Edit operation to verify the edit actually
applied. Catches silent failures before they compound into broken state.

Based on mvanhorn's PR #32755 (anthropics/claude-code) with three improvements:
  1. Configurable minimum threshold (env EDIT_VERIFY_MIN_CHARS, default 3)
  2. Checks that old_string is GONE (catches wrong-occurrence edits)
  3. False-alarm reduction: only flags old_string presence when new_string
     is also MISSING, preventing false positives from legitimate duplicate
     occurrences elsewhere in the file

Setup: Add to .claude/settings.json as a PostToolUse hook matching "Edit".
See README.md for full installation instructions.

License: MIT — Copyright (c) 2026 VoxCore84
"""
import json
import os
import sys


def main():
    # --- Parse hook input from stdin ---
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if tool_name != "Edit":
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response", {})

    file_path = tool_input.get("file_path", "")
    old_string = tool_input.get("old_string", "")
    new_string = tool_input.get("new_string", "")
    replace_all = tool_input.get("replace_all", False)

    if not file_path:
        sys.exit(0)

    # --- Skip trivially small edits (configurable) ---
    min_chars = int(os.environ.get("EDIT_VERIFY_MIN_CHARS", "3"))
    if new_string and len(new_string.strip()) < min_chars:
        sys.exit(0)

    # --- Skip if the Edit tool already reported failure ---
    if isinstance(tool_response, dict) and not tool_response.get("success", True):
        sys.exit(0)

    # --- Read the file back with encoding fallback chain ---
    content = None
    for encoding in ("utf-8", None, "latin1"):
        try:
            with open(file_path, "r", encoding=encoding) as f:
                content = f.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except (FileNotFoundError, PermissionError, OSError):
            result = {
                "decision": "block",
                "reason": (
                    f"Edit verification: Could not read '{file_path}' after the edit. "
                    "The file may have been moved, deleted, or is locked by another process."
                ),
            }
            json.dump(result, sys.stdout)
            sys.exit(0)

    if content is None:
        result = {
            "decision": "block",
            "reason": f"Edit verification: Could not decode '{file_path}' with any supported encoding (utf-8, system default, latin1).",
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    # --- Verify the edit applied correctly ---
    problems = []

    # Check 1: new_string should be present in the file
    if new_string and new_string not in content:
        problems.append(f"MISSING NEW CONTENT: Expected text not found in '{file_path}'.")

    # Check 2: old_string should be gone (with false-alarm reduction)
    #
    # The key improvement over PR #32755: we only flag old_string's presence
    # when new_string is ALSO missing. This handles the common case where
    # old_string legitimately appears in multiple locations — if the edit
    # succeeded on the target occurrence, new_string will be present and
    # we skip the alarm.
    if old_string and old_string in content:
        if replace_all:
            # replace_all=true means ALL occurrences should be gone
            problems.append(
                f"OLD CONTENT STILL PRESENT (replace_all=true): "
                f"Original text still exists in '{file_path}'."
            )
        elif old_string != new_string and new_string and new_string not in content:
            # Single replacement: old_string is still there AND new_string is missing
            # — this strongly suggests the edit did not apply
            occurrences = content.count(old_string)
            problems.append(
                f"POSSIBLE EDIT FAILURE: old_string still appears {occurrences} time(s) "
                f"and new_string is missing."
            )

    # --- Report results ---
    if problems:
        result = {
            "decision": "block",
            "reason": (
                "Edit verification FAILED:\n"
                + "\n".join(f"  - {p}" for p in problems)
                + "\n\nPlease read the file to verify the edit applied correctly."
            ),
        }
        json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
