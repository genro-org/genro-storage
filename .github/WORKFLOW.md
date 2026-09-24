# Git Workflow - genro-storage

## Overview

genro-storage works on a **single long-lived branch**. `main` carries the
releases; every change arrives through a short-lived topic branch that is deleted
once merged.

The Git Flow model this project used until 0.4.3 is retired. `develop` was
removed on 2026-07-30, and the release and hotfix branches went with it: since
0.7.0 every commit has landed on `main` directly or through a single pull request
against it.

## Branch Structure

```
main (protected)
  ↑
  └── PR (or a direct push, for administrators)
       ↑
    feat/*  fix/*  docs/*  refactor/*  test/*  chore/*  hotfix/*
```

### Branch Purposes

| Branch | Purpose | Protected | Lifetime |
|--------|---------|-----------|----------|
| `main` | Releases, tagged `v*` | ✅ Yes | permanent |
| `feat/*` | New features | ❌ No | deleted after merge |
| `fix/*` | Bug fixes | ❌ No | deleted after merge |
| `docs/*` | Documentation only | ❌ No | deleted after merge |
| `refactor/*`, `test/*`, `chore/*` | Everything else, prefix matching the commit type | ❌ No | deleted after merge |
| `hotfix/*` | Urgent fix that ships immediately | ❌ No | deleted after merge |

There is no `develop`, no `release/*` and no merge-back step.

## Protection Rules

`main` is protected, but lightly. What is enforced:

- ❌ No force pushes
- ❌ No deletions

What is **not** enforced, and is worth knowing before you rely on it:

- No required approving reviews (`required_approving_review_count` is 0)
- No required status checks — a red CI run does not block a merge
- Administrators are exempt from the pull request requirement
  (`enforce_admins` is off), which is how the maintainer lands release commits
  straight on `main`

Read the live settings rather than trusting this table:

```bash
gh api repos/genropy/genro-storage/branches/main/protection
```

## Common Workflows

### 1. Working on a Change

```bash
# Start from main
git checkout main
git pull origin main

# Create a topic branch, prefix matching the commit type
git checkout -b feat/add-webdav-backend

# Make changes, commit
git add .
git commit -m "feat: add WebDAV backend support"

# Push and open a PR against main
git push origin feat/add-webdav-backend
gh pr create --base main --head feat/add-webdav-backend

# After the merge, delete the branch
git push origin --delete feat/add-webdav-backend
```

### 2. Cutting a Release

```bash
git checkout main
git pull origin main

# Bump the single source of truth: __version__ in the package itself.
# pyproject.toml reads it through [tool.hatch.version] - there is no second place.
vim src/genro_storage/__init__.py

# Add the entry, newest first
vim docs/changelog.rst

git add .
git commit -m "chore: release 0.9.0"
git push origin main

# The v* tag is what triggers .github/workflows/release.yml and the PyPI publish
git tag -a v0.9.0 -m "Release version 0.9.0"
git push origin v0.9.0
```

Run the full suite with the Docker services up before tagging — see
[TESTING.md](../TESTING.md). CI does not gate the merge, so this check is yours.

### 3. Urgent Fix

No separate flow: `main` is the release branch, so an urgent fix is an ordinary
topic branch, `hotfix/` by convention, followed by a patch tag if it has to ship
straight away.

```bash
git checkout main
git pull origin main
git checkout -b hotfix/critical-security-fix

git add .
git commit -m "fix: patch critical security vulnerability"
git push origin hotfix/critical-security-fix

gh pr create --base main --head hotfix/critical-security-fix \
  --title "HOTFIX: Critical security patch"

# After the merge
git checkout main
git pull origin main
git tag -a v0.8.1 -m "Hotfix: security patch"
git push origin v0.8.1
```

## Pull Request Guidelines

Every PR targets `main`. Requirements:

- All tests pass, with the Docker services running for the integration ones
- Coverage maintained
- Docstrings and `docs/` updated for user-facing changes
- `docs/changelog.rst` updated
- Conventional commit messages

## Commit Message Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <description>

[optional body]

[optional footer]
```

Types:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation only
- `style:` - Code style (formatting, etc.)
- `refactor:` - Code refactoring
- `test:` - Test additions/changes
- `chore:` - Maintenance tasks
- `perf:` - Performance improvements

A `!` after the type marks a breaking change (`refactor!:`, `feat!:`).

Examples:
```
feat: add WebDAV backend support
fix: resolve S3 timeout issue in large file uploads
docs: update contributing guidelines
feat!: per-node encryption with a self-describing envelope
chore: release 0.9.0
```

## Tools

### GitHub CLI

```bash
# Create PR
gh pr create --base main --head feat/my-feature

# List PRs
gh pr list

# Review PR
gh pr review 74 --approve
gh pr review 74 --comment -b "Looks good!"
gh pr review 74 --request-changes -b "Please fix..."

# Merge PR
gh pr merge 74

# Clean up local branches whose remote is gone
git fetch --prune
git branch -vv | grep ': gone]'
```

## Troubleshooting

### "Protected branch update failed"

You tried to force-push to `main`, or to delete it. Neither is allowed; a plain
push is, for administrators.

### Merge conflicts

```bash
# Update your topic branch with the latest main
git checkout feat/my-feature
git fetch origin
git merge origin/main
# Resolve conflicts
git add .
git commit -m "merge: resolve conflicts with main"
git push origin feat/my-feature
```

## Resources

- [CONTRIBUTING.md](../CONTRIBUTING.md) - Full contribution guide
- [TESTING.md](../TESTING.md) - Running the suite, with and without Docker
- [Conventional Commits](https://www.conventionalcommits.org/)
- [GitHub Protected Branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches)

---

**Questions?** Open an issue or ask in pull requests.
