# Electrical Enrichment Policy

Use exact selected electrical locator only.

Never use timestamp equality, nearest timestamp, merge_asof, cycle/step guessing.

Recommended whitelist：cycle_index_raw, step_index_raw, step_type, voltage_v, current_a, capacity_ah, charge_capacity_ah, discharge_capacity_ah, energy_wh, power_w, temperature_c, soc_dod_percent, contact_resistance_mohm, dq_dv_raw.

Actual names follow current BRW-003 canonical schema.
