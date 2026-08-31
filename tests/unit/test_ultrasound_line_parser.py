from battery_workbench.io.ultrasound.custom_txt import parse_ultrasound_line


def test_parse_ultrasound_line_contract() -> None:
    waveform = " ".join(str(i) for i in range(1250))
    tail = " ".join("0" for _ in range(16))
    line = f"7;0;70.031;28000 78;{waveform};{tail}\n"

    frame = parse_ultrasound_line(line)

    assert frame.frame_index == 7
    assert frame.elapsed_time_s == 70.031
    assert frame.unknown_meta_pair == ("28000", "78")
    assert len(frame.waveform) == 1250
    assert frame.waveform[0] == 0
    assert frame.waveform[-1] == 1249
    assert len(frame.unknown_tail) == 16
