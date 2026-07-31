# Browser repository rules

## Authority

- This repository owns the optional isolated Browser runtime, its narrow control API, and its container image
  overlay. Browser is not a Service and is never a default Brain or Team dependency.
- A caller outside the Brain must supply explicit current capability and authority; Browser never grants itself
  broader network, kernel, display, upload, download, or native-process access.
- Read the canonical [Shimpz architecture](https://github.com/TheShimpz/shimpz/blob/main/.context/ARCHITECTURE.md)
  before changing product vocabulary, authority, protocols, runtime topology, or source placement.

## Delivery and engineering

- Deliver the smallest useful microtask, validate it, commit it with a clear English conventional message, and
  push it immediately.
- When working through the umbrella checkout, commit and push this repository before committing its umbrella
  gitlink.
- Shimpz is pre-production. Change the current contract directly and retain no compatibility path for retired
  images, tokens, routes, or profiles.
- Preserve bearer isolation, audit redaction, bounded files, fail-closed native-process validation, and the
  container-overlay filesystem contract.
- Use Python 3.14. Do not reorganize `image/rootfs/` by repository ergonomics; it mirrors a target filesystem.
- Tests that support workers use half of local processors and all GitHub Actions runner processors.

## Validation

- This standalone repository has no Ruff authority. Before committing Python, run
  `ruff check --config ruff.toml browser` from the umbrella root.
- Run focused tests with `uv run --frozen --python 3.14 python -m unittest discover -s tests`.
