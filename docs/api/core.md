# Core API

::: app.core.config

::: app.core.security

::: app.core.image_security

## ZIP upload validation

ZIP validation checks archive structure and size limits, rejects unsafe paths and symlinks, verifies the model file type, and applies the supported-file rules before a conversion job is queued. The implementation is in [`app/core/zip_security.py`](https://github.com/ismayilovh/ARDesign-Server/blob/expert-panel-dev/fastapi_app/app/core/zip_security.py).
