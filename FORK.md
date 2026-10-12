# FORK.md

This is `ASneakyToast/dash-fork`, Joel's fork of [`whatever/dash`](https://github.com/whatever/dash) (Matt's repo). Read this before creating a branch, committing, or opening a PR.

The goal: Joel runs a customized dash, and good changes still go to Matt cleanly. One rule makes both work: **a branch that can go to Matt never contains a fork-only file.**

## Branches

| Branch | What it is | Cut from | Goes to Matt? |
|---|---|---|---|
| `main` | Exact copy of `whatever/dash` `main`. Fast-forward only. Never commit here. | | no |
| `feat/*`, `fix/*`, `chore/*`, `claude/*` | **Topic branches.** One change each, no fork-only files. | `upstream/main` | yes, these are the only ones |
| `joel-dash/main` | **The deployable line.** `upstream/main` + fork-only files + a merge of every topic branch Joel runs. Every push builds an image. | | never |
| `joel-dash/<name>` | Experiments on top of `joel-dash/main` (e.g. `joel-dash/acp`). Merge into `joel-dash/main` by PR when ready. | `joel-dash/main` | never |
| `fork/*` | Fork-only layers (tooling, OpenSpec change folders). PR them into `joel-dash/main`. | `joel-dash/main` | never |

Open fork PRs against `joel-dash/main`. A PR against `main` is a dress rehearsal: it shows exactly what Matt would see.

## Rules

1. **Never commit to `main`.** Refresh it with `git fetch upstream && git push origin upstream/main:main`.
2. **Start every topic branch at `upstream/main`, never at `joel-dash/main`.** Starting from the fork line is how fork files leak, and how a change ends up built twice (once for the fork, once clean for Matt).
3. **Topic branches reach `joel-dash/main` by merge commit** (PR, "Create a merge commit"). Don't rebase or squash `joel-dash/main`.
4. **Check before anything goes to Matt.** This must print nothing:

   ```sh
   git diff --name-only upstream/main...HEAD \
     | grep -E '^(\.claude/|CLAUDE\.md|FORK\.md|\.github/workflows/joel-dash|openspec/changes/)' \
     | grep -v 'changes/archive/.gitkeep'
   ```

   Also: no `fixup!` commits, and PR titles follow `AGENTS.md` (`fix:`, `feat:`, `chore:`).
5. **Take upstream changes into the fork line** with `git merge upstream/main` on a branch off `joel-dash/main`, then PR it.

Setup once: `git remote add upstream https://github.com/whatever/dash`.

## Fork-only files

Never in a topic branch:

- `.github/workflows/joel-dash-build.yml` builds `joel-dash/**` pushes into `ghcr.io/asneakytoast/dash:joel-dash-<short-sha>`.
- `FORK.md`, `CLAUDE.md`, the pointer line at the top of `AGENTS.md`.
- `.claude/` (OpenSpec commands and skills for Claude Code). Matt installs his own with `openspec init --tools <his>`.
- `openspec/changes/<name>/`: changes that describe fork-only work.
- The dash-brood install lines in `Dockerfile` (commit `0e3eb2e`) and its notes in `docs/plugins.md` and `examples/dash-brood/README.md`.

`openspec/specs/` and `openspec/config.yaml` describe upstream behavior and are meant to go to Matt (branch `chore/openspec`).

## What `joel-dash/main` holds that upstream doesn't

| Change | Topic branch (for Matt) | Note |
|---|---|---|
| OpenAI-compatible memory | `feat/openai-compatible-memory` | Has a `fixup!` commit to squash before it goes up. Spec: `openspec/changes/openai-compatible-memory/`. |
| OpenSpec baseline specs | `chore/openspec` | Merged here. |
| Mobile UI | `feat/mobile-layout` | **Duplicate:** the fork line has its own commit (`0d32b73`). |
| Plugin system + dash-brood | `claude/dash-plugin-system-ue2bwa` | **Duplicate:** the fork line has its own commits. |
| Theming | `claude/dash-theming` | **Duplicate:** the fork line merged PR #6, a port onto the fork line. |
| ACP agents | none yet | Merged from `joel-dash/acp`. Built on the plugin system and theming, so a clean branch for Matt waits on those. Spec: `openspec/changes/acp-agent-sessions/`. |

**Duplicates collapse on upstream merge.** When a topic branch lands in `whatever/dash`, refresh `main`, merge `upstream/main` into `joel-dash/main` (rule 5), and expect conflicts where the fork's copy differs. Resolve toward upstream's version unless the fork copy adds something.

## Building and deploying

A push to `joel-dash/**` builds the image. Pin `joel-dash-<short-sha>` in `cluster/apps/dash/` in `jlithgow-ops` (see its `docs/plans/dash.md`). The tag must exist in ghcr before the pin merges.

## OpenSpec

Specs live in `openspec/specs/`, one folder per capability. A change (`/opsx:propose`) lives in `openspec/changes/<name>/` until the work is merged **upstream**, then `/opsx:archive` folds it into the specs. Keep fork-only changes unarchived, so `openspec/specs/` stays equal to what Matt has. Check with `openspec validate --all --strict`. Telemetry is off: `openspec config set telemetry.enabled false`.
