# BRW-006 Test Plan

T01 perfect synthetic → PASS
T02 metadata/Zarr frame mismatch → FAIL
T03 missing Zarr group → FAIL
T04 all-zero frame → critical
T05 constant frame → warning
T06 DC offset outlier
T07 RMS outlier
T08 P2P outlier
T09 low adjacent correlation
T10 large elapsed gap
T11 non-monotonic elapsed
T12 unknown rails + repeated extremes → POSSIBLE_SATURATION only
T13 known ADC rails synthetic → rail-hit metrics
T14 JSON Pydantic contract
T15 HTML required sections
T16 eight figures exist/non-empty
T17 input immutability
T18 current real data: 3999 × 1250, sampling_rate_hz=null, no Hz/μs output
