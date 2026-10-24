# Changelog

## 0.8.4 — 2026-10-24

- Add the `version_aware` option to `s3` mounts (#84). It defaults to `True`,
  as before. With `False`, delete, list, copy and move work on S3-compatible
  servers without `ListObjectVersions`, such as Garage, and the versioning
  capabilities report `False`.

## 0.8.3 — 2026-10-24

First published release with the 0.8.2 changes below.

- Rename the publishing workflow to `publish.yml`, matching the PyPI trusted
  publisher and the other Genro repositories.
- Run the S3 integration tests against RustFS instead of MinIO, whose images
  were removed from Docker Hub.

## 0.8.2 — 2026-10-24 (tagged, not published to PyPI)

- Replace files atomically on the `local` backend (#83). `write_bytes`,
  `write_text` and `open()` in a `w` mode write to a temporary file in the
  destination directory, fsync it and move it onto the destination with
  `os.replace`. Concurrent readers see the complete old or the complete new
  content. An existing destination keeps its permission bits; an error inside
  the `open()` block leaves the destination untouched. Modes `a`, `x` and `r+`
  still write in place.
- Require genro-bag and genro-builders >=0.27.0 and genro-toolbox >=0.14.0.
  Document keeping Genro modules on the latest stable releases in development.

## 0.8.1 — 2026-09-08

- Fetch StorageNode attributes through one backend metadata snapshot. On S3,
  uncached file attributes now require one HEAD request instead of four.
- Return no fabricated modification timestamp for implicit S3 directories in
  `ext_attributes`, matching the legacy tuple. The separate `mtime()` method
  keeps its previous behavior.
- Preserve compatibility with other backends through a default implementation,
  and delegate snapshots through relative mounts without losing path scoping.
- Add real legacy/current S3 contract tests, metadata regression tests, a local
  MinIO/remote S3 benchmark harness, and portable HTML comparison reports.
- Make pytest import this checkout's source instead of an installed distribution.

Local exploratory measurements for file attributes improved from 6.70 ms to
1.52 ms; legacy measured 3.27 ms in the final comparison. These measurements
are workload-specific and do not establish production or remote S3 performance.
Copy and move paths are unchanged.

See [previous releases](https://github.com/genropy/genro-storage/releases)
for earlier release notes.
