# Testing Guide

This guide explains how to run tests for genro-storage, both locally and in CI/CD.

## Quick Start

The simplest way to run tests is using Make commands:

```bash
# Run all tests (auto-starts Docker services)
make test

# Run only unit tests (no Docker needed)
make test-unit

# Run only integration tests
make test-integration

# Run all tests with coverage report
make test-all

# Show available commands
make help
```

## Requirements

### For Unit Tests
- Python 3.12+
- pip packages: `pip install -e ".[dev]"`

### For Integration Tests
- Docker Desktop (macOS) or Docker Engine (Linux)
- docker compose (v2 plugin)

## Test Organization

```
tests/
├── conftest.py                     # Shared fixtures and helpers
├── test_local_storage.py           # Unit tests (no Docker)
├── test_config_grammar.py          # Unit tests, StorageConfig grammar (no Docker)
├── test_encryption.py              # Unit tests, at-rest encryption (no Docker)
├── test_notebooks.py               # Executes the notebooks/ tutorials (no Docker)
├── test_s3_integration.py          # Integration tests (requires MinIO)
├── test_additional_backends.py     # Integration tests (GCS, WebDAV, Azure)
├── test_new_backends.py            # Integration tests (SMB, SFTP)
└── ...
```

## Running Tests

### Option 1: Using Make (Recommended)

```bash
# Install dependencies
pip install -e ".[dev]"

# Run all tests
make test

# Run with coverage
make test-all
```

### Option 2: Using Scripts Directly

```bash
# Start services
bash scripts/start_test_services.sh

# Run tests
pytest tests/ -v

# Stop services
bash scripts/stop_test_services.sh
```

### Option 3: Manual Docker Management

```bash
# Start all services
docker compose -f tests/docker-compose.yml up -d

# Check services status
docker compose -f tests/docker-compose.yml ps

# Run tests
pytest tests/ -v

# Stop services
docker compose -f tests/docker-compose.yml down
```

## Test Services

The following Docker services are required for integration tests:

| Service | Port | Purpose | Container Name |
|---------|------|---------|----------------|
| **MinIO** | 9000, 9001 | S3-compatible storage | genro-storage-minio |
| **fake-gcs-server** | 4443 | Google Cloud Storage emulator | genro-storage-fake-gcs |
| **WebDAV** | 8080 | WebDAV server | genro-storage-webdav |
| **Azurite** | 10000-10002 | Azure Storage emulator | genro-storage-azurite |
| **Samba** | 139, 445 | SMB/CIFS file sharing | genro-storage-samba |
| **SFTP** | 2222 | SSH file transfer | genro-storage-sftp |

### Service Credentials

- **MinIO**: minioadmin / minioadmin
- **SFTP**: testuser / testpass
- **Samba**: testuser / testpass
- **WebDAV**: testuser / testpass
- **Azurite**: Uses well-known dev credentials
- **fake-gcs**: No authentication (anonymous)

## Test Markers

Tests are marked with pytest markers:

```bash
# Run only unit tests (no Docker)
pytest tests/ -v -m "not integration"

# Run only integration tests (requires Docker)
pytest tests/ -v -m integration
```

## CI/CD Integration

### GitHub Actions

Tests run automatically on GitHub via `.github/workflows/tests.yml`:

- Starts all required Docker services
- Runs unit and integration tests
- Uploads coverage to Codecov

### Local CI Simulation

To simulate CI behavior locally:

```bash
# Make sure Docker is running
make services-start

# Run tests like CI does
pytest tests/ -v -m "not integration" --cov=genro_storage
pytest tests/ -v -m integration --cov=genro_storage --cov-append
```

## Troubleshooting

### Services Not Starting

```bash
# Check Docker is running
docker ps

# View service logs
docker compose -f tests/docker-compose.yml logs minio
docker compose -f tests/docker-compose.yml logs fake-gcs
docker compose -f tests/docker-compose.yml logs webdav

# Restart all services
make services-stop
make services-start
```

### Port Conflicts

If you get port conflicts (e.g., port 8080 already in use):

```bash
# Find what's using the port
lsof -i :8080

# Kill the process or change ports in tests/docker-compose.yml
```

### Tests Skipping

If tests are being skipped when services are running:

```bash
# Check services are actually accessible
curl http://localhost:9000/minio/health/live  # MinIO
curl http://localhost:4443/storage/v1/b       # fake-gcs
curl http://localhost:8080                    # WebDAV
nc -zv localhost 10000                        # Azurite
nc -zv localhost 2222                         # SFTP
```

### Clean Up

```bash
# Stop services and clean up everything
make clean

# Or manually
docker compose -f tests/docker-compose.yml down -v
rm -rf .pytest_cache htmlcov .coverage
```

## Coverage Reports

After running tests with coverage:

```bash
# Generate HTML report
pytest tests/ --cov=genro_storage --cov-report=html

# Open in browser
open htmlcov/index.html
```

## Best Practices

1. **Always run unit tests first** - They're fast and catch most issues
2. **Use Make commands** - They handle service management automatically
3. **Check service health** - If tests fail, verify services are healthy
4. **Clean up regularly** - Use `make clean` to reset everything
5. **Watch logs** - Use `docker compose -f tests/docker-compose.yml logs -f [service]` to debug

## Environment Variables

You can customize test behavior with environment variables:

```bash
# Use different MinIO endpoint
export MINIO_ENDPOINT=http://localhost:9000

# Custom MinIO credentials
export MINIO_ACCESS_KEY=your_key
export MINIO_SECRET_KEY=your_secret

# Run tests
pytest tests/
```

## Development Workflow

Recommended workflow for development:

```bash
# 1. Start services once
make services-start

# 2. Run tests repeatedly during development
pytest tests/test_your_feature.py -v

# 3. When done, stop services
make services-stop
```

Or use watch mode for continuous testing:

```bash
# Install pytest-watch
pip install pytest-watch

# Start services
make services-start

# Watch for changes and re-run tests
ptw tests/ -- -v
```

## Manual Service Access

Access services directly for debugging:

- **MinIO Console**: http://localhost:9001
- **fake-gcs API**: http://localhost:4443/storage/v1/b
- **WebDAV**: http://localhost:8080 (testuser/testpass)

## Questions?

For issues or questions:
- Check the logs: `docker compose -f tests/docker-compose.yml logs [service]`
- Verify services: `make services-status`
- Clean and restart: `make clean && make services-start`
- Open an issue on GitHub
