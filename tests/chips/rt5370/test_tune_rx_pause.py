"""``_tune`` must pause the RX reader thread across a channel change: ``chan.set_channel``
stops/restarts the HW RX queue and rewrites ~30 RFCSR/BBP/MAC registers over the control
endpoint, and a bulk-IN URB still in flight on the reader's own thread during that window is
the rt5572/rtl8821cu-documented "RF/BBP writes don't latch" wedge — it later surfaces as a
dead RX pipe that the reader's error-streak counter misreports as the adapter having been
unplugged (the repro: channel hopping reliably trips it a few hops in). Mirrors the rt5572
"stop_queue + pause RX reader across deliberate tunes" fix; no hardware needed here."""
from unittest.mock import MagicMock

import pytest

import wifit3.chips.rt5370.driver as drv


def _driver(monkeypatch) -> drv.RT5370Driver:
    d = drv.RT5370Driver(MagicMock())
    d._chip = object()
    d._eeprom = object()
    return d


def test_tune_pauses_reader_before_and_resumes_after(monkeypatch):
    d = _driver(monkeypatch)
    calls: list = []
    reader = MagicMock()
    reader.pause.side_effect = lambda: calls.append("pause") or True
    reader.resume.side_effect = lambda: calls.append("resume")
    d._reader = reader
    monkeypatch.setattr(drv.chan, "set_channel",
                         lambda *a, **k: calls.append("set_channel"))
    monkeypatch.setattr(drv.chan, "config_lna_gain", lambda ev, ch: 0)

    d._tune(2)

    assert calls == ["pause", "set_channel", "resume"]


def test_tune_resumes_reader_even_if_set_channel_raises(monkeypatch):
    d = _driver(monkeypatch)
    reader = MagicMock()
    d._reader = reader
    monkeypatch.setattr(drv.chan, "set_channel",
                         lambda *a, **k: (_ for _ in ()).throw(RuntimeError("wedged")))
    monkeypatch.setattr(drv.chan, "config_lna_gain", lambda ev, ch: 0)

    with pytest.raises(RuntimeError):
        d._tune(2)

    reader.pause.assert_called_once()
    reader.resume.assert_called_once()          # never left stuck paused


def test_tune_tolerates_no_reader_yet(monkeypatch):
    """The very first tune in connect() runs before self._reader is created."""
    d = _driver(monkeypatch)
    d._reader = None
    monkeypatch.setattr(drv.chan, "set_channel", lambda *a, **k: None)
    monkeypatch.setattr(drv.chan, "config_lna_gain", lambda ev, ch: 0)

    d._tune(1)          # must not raise
