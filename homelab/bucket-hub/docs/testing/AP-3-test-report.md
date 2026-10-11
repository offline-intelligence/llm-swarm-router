# AP-3 test report

## Run log

```bash
cd homelab/bucket-hub && PYTHONPATH=. uv run --with pytest pytest tests/ -q
```

| When | Result |
|------|--------|
| Before (AP-2) | 124 passed |
| After (AP-3) | 146 passed in 3.1s |

## Automated tests (new)

| File | Coverage |
|------|----------|
| `test_repo_lane.py` | §T1 lane separation + `/api/repo-lane` |
| `test_repo_archive_paths.py` | §T2 paths, slug, partial guard |
| `test_repo_archive_github.py` | §T2 mount defer, idempotent, clone, size cap, provenance |

## Manual smoke (Finn)

See `cursor-github-hf-downloader.md` §T6 steps 1–5.
