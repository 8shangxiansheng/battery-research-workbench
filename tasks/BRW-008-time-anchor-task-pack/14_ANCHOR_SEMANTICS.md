# Anchor Semantics

## File start anchor

If:

```text
file_start_time = T0
```

and the elapsed clock is defined relative to file acquisition zero:

```text
frame candidate time = T0 + elapsed
```

Current first frame elapsed is not zero.

Therefore:

```text
T0
```

must not be relabeled as the first frame timestamp.

---

## Provisional

Means:

```text
there is an explicit, usable anchor source
```

not:

```text
cross-modal synchronization has been scientifically verified
```

---

## Plausible

Means:

```text
derived coverage is compatible with reference windows under configured diagnostics
```

not:

```text
each ultrasound frame is matched to the correct electrical event
```
