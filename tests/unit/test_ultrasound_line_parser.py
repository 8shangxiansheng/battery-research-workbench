import pytest

from battery_workbench.io.ultrasound.custom_txt import (
    UltrasoundFormatError,
    parse_ultrasound_line,
)


def test_parse_ultrasound_line_contract() -> None:
    waveform = " ".join(str(i) for i in range(1250))
    tail = " ".join("0" for _ in range(16))
    line = f"7;0;70.031;28000 78;{waveform};{tail}\n"

    frame = parse_ultrasound_line(line, line_number=9)

    assert frame.frame_index_raw == 7
    assert frame.source_line_index == 9
    assert frame.elapsed_time_s == 70.031
    assert (frame.unknown_meta_0, frame.unknown_meta_1) == ("28000", "78")
    assert len(frame.waveform) == 1250
    assert frame.waveform[0] == 0
    assert frame.waveform[-1] == 1249
    assert len(frame.unknown_tail) == 16


@pytest.mark.parametrize(
    ("line", "failed_field"),
    [
        ("0;0;0;1 2;3", "sections"),
        ("0;0;0;1 2;3;4;5", "sections"),
        (
            "0;0;0;1;"
            + " ".join("1" for _ in range(1250))
            + ";"
            + " ".join("0" for _ in range(16)),
            "unknown_meta_pair",
        ),
        (
            "0;0;0;1 2;"
            + " ".join("1" for _ in range(1249))
            + ";"
            + " ".join("0" for _ in range(16)),
            "waveform",
        ),
        (
            "0;0;0;1 2;"
            + " ".join("1" for _ in range(1251))
            + ";"
            + " ".join("0" for _ in range(16)),
            "waveform",
        ),
        (
            "0;0;0;1 2;"
            + " ".join("1" for _ in range(1250))
            + ";"
            + " ".join("0" for _ in range(15)),
            "unknown_tail",
        ),
        (
            "0;0;0;1 2;"
            + " ".join("1" for _ in range(1250))
            + ";"
            + " ".join("0" for _ in range(17)),
            "unknown_tail",
        ),
        (
            "0;0;0;1 2;"
            + "bad "
            + " ".join("1" for _ in range(1249))
            + ";"
            + " ".join("0" for _ in range(16)),
            "waveform",
        ),
    ],
)
def test_invalid_line_has_full_context(line: str, failed_field: str) -> None:
    with pytest.raises(UltrasoundFormatError) as caught:
        parse_ultrasound_line(
            line,
            asset_id="U_TEST",
            source_file="sample.txt",
            line_number=12,
        )

    message = str(caught.value)
    assert "asset_id=U_TEST" in message
    assert "file=sample.txt" in message
    assert "line=12" in message
    assert f"field={failed_field}" in message
