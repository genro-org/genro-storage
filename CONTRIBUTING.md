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

We use a **Git Flow** workflow with protected branches to ensure code quality and stability.

### Branch Structure

- **`main`**: Production-ready code. Protected branch, requires PR and review.
- **`develop`**: Integration branch for features. Protected branch, requires PR and review.
- **`feature/*`**: Feature development branches (e.g., `feature/add-webdav-backend`)
- **`bugfix/*`**: Bug fixes for develop branch
- **`hotfix/*`**: Urgent fixes for production (branched from main)
- **`release/*`**: Release preparation branches

### Branch Protection Rules

Both `main` and `develop` branches are protected:
- **No direct pushes** - All changes must go through Pull Requests
- **Required reviews** - At least 1 approving review required
- **No force pushes** - History cannot be rewritten
- **No deletions** - Branches cannot be deleted

### Working on Features

1. **Start from develop**:
   ```bash
   git checkout develop
   git pull origin develop
   ```

2. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

   Naming conventions:
   - `feature/add-webdav-backend`
   - `feature/improve-error-handling`
   - `bugfix/fix-s3-timeout`
   - `hotfix/critical-security-fix`

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
   - Go to GitHub and create a PR from your feature branch to `develop`
   - Fill in the PR template with a clear description
   - Link related issues (e.g., "Closes #15")
   - Wait for review and address feedback

### Release Process

When ready to release a new version:

1. **Create release branch** from `develop`:
   ```bash
   git checkout develop
   git checkout -b release/0.5.0
   ```

2. **Prepare release**:
   - Update version in `pyproject.toml`
   - Update `CHANGELOG.md`
   - Create release announcement
   - Run full test suite

3. **Merge to main**:
   - Create PR from `release/0.5.0` to `main`
   - After approval and merge, tag the release:
   ```bash
   git checkout main
   git tag -a v0.5.0 -m "Release version 0.5.0"
   git push origin v0.5.0
   ```

4. **Merge back to develop**:
   - Create PR from `main` to `develop` to sync changes
   - Delete release branch after merge

### Hotfix Process

For critical production issues:

1. **Branch from main**:
   ```bash
   git checkout main
   git checkout -b hotfix/critical-issue
   ```

2. **Fix and test** thoroughly

3. **Merge to both main and develop**:
   - Create PR to `main` first
   - After merge, create PR to `develop`
   - Tag the hotfix version

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

   Keep Genro modules on their latest stable releases. When reusing an existing
   environment, explicitly upgrade them (a normal install can keep older versions
   that still satisfy the minimum requirements):

   ```bash
   python -m pip install --upgrade genro-bag genro-builders genro-toolbox genro-tytx
   ```

   When updating dependencies, raise the Genro minimum versions in
   `pyproject.toml` to the latest verified releases.

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
black genro_storage/ tests/

# Lint
ruff check genro_storage/ tests/

# Type check
mypy genro_storage/
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
3. **Update CHANGELOG.md** with your changes
4. **Ensure all tests pass** and coverage is maintained
5. **Request review** from maintainers
6. **Address feedback** promptly and professionally
7. **Squash commits** if requested before merge

### PR Checklist

- [ ] Code follows project style guidelines
- [ ] Tests added/updated and passing
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
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

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to genro-storage!
