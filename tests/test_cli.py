"""Auto-detection in main.py — adb discovery and device pick."""
import pytest

import main
from src.device import AdbError


class TestFindAdb:
    def test_env_var_wins(self, monkeypatch):
        monkeypatch.setenv("ADB_PATH", r"X:\custom\adb.exe")
        assert main._find_adb() == r"X:\custom\adb.exe"

    def test_path_adb_when_no_env(self, monkeypatch):
        monkeypatch.delenv("ADB_PATH", raising=False)
        monkeypatch.setattr(main.shutil, "which", lambda _: r"C:\tools\adb.exe")
        assert main._find_adb() == "adb"

    def test_picks_newest_ldplayer(self, monkeypatch):
        monkeypatch.delenv("ADB_PATH", raising=False)
        monkeypatch.setattr(main.shutil, "which", lambda _: None)
        hits = [r"C:\LDPlayer\LDPlayer9\adb.exe", r"C:\LDPlayer\LDPlayer14\adb.exe"]
        monkeypatch.setattr(main.glob, "glob", lambda p: hits if "C:\\LDPlayer" in p else [])
        assert main._find_adb() == r"C:\LDPlayer\LDPlayer14\adb.exe"

    def test_falls_back_to_bare_adb(self, monkeypatch):
        monkeypatch.delenv("ADB_PATH", raising=False)
        monkeypatch.setattr(main.shutil, "which", lambda _: None)
        monkeypatch.setattr(main.glob, "glob", lambda _: [])
        assert main._find_adb() == "adb"


class TestDetectDevice:
    def test_prefers_tcp_over_dual_listed_emulator(self, monkeypatch):
        monkeypatch.setattr(main, "list_devices",
                            lambda adb: ["emulator-5556", "127.0.0.1:5557"])
        assert main._detect_device("adb", hint=None) == "127.0.0.1:5557"

    def test_probes_ports_when_nothing_attached(self, monkeypatch):
        calls = {"n": 0}
        connected = []

        def fake_list(adb):
            calls["n"] += 1
            return [] if calls["n"] == 1 else ["127.0.0.1:5557"]

        def fake_connect(address, adb):
            connected.append(address)
            if address != "127.0.0.1:5557":
                raise AdbError("nothing there")

        monkeypatch.setattr(main, "list_devices", fake_list)
        monkeypatch.setattr(main, "connect", fake_connect)
        assert main._detect_device("adb", hint=None) == "127.0.0.1:5557"
        assert "127.0.0.1:5555" in connected

    def test_hint_probed_first(self, monkeypatch):
        connected = []
        monkeypatch.setattr(main, "list_devices",
                            lambda adb: [] if not connected else ["127.0.0.1:5561"])
        monkeypatch.setattr(main, "connect",
                            lambda address, adb: connected.append(address))
        main._detect_device("adb", hint="127.0.0.1:5561")
        assert connected[0] == "127.0.0.1:5561"

    def test_none_when_no_device(self, monkeypatch):
        monkeypatch.setattr(main, "list_devices", lambda adb: [])
        monkeypatch.setattr(main, "connect",
                            lambda address, adb: (_ for _ in ()).throw(AdbError("no")))
        assert main._detect_device("adb", hint=None) is None

    def test_ambiguous_raises(self, monkeypatch):
        monkeypatch.setattr(main, "list_devices",
                            lambda adb: ["127.0.0.1:5555", "127.0.0.1:5557"])
        with pytest.raises(AdbError, match="multiple devices"):
            main._detect_device("adb", hint=None)
