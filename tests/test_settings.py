"""settings.json is untrusted input.

It is hand-editable and travels between machines, and a malformed `presets` value
once crashed the window on startup before it could draw anything. These tests
feed it the shapes that broke it.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def settings_file(gui, tmp_path, monkeypatch):
    """Point the window's settings at a scratch file."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(gui, "settings_path", lambda: path)
    return path


class TestLoadSettings:
    def test_missing_file_is_not_an_error(self, gui, settings_file):
        assert gui.load_settings() == {}

    @pytest.mark.parametrize(
        "content",
        [
            "",
            "   ",
            "not json at all",
            "{",
            '{"presets": }',
            "\x00\x01\x02",
        ],
    )
    def test_corrupt_content_gives_an_empty_dict_rather_than_raising(
        self, gui, settings_file, content
    ):
        settings_file.write_text(content, encoding="utf-8")
        assert gui.load_settings() == {}

    @pytest.mark.parametrize("payload", ["a string", "123", "[1, 2, 3]", "null", "true"])
    def test_valid_json_of_the_wrong_shape_is_rejected(self, gui, settings_file, payload):
        """The file must contain an object. A bare list or string is not one."""
        settings_file.write_text(payload, encoding="utf-8")
        assert gui.load_settings() == {}

    def test_a_good_file_round_trips(self, gui, settings_file):
        assert gui.save_settings({"image_page": "letter"}) is True
        assert gui.load_settings()["image_page"] == "letter"

    def test_utf8_bom_is_tolerated(self, gui, settings_file):
        """A Save As from Notepad adds one."""
        settings_file.write_text(
            json.dumps({"image_page": "a4"}), encoding="utf-8-sig"
        )
        assert gui.load_settings().get("image_page") == "a4"


class TestCleanPreset:
    @pytest.mark.parametrize(
        "junk", ["a string", 123, None, ["a", "list"], True]
    )
    def test_anything_that_is_not_an_object_is_dropped(self, gui, junk):
        """This is the shape that crashed startup."""
        assert gui.clean_preset(junk) is None

    def test_an_empty_object_is_dropped(self, gui):
        assert gui.clean_preset({}) is None

    def test_unknown_fields_are_stripped(self, gui):
        cleaned = gui.clean_preset({"index": True, "something_invented": "xyz"})
        assert cleaned == {"index": True}

    def test_booleans_must_really_be_booleans(self, gui):
        assert gui.clean_preset({"index": "yes"}) is None
        assert gui.clean_preset({"index": 1}) is None
        assert gui.clean_preset({"index": False}) == {"index": False}

    def test_stamp_position_is_checked_against_the_real_list(self, gui):
        import merge

        good = next(iter(merge.STAMP_SPOTS))
        assert gui.clean_preset({"stamp_at": good}) == {"stamp_at": good}
        assert gui.clean_preset({"stamp_at": "middle-of-nowhere"}) is None

    def test_image_page_is_checked(self, gui):
        assert gui.clean_preset({"image_page": "a4"}) == {"image_page": "a4"}
        assert gui.clean_preset({"image_page": "a5"}) is None

    def test_empty_strings_are_not_kept(self, gui):
        assert gui.clean_preset({"index_title": ""}) is None
        assert gui.clean_preset({"index_title": "Index"}) == {"index_title": "Index"}

    def test_a_realistic_preset_survives_intact(self, gui):
        preset = {
            "index": True,
            "index_title": "Index",
            "stamp": True,
            "stamp_format": "{n}",
            "stamp_at": "bottom-center",
            "image_page": "match",
        }
        assert gui.clean_preset(preset) == preset

    def test_one_bad_field_does_not_discard_the_good_ones(self, gui):
        cleaned = gui.clean_preset({"index": True, "image_page": "nonsense"})
        assert cleaned == {"index": True}


class TestBuiltInPresets:
    def test_they_survive_their_own_cleaner(self, gui):
        """A built-in that the cleaner would reject would be an own goal."""
        for name, preset in gui.BUILT_IN_PRESETS.items():
            assert gui.clean_preset(preset) == preset, f"{name} does not round-trip"
