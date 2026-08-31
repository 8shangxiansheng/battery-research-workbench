# Human Review Checklist

## Report
- [ ] JSON opens
- [ ] HTML opens
- [ ] status matches anomalies

## Figures
- [ ] Voltage vs time reasonable
- [ ] Current vs time reasonable
- [ ] Capacity vs time reasonable
- [ ] Temperature reasonable
- [ ] Cycle capacity consistent
- [ ] Step timeline shows expected order
- [ ] dQ/dV not silently smoothed

## Current known facts
- [ ] 2 cycles
- [ ] 10 steps
- [ ] 12 duplicate timestamps reported, not deleted
- [ ] boundary duplicate risk visible

## Integrity
- [ ] input Parquet SHA256 unchanged
- [ ] BRW-003 parser not unnecessarily modified

## Scope
- [ ] no ultrasound
- [ ] no sync
- [ ] no ML
- [ ] no Agent/UI
