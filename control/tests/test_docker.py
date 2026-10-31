from unittest.mock import Mock, patch
from pathlib import Path

from control.docker import Docker


def test_windows_keepalive_reuses_process_and_closes_only_owned_process():
    docker = Docker(Path.cwd(), "test")
    process = Mock()
    process.poll.return_value = None
    with patch("control.docker.os.name", "nt"), patch("control.docker.subprocess.Popen", return_value=process) as launch:
        docker.keep_alive()
        docker.keep_alive()
        assert launch.call_count == 1
        assert launch.call_args.args[0][-1] == "cat"
        docker.close()
        process.stdin.close.assert_called_once()
        process.wait.assert_called_once()
