# Human Review Checklist

- [ ] Adapter did not copy parser logic
- [ ] Registry has no giant if/elif dispatcher
- [ ] importer groups by modality
- [ ] one modality with multiple assets is one adapter call
- [ ] plan mode performs zero writes
- [ ] unsupported modality not silently ignored
- [ ] one modality failure does not erase successful result
- [ ] existing outputs not silently overwritten
- [ ] E001 resolves to ElectricalAdapter
- [ ] U001 resolves to UltrasoundAdapter
- [ ] BRW-003/005 tests still pass
- [ ] no synchronization code added
