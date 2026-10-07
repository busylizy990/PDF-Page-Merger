"""Regression tests for the installed-copy crash of 2 October 2026.

`writable_output_dir()` used `os.access(folder, os.W_OK)`, which on Windows
reflects only the read-only attribute and ignores ACLs -- it calls
C:\\Program Files writable. The fallback it existed to provide was therefore
unreachable, and an installed copy died with an unhandled PermissionError from
mkdir on the first merge without -o.

These tests pin the behaviour, not the implementation: given a place it cannot
write, the function must choose somewhere else rather than hand back the bad path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import merge


class TestCanWriteDir:
    def test_true_for_a_writable_folder(self, tmp_path):
        assert merge.can_write_dir(tmp_path) is True

    def test_creates_the_folder_if_it_is_missing(self, tmp_path):
        target = tmp_path / "not" / "there" / "yet"
        assert merge.can_write_dir(target) is True
        assert target.is_dir()

    def test_leaves_no_probe_file_behind(self, tmp_path):
        assert merge.can_write_dir(tmp_path) is True
        assert list(tmp_path.iterdir()) == []

    def test_false_when_the_folder_cannot_exist(self, tmp_path):
        """Parent is a file, so mkdir raises -- stands in for a denied ACL."""
        blocker = tmp_path / "a-file"
        blocker.write_text("not a directory", encoding="utf-8")
        assert merge.can_write_dir(blocker / "output") is False

    def test_false_rather_than_raising_for_nonsense(self):
        assert merge.can_write_dir(Path("\\\\?\\Z:\\nope\\nowhere")) is False


class TestWritableOutputDir:
    def test_prefers_the_tools_own_output_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(merge, "OUTPUT_DIR", tmp_path / "output")
        monkeypatch.setattr(merge, "BASE", tmp_path)
        assert merge.writable_output_dir() == tmp_path / "output"

    def test_falls_back_when_its_own_folder_is_unusable(self, tmp_path, monkeypatch):
        """The Program Files case. This is the regression: it must NOT return
        OUTPUT_DIR and leave the caller's mkdir to explode."""
        blocker = tmp_path / "read-only-install"
        blocker.write_text("stands in for a folder you cannot write to", encoding="utf-8")
        unusable = blocker / "output"

        home = tmp_path / "home"
        monkeypatch.setattr(merge, "OUTPUT_DIR", unusable)
        monkeypatch.setattr(merge, "BASE", blocker)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

        chosen = merge.writable_output_dir()

        assert chosen != unusable
        assert chosen == home / "Documents" / "PDF Page Merger"
        assert chosen.is_dir(), "the chosen folder should be ready to write into"

    def test_the_chosen_folder_is_actually_writable(self, tmp_path, monkeypatch):
        """What the caller does next is mkdir then open(..., 'wb'); both must work."""
        blocker = tmp_path / "blocked"
        blocker.write_text("x", encoding="utf-8")
        home = tmp_path / "home"
        monkeypatch.setattr(merge, "OUTPUT_DIR", blocker / "output")
        monkeypatch.setattr(merge, "BASE", blocker)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

        chosen = merge.writable_output_dir()
        chosen.mkdir(parents=True, exist_ok=True)
        (chosen / "merged.pdf").write_bytes(b"%PDF-1.7\n")
        assert (chosen / "merged.pdf").is_file()

    def test_falls_through_to_temp_when_nothing_else_works(self, tmp_path, monkeypatch):
        import tempfile

        blocker = tmp_path / "blocked"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(merge, "OUTPUT_DIR", blocker / "output")
        monkeypatch.setattr(merge, "BASE", blocker)
        # A home directory that cannot hold anything either.
        monkeypatch.setattr(Path, "home", staticmethod(lambda: blocker / "nohome"))

        chosen = merge.writable_output_dir()
        assert chosen == Path(tempfile.gettempdir()) / "PDF Page Merger"


class TestSettingsPathFallback:
    """The same os.access bug left the window silently unable to save settings."""

    def test_uses_the_folder_beside_the_tool_when_writable(self, gui, tmp_path, monkeypatch):
        monkeypatch.setattr(gui, "BASE", tmp_path)
        assert gui.settings_path() == tmp_path / gui.SETTINGS_NAME

    def test_falls_back_to_the_profile_when_it_is_not(self, gui, tmp_path, monkeypatch):
        blocker = tmp_path / "program-files"
        blocker.write_text("x", encoding="utf-8")
        profile = tmp_path / "appdata"
        monkeypatch.setattr(gui, "BASE", blocker)
        monkeypatch.setenv("APPDATA", str(profile))

        chosen = gui.settings_path()

        assert chosen != blocker / gui.SETTINGS_NAME
        assert chosen == profile / "PDF Page Merger" / gui.SETTINGS_NAME

    def test_and_settings_can_then_actually_be_saved(self, gui, tmp_path, monkeypatch):
        """save_settings swallows OSError, so a wrong path looks like success
        while silently losing every preference. Prove the file appears."""
        blocker = tmp_path / "program-files"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(gui, "BASE", blocker)
        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

        assert gui.save_settings({"image_page": "a4"}) is True
        assert gui.load_settings()["image_page"] == "a4"
