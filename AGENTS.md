# Project Instructions

## Project context

- This is a Python 3.13 desktop application managed with `uv`.
- The application uses PySide6, SQLite, pyqtgraph, and openpyxl.
- Activate this project with Serena when available. Read the relevant project memories before making changes, and use Serena for internal symbol, definition, and reference analysis.
- Perform Serena onboarding only when the project has not already been onboarded.

## Development rules

- Keep changes focused and preserve existing behavior unless the task explicitly requires a behavior change.
- Before adding a dependency, check whether the standard library or an existing dependency can solve the problem.
- If an external package API is uncertain, check current official documentation with Context7 before implementing against it.
- Use modern Python 3.13 type syntax and the existing Ruff formatting conventions.
- Use scoped PySide6 enums such as `Qt.AlignmentFlag` and `QMessageBox.StandardButton` rather than deprecated aliases.
- Preserve the existing local naive ISO timestamp format used by `played_at` unless a data migration is explicitly requested.
- User data belongs in the OS-standard data directory resolved by `src/mdlogger/paths.py`. Preserve `MDLOGGER_DATA_DIR` support and the non-destructive legacy-data migration behavior.

## Required validation

After changing Python code, run all of the following:

1. `uv run ruff check .`
2. `uv run ruff format --check .`
3. `uv run ty check`
4. Tests related to the change with `uv run pytest <target>`
5. The full `uv run pytest` suite when the impact is broad

If Ruff reports formatting differences, use `uv run ruff format .`. Use `uv run ruff check . --fix` only for safe, understood fixes, then rerun the required checks.

Never claim a check passed unless it was actually run successfully. If a failure was caused by the current change, fix the cause and rerun the failing check.

## Agent terminal sandbox notes

- The normal commands above are correct for users and ordinary terminals; do not add cache overrides to user-facing documentation.
- In the Zed agent terminal sandbox, the default user cache and tool directories such as `~/.cache/uv`, `~/.cache/pip-audit`, and `~/.local/share/uv/tools` may be read-only. Even read-like `uv` commands can create lock or temporary files there and fail with `Read-only file system`.
- When that sandbox-only failure occurs, redirect only the affected command's temporary state to writable `/tmp`, for example: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest`.
- For `uvx` tools that also need an installation directory and their own cache, use command-scoped overrides such as `XDG_CACHE_HOME=/tmp/tool-cache UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx ...`.
- These overrides are an agent sandbox workaround, not a project requirement. `/tmp` may be cleared between terminal calls, so repeated tool installation or copy-mode warnings are expected and are not project failures.

## Known Zed diagnostic behavior

- Zed's internal diagnostics may temporarily fail to index a newly created module. A known instance is an unresolved-import diagnostic for `mdlogger.checksum` in `tests/test_checksum.py`, even though `uv run ty check`, direct Python import/execution, and pytest all resolve it successfully.
- Do not assume every unresolved import is a cache issue. Refresh diagnostics for both the new module and its importer first, then verify with `uv run ty check`, direct Python execution when relevant, and the related pytest target.
- If all authoritative checks pass and only Zed continues to report the newly created module as unresolved, document it as a stale editor/indexing diagnostic rather than changing correct imports solely to silence the editor cache.

## UI/UX work

- For any task that designs, changes, or reviews UI layout, styling, interaction,
  accessibility, navigation, or data visualization, load and follow the
  project-local `ui-ux-pro-max` Skill before planning or editing.
- Apply its recommendations through PySide6, Qt layouts, QSS, and pyqtgraph.
  Do not introduce web frameworks solely for UI implementation.
- `AGENTS.md` and existing project behavior take precedence if a Skill
  recommendation conflicts with project rules.
