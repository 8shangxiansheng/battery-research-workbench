# Human Review Checklist

- [ ] event count == aligned row count
- [ ] event id unique
- [ ] no waveform samples in events parquet
- [ ] exact locator join only
- [ ] no merge_asof / nearest matching
- [ ] ambiguous events remain
- [ ] ambiguous electrical state null
- [ ] candidate relation retained
- [ ] frame 3998 remains ambiguous
- [ ] sync_error/boundary not recomputed
- [ ] validated_sync remains false
- [ ] soc_dod_percent not renamed
- [ ] dq/dv remains raw
