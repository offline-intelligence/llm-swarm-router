# AP-4 test report: `huggingface_repo`

## Run log

```bash
cd homelab/bucket-hub && PYTHONPATH=. uv run --with pytest --with huggingface_hub==0.26.2 pytest tests/ -q
```

| When | Result |
|------|--------|
| Before (AP-3.1 r4) | 193 passed |
| After (AP-4, PM run, Python 3.13) | **217 passed** (24 new). Without `huggingface_hub` installed, the 2 archiver-entry HF tests skip. |

## Automated tests (new, `tests/test_repo_archive_hf.py`)

| Test | Asserts |
|------|---------|
| `test_repo_id_and_type_from_url` | model URL, `/datasets/` URL, `repo_type` option, `hf:` prefix; Space and non-HF URLs rejected readably |
| `test_space_url_job_errors_readably` | Space job → `error` mentioning Spaces, no runner call |
| `test_hf_slug_layout` | `huggingface-daily/<day>/models__org__name` |
| `test_prefer_safetensors_patterns` | `.bin`/`.h5`/`.msgpack` ignored beside safetensors; explicit `allow_patterns` wins and keeps `README.md` |
| `test_dir_pattern_matches_like_huggingface_hub` | `onnx/` → `onnx/*` |
| `test_size_precheck_uses_filtered_siblings` | 2 GB `.bin` filtered out, 5 MB cap passes, runner called with ignore patterns |
| `test_size_cap_skip` | over cap → `done` "Skipped: …", `skipped_too_large` index row, no runner call |
| `test_gated_error_text` | archiver `gated` → licence message, partial removed |
| `test_metadata_not_found_error` | API refusal → "Repository not found or private" |
| `test_card_front_matter` | `license`, `base_model`, `datasets`, `language` set; excerpt without front matter; token-shaped card text redacted |
| `test_simple_yaml_fallback_matches` | parser without PyYAML gives the same card fields |
| `test_scrub_free_text` | `Bearer …`, `token=…`, `ghp_…` redacted and pass `secret_scan` |
| `test_hf_mount_offline_defers` | TNAS offline → `queued`, `not_before`, nothing written, no metadata call |
| `test_hf_temp_then_rename` | `.partial-<id>` work dir, final folder with `snapshot/`, `README.md`, sidecars; download pinned to metadata `sha` |
| `test_hf_idempotent` | second job → "Already archived on", `refresh` downloads again |
| `test_hf_post_check_over_cap` | measured > 110 % of cap → error, partial removed |
| `test_hf_token_not_in_argv` | `HF_TOKEN` only in the env file; argv `hf_snapshot <repo> <spec>`; 12 h timeout; Gluetun network |
| `test_docker_runner_maps_gated_exit` | exit 3 + `error_kind: gated` → `ArchiverError.kind == "gated"` |
| `test_partial_guard_accepts_hf_root` | partial guard allows `huggingface-daily`, still refuses other parents |
| `test_entry_hf_snapshot_args_and_card` | entry passes repo type, pinned revision, patterns, token; copies card |
| `test_entry_hf_error_kinds` | `GatedRepoError` → gated, `RepositoryNotFoundError` → not_found |
| `test_pi_hf_url_auto_is_huggingface_repo_without_drive` | huggingface.co URL + Auto → `huggingface_repo`, no drive needed, claimed by the `repo` lane |
| `test_pi_legacy_hf_keeps_drive_path` | legacy `hf` goes through the drive check again (it needs `destination_path`) |
| `test_worker_dispatches_huggingface_repo` | repo pool runs the HF handler and frees the slot |

## Fixes found while building AP-4

- **Legacy `hf` and `github` jobs had lost their destination (since AP-3).** `create_job` sent every repo-lane kind down the "no drive" branch, so `run_hf_job` hit `KeyError: 'destination_path'`. Only the archive-root kinds (`github_repo`, `huggingface_repo`, `github_release`) and meta kinds skip the drive now.
- **README text could fail the index secret scan.** A card or README with `token=…` or `Bearer …` in a code sample raised `IndexSecretError` and errored the job. Excerpts are now scrubbed first (`scrub_free_text`), for GitHub too.

## LFS pointer inference (spec AP-4 "before writing code")

Code reading: legacy `hf` whole-repo mode runs `git clone --depth 1` in `GIT_IMAGE` with no LFS step, so weight files would be LFS pointers (≈130-byte text files).

**QC r1 (2026-10-12):** job `14835f682592` at `/mnt/media/Media/SmokeTest/tiny-random-gpt2/` — `model.safetensors` 453864 B, `pytorch_model.bin` 3561811 B; `starts_with_lfs_pointer: false` (real weights, not LFS text).

## Manual acceptance (§T6 step 6 + error paths)

`scripts/smoke-ap4-hf.sh` (fake Hub: 7/7).

| Check | Result (QC r1 / r1b) |
|-------|------------------------|
| Integrate (217 tests, draft PR #6) | **pass** (r1) |
| Pi/worker parity + image `:4` build | **pass** (r1) |
| Pi `hub-form.service` reload + kind detect | **pass** (r1b) |
| `smoke-ap4-hf.sh` | **7/7 pass** (r1b) |
| `live.hf_real_weights` (453864 B safetensors, LFS 0) | **pass** (r1b) |

QC: `docs/pm/2026-10/qc/AP-4-r1.json` (**blocked** env only); `docs/pm/2026-10/qc/AP-4-r1b.json` (**overall pass**).
