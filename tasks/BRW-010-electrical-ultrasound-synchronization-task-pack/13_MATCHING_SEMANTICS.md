# BRW-010 Matching Semantics

## Unique

```text
exactly one nearest electrical record
and
error <= tolerance
```

## Ambiguous

```text
more than one nearest electrical record
```

Reasons:

```text
duplicate same timestamp
equidistant timestamp groups
or both
```

## Out of tolerance

Nearest candidates exist,
but minimum error exceeds policy threshold.

## Candidate preservation

Candidates are evidence.

They are never deleted merely because
the summary row cannot select a unique record.
