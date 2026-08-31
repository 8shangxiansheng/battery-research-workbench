"""Clock-drift models.

V1 synchronization starts with offset-only matching.
If sync error changes systematically with elapsed time, P4 may enable:
    electrical_time = a + b * ultrasound_time
or piecewise clock models.
"""
