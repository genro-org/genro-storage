# Contributing to genro-storage

Thank you for your interest in contributing to genro-storage! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Git Workflow](#git-workflow)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Testing Guidelines](#testing-guidelines)
- [Documentation](#documentation)

## Code of Conduct

By participating in this project, you agree to maintain a respectful and collaborative environment. Please be considerate and constructive in your interactions.

## Git Workflow

We work on a **single long-lived branch**. `main` carries the releases; every
change arrives through a short-lived topic branch that is deleted once merged.
The Git Flow model this project used until 0.4.3 is retired: `develop` was
removed on 2026-07-30, and release and hotfix branches went with it.

### Branch Structure

- **`main`**: the only permanent branch. Releases are tagged here.
- **topic branches**: short-lived, one per change, named after the kind of work —
  `feat/`, `fix/`, `docs/`, `refactor/`, `test/`, `chore/`, `hotfix/`. Deleted
  after the merge.

### Branch Protection Rules

`main` is protected, but lightly:
- **No force pushes** - history cannot be rewritten
- **No deletions** - the branch cannot be removed
- **Pull requests are the contribution path**, and the place review happens

Note what is *not* enforced: there is no required approval count and no required
status check, and administrators are exempt from the pull request requirement —
which is how the maintainer lands release commits directly on `main`. If you are
not an administrator, open a pull request.

### Working on a Change

1. **Start from main**:
   ```bash
   git checkout main
   git pull origin main
   ```

2. **Create a topic branch**:
   ```bash
   git checkout -b feat/your-feature-name
   ```

   Naming conventions — the prefix matches the commit type:
   - `feat/add-webdav-backend`
   - `fix/s3-timeout`
   - `docs/encryption-guide`
   - `chore/bump-github-actions`
   - `hotfix/ci-green`

3. **Make your changes**:
   - Write clean, documented code
   - Add tests for new functionality
   - Update documentation as needed

4. **Commit your changes**:
   ```bash
   git add .
   git commit -m "feat: add WebDAV backend support"
   ```

   Follow [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat:` - New feature
   - `fix:` - Bug fix
   - `docs:` - Documentation changes
   - `test:` - Test additions/changes
   - `refactor:` - Code refactoring
   - `chore:` - Maintenance tasks

5. **Push to GitHub**:
   ```bash
   git push origin feature/your-feature-name
   ```

6. **Create a Pull Request**:
   - Open a PR from your topic branch against `main`
   - Fill in the PR template with a clear description
   - Link related issues (e.g., "Closes #15")
   - Wait for review and address feedback
   - Delete the branch once it is merged

### Release Process

Releases are cut on `main`; there is no release branch.

1. **Bump the version** in `src/genro_storage/__init__.py`. That `__version__` is
   the single source of truth — `pyproject.toml` reads it through
   `[tool.hatch.version]`, so there is no second place to edit.

2. **Add the changelog entry** in `docs/changelog.rst`, newest first.

3. **Run the full suite** with the Docker services up (see [TESTING.md](TESTING.md)).

4. **Tag on `main`**: pushing a `v*` tag is what triggers the release workflow
   and the PyPI publish.
   ```bash
   git checkout main
   git pull origin main
   git tag -a v0.9.0 -m "Release version 0.9.0"
   git push origin v0.9.0
   ```

### Urgent Fixes

There is no separate hotfix flow: `main` is the release branch, so an urgent fix
is an ordinary topic branch — `hotfix/` by convention — merged into `main` and
followed by a patch tag if it needs to ship immediately.

## Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/genropy/genro-storage.git
   cd genro-storage
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   # Install in development mode
   pip install -e ".[dev,all]"
   ```

4. **Run tests**:
   ```bash
   pytest tests/ -v
   ```

## Making Changes

### Before You Start

- Check existing issues and PRs to avoid duplicate work
- For large changes, open an issue first to discuss the approach
- Keep changes focused - one feature/fix per PR

### Code Style

- Follow PEP 8 style guidelines
- Use type hints for function signatures
- Write docstrings for public APIs
- Keep functions small and focused

### Running Code Quality Tools

```bash
# Format code
black src/genro_storage/ tests/

# Lint
ruff check src/genro_storage/ tests/

# Type check (advisory, never a gate - see the mypy config in pyproject.toml)
mypy
```

## Testing Guidelines

### Writing Tests

- Write tests for all new features
- Maintain or improve test coverage
- Use descriptive test names
- Follow the existing test structure

### Test Types

- **Unit tests**: Fast, no external dependencies
- **Integration tests**: Test with real backends (MinIO, etc.)

### Running Tests

```bash
# All tests
pytest tests/ -v

# Specific test file
pytest tests/test_new_backends.py -v

# With coverage
pytest tests/ -v --cov=genro_storage --cov-report=html

# Skip slow integration tests
pytest tests/ -v -m "not integration"
```

## Pull Request Process

1. **Update documentation** for any user-facing changes
2. **Add tests** for new functionality
3. **Update `docs/changelog.rst`** with your changes
4. **Ensure all tests pass** and coverage is maintained
5. **Request review** from maintainers
6. **Address feedback** promptly and professionally
7. **Squash commits** if requested before merge

### PR Checklist

- [ ] Code follows project style guidelines
- [ ] Tests added/updated and passing
- [ ] Documentation updated
- [ ] `docs/changelog.rst` updated
- [ ] Commits follow conventional commit format
- [ ] PR description clearly explains the changes
- [ ] Related issues linked

## Documentation

- Update docstrings for code changes
- Update `.rst` files in `docs/` for user-facing features
- Add examples to demonstrate new functionality
- Keep documentation in English

### Building Documentation

```bash
cd docs/
make html
# Output in docs/_build/html/
```

## Questions?

- Open an issue for questions
- Check existing documentation
- Review closed issues and PRs for similar cases

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.

---

Thank you for contributing to genro-storage!
