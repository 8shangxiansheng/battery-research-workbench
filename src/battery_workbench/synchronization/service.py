"""High-level synchronization service.

Planned public API:

    synchronize_experiment(
        experiment_id,
        electrical_records,
        ultrasound_frames,
        assets,
        config,
    ) -> list[MeasurementEvent]

The implementation is intentionally deferred until BRW-008–BRW-011, after both
modality parsers have passed their acceptance gates.
"""
