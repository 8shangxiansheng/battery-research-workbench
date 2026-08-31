# Current upstream facts to verify during execution

The Coding Agent must verify these again from installed packages / upstream docs.

As of task-pack creation:

## cellpy

- current releases require Python >=3.13
- has `neware_txt`
- documented Neware example is CSV-oriented
- `custom` loader can use csv/xls/xlsx query methods

## BEEP

- current release 2026.2.7
- Python >=3.11
- officially lists Neware among supported cyclers

Important:

“supports Neware” does not prove direct support for the current multi-sheet XLSX.

That is exactly what OSI-001 must test.
