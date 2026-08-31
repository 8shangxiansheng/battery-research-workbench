# Synchronization Engine

P4 target:

```text
ultrasound absolute time
= electrical experiment start time + ultrasound elapsed_time_s
```

Then match to the nearest electrical record and expose `sync_error_s`.

Do not hide synchronization error.
