# AGENTS.md

> Fork (joellithgow95/dash-fork): read `FORK.md` before branching or committing, and keep it up to date.

## Code style

- Use list, dict, and set comprehensions and generator expressions instead of `for` loops, especially loops that call `.append()`.
- Do not write comments in generated code. Tool pragmas such as `# noqa` and `# type: ignore` are permitted.
- Write one-line docstrings in the imperative mood. Start with the verb that matches what the callable does:

| Callable | Verb | Example |
| :- | :- | :- |
| Returns a value | Return | `"""Return the user with the given ID."""` |
| Returns a bool | Return True if | `"""Return True if the job is finished."""` |
| Generator | Yield | `"""Yield each memory that matches the query."""` |
| Side effect, returns None | Specific action verb | `"""Delete expired jobs from the queue."""` |
| Raises only (a validator) | Raise | `"""Raise ValueError if the token is expired."""` |
| Class | Noun phrase | `"""A queued job and its status."""` |

## PR style

- use semantic pull request titles with `{fix,feat,chore}`
- keep descriptions simple and up-to-date
