from pathlib import Path

from openpyxl import Workbook

from battery_workbench.io.electrical.custom_excel import inspect_electrical_workbook


def test_inspect_electrical_workbook(tmp_path: Path) -> None:
    path = tmp_path / "sample.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "record"
    ws.append(["数据序号", "电压(V)"])
    ws.append([1, 3.5])
    wb.create_sheet("cycle")
    wb.save(path)

    result = inspect_electrical_workbook(path)

    assert result.sheets["record"].rows == 2
    assert result.sheets["record"].columns == 2
    assert "cycle" in result.sheets
