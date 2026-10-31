from unittest.mock import Mock

from control.desktop import DesktopLifecycle


def test_close_button_hides_window_without_stopping_services():
    window, shutdown = Mock(), Mock()
    lifecycle = DesktopLifecycle(window, shutdown)
    assert lifecycle.on_closing() is False
    window.hide.assert_called_once()
    shutdown.assert_not_called()
    lifecycle.show()
    window.show.assert_called_once()
    window.restore.assert_called_once()


def test_exit_destroys_only_after_successful_service_shutdown():
    window, shutdown = Mock(), Mock(return_value=True)
    lifecycle = DesktopLifecycle(window, shutdown)
    lifecycle.quit()
    shutdown.assert_called_once()
    window.destroy.assert_called_once()
    assert lifecycle.on_closing() is True


def test_failed_shutdown_keeps_window_available():
    window, shutdown = Mock(), Mock(return_value=False)
    lifecycle = DesktopLifecycle(window, shutdown)
    lifecycle.quit()
    window.destroy.assert_not_called()
    assert lifecycle.on_closing() is False


def test_application_branding_has_window_and_tray_sizes():
    import struct
    from control.icon import ICON_DIR
    icon=(ICON_DIR / 'hub.ico').read_bytes()
    assert icon[:4]==b'\x00\x00\x01\x00'
    count=struct.unpack_from('<H',icon,4)[0]
    sizes={(icon[6+i*16] or 256,icon[7+i*16] or 256) for i in range(count)}
    assert {(16,16),(32,32),(256,256)} <= sizes
    png=(ICON_DIR / 'hub.png').read_bytes()
    assert struct.unpack_from('>II',png,16)==(256,256)
