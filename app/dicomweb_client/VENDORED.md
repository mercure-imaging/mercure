# Vendored: `dicomweb_client`

| | |
|---|---|
| Upstream | https://github.com/ImagingDataCommons/dicomweb-client |
| Version vendored | **0.60.1** |
| Source artifact | `dicomweb_client-0.60.1-py3-none-any.whl` (PyPI) |
| Wheel URL | https://pypi.org/project/dicomweb-client/0.60.1/ |
| License | MIT — see [`LICENSE`](LICENSE) (Copyright 2020 MGH Computational Pathology) |
| Vendored on | 2026-10-26 |
| Local modifications | [`MERCURE.patch`](MERCURE.patch) (Pillow made optional) |

## Why this is vendored instead of installed

`dicomweb-client` hard-requires `pillow>=8.3` in every release up to and including 0.61.2.
Mercure has **no** use for Pillow: nothing in `app/`, `tests/`, `getdcmtags/`, docs or templates
imports `PIL`. Pillow is only reached because `dicomweb_client/api.py` re-exports
`DICOMfileClient` from `file.py`, the single module that imports Pillow — and only for
rendered-frame retrieval, which mercure never calls.

Carrying Pillow cost mercure **104 Dependabot alert rows / 52 advisories**, including 4 criticals
(FPX/TIFF/JPEG heap overflows, Ghostscript argument injection), all of which required a Python
≥3.11 runtime upgrade to patch, because `Pillow 13.0.0` dropped Python 3.10.

Vendoring without Pillow removes that entire cluster. See `DEPENDABOT_TRIAGE.md` in the repo root.

## What was taken, what was dropped

Taken (9,295 lines): `__init__.py`, `api.py`, `file.py`, `log.py`, `protocol.py`,
`session_utils.py`, `uri.py`, `web.py`.

Dropped: `cli.py` (console entry point, unused) and `ext/gcp/` (Google auth, unused — the only
remaining `google` references in `session_utils.py` are inside a deprecated shim that defers its
import and is never called by mercure).

## Local modifications (`MERCURE.patch`)

`file.py` only:

1. `from PIL import Image` / `from PIL.ImageCms import ...` moved into a `try/except ImportError`
   that sets `HAS_PIL`.
2. `_require_pil()` raises a clear `RuntimeError` when Pillow is absent; called at the top of
   `retrieve_instance_rendered`, `iter_instance_frames`, `retrieve_instance_frames`,
   `retrieve_instance_frames_rendered`.

With Pillow installed the guards are inert, so behaviour is unchanged. Without Pillow,
`store_instances`, `search_for_series`, `retrieve_series` and session construction all work.

Keep the diff minimal and keep `MERCURE.patch` regenerable:

```sh
# regenerate the patch after updating the vendored sources
diff -ru /tmp/pristine app/dicomweb_client --exclude=LICENSE --exclude=MERCURE.patch \
  > app/dicomweb_client/MERCURE.patch
```

## Runtime dependencies the vendored code needs

`numpy`, `pydicom`, `requests`, `retrying`, and `typing_extensions` (only for Python < 3.8).
These are **now declared explicitly in `app/requirements.in`** — they used to arrive transitively
through `dicomweb-client`. If you remove `dicomweb-client` from the manifests and forget these,
the vendored code fails at import time.

Python floor: the vendored code targets `>=3.9` (upstream 0.60.1 metadata); mercure runs 3.10.

## Updating this copy

```sh
pip download dicomweb-client==<version> --no-deps -d /tmp/dw
unzip -d /tmp/dw /tmp/dw/dicomweb_client-*.whl
# copy the 8 modules listed above over app/dicomweb_client/, re-apply MERCURE.patch,
# regenerate MERCURE.patch against a pristine copy, then run:
#   app/tests/test_dicomweb.py  and  app/tests/test_query.py   (the latter covers file:// targets)
```

Do **not** jump to 0.61.x casually: 0.61.x requires `pydicom>=3.0` while mercure pins
`pydicom ~= 2.4.1`.

## Security-review notes

* This tree is **not** scanned by Dependabot. When auditing third-party code, include
  `app/dicomweb_client/` explicitly.
* Upstream is still maintained (0.61.2 released 2026-08); this copy will drift until mercure
  migrates to pydicom 3. Re-check upstream advisories periodically:
  `pip index versions dicomweb-client` / GitHub security advisories for
  `ImagingDataCommons/dicomweb-client`.
* mercure's only consumer is `app/dispatch/target_types/dicomweb.py`
  (`DICOMfileClient`, `DICOMwebClient`, `set_http_retry_params`, `search_for_series`,
  `retrieve_series`, `store_instances`, `create_session_from_user_pass`).
