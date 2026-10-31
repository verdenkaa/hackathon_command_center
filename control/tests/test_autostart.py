from pathlib import Path

from control.autostart import command


def test_autostart_is_absolute_and_handles_spaces():
    args = command(Path("D:/Project With Spaces"))
    assert args[-1] == "--no-browser"
    assert str(args[-2]).replace("\\", "/") == "D:/Project With Spaces"
    assert Path(args[1]).is_absolute()
