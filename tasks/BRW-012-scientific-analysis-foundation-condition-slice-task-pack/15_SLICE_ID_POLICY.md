# Slice ID Policy

Canonical ID is deterministic over:

```text
measurement_events input checksum
+
normalized ConditionSliceSpec
```

Normalize list values with sort + dedupe + canonical serialization.

Do not use a random UUID as canonical slice identity.
