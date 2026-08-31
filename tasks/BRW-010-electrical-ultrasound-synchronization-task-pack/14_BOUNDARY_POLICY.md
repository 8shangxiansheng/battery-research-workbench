# Boundary Policy

Boundary diagnostics may use:

```text
duplicate timestamp
cycle transition
step transition
explicit start/end marker
```

But boundary information must never alter nearest-time matching.

Example:

```text
two duplicate rows at 15:41:31
```

Even if one is Cycle 1 end and one is Cycle 2 start:

BRW-010 does not choose one by cycle semantics.

It reports:

```text
candidate_record_count = 2
sync_ambiguous = true
boundary_flag = true
```
