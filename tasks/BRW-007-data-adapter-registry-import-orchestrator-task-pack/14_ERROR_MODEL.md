# Recommended Import Error Model

Suggested codes:

```text
EXPERIMENT_NOT_FOUND
BATTERY_NOT_FOUND
UNSUPPORTED_MODALITY
DUPLICATE_ADAPTER_REGISTRATION
ADAPTER_FAILURE
INVALID_ASSET_GROUP
ALREADY_IMPORTED
OUTPUT_EXISTS
```

Recommended fields:

```text
code
message
battery_id
experiment_id
modality
asset_ids
adapter_name
```

Do not hide errors as plain logging only.
