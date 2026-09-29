"""``read_rx_burst`` must treat an empty-channel read timeout as "no data" (return None), not a
fault, on every OS. The RX reader gives up after 5 consecutive raised errors, so a misclassified
timeout on a quiet channel fired a bogus "Adapter disconnected" — on macOS the errno is 60
(ETIMEDOUT/BSD), which the old ``err in (110, 10060)`` check missed. A genuine device loss
(NO_DEVICE) is not a timeout and must still propagate."""
import usb.core
from unittest.mock import MagicMock

import pytest

from wifit3.chips.rt5370.rx import read_rx_burst


def _dev_raising(exc: Exception) -> MagicMock:
    dev = MagicMock()
    dev.read.side_effect = exc
    return dev


def _usberror(msg: str, backend_code, errno) -> usb.core.USBError:
    return usb.core.USBError(msg, backend_code, errno)


# Messages are chosen to isolate each guard: the "no message" rows carry a string with neither
# "timeout" nor "timed out", so they pass ONLY if the numeric guard (backend code / errno) fires.
@pytest.mark.parametrize("msg, backend_code, errno", [
    ("Operation timed out", -7, 60),    # macOS/BSD, the reported bug (all three guards)
    ("libusb0-win32 error", None, 60),  # macOS errno alone (no libusb code, no timeout text)
    ("pipe stalled", -7, None),         # libusb LIBUSB_ERROR_TIMEOUT code alone
    ("resource unavailable", None, 110),   # Linux ETIMEDOUT errno alone
    ("resource unavailable", None, 10060),  # Windows WSAETIMEDOUT errno alone
])
def test_timeout_returns_none(msg, backend_code, errno):
    dev = _dev_raising(_usberror(msg, backend_code, errno))
    assert read_rx_burst(dev, 0x81) is None


def test_success_returns_bytes():
    dev = MagicMock()
    dev.read.return_value = b"\x01\x02\x03"
    assert read_rx_burst(dev, 0x81) == b"\x01\x02\x03"


def test_device_gone_propagates():
    # NO_DEVICE (unplug) is not a timeout: read_rx_burst must re-raise so the reader's
    # is_device_gone path fires, not swallow it as an empty read.
    dev = _dev_raising(_usberror("No such device", -4, 19))
    with pytest.raises(usb.core.USBError):
        read_rx_burst(dev, 0x81)
