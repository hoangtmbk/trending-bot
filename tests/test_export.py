import pytest

from interfaces.web.export import slugify


class TestSlugify:
    def test_basic_lowercase(self):
        assert slugify("Hello World") == "hello-world"

    def test_collapses_non_alphanumeric_runs(self):
        assert slugify("Foo!!! Bar??? Baz") == "foo-bar-baz"

    def test_strips_leading_trailing_dashes(self):
        assert slugify("---weird---title---") == "weird-title"

    def test_truncates_to_50_chars(self):
        long = "a" * 80
        result = slugify(long)
        assert len(result) == 50

    def test_truncate_does_not_leave_trailing_dash(self):
        # 49 a's + space + bbbbb → naive slice gives 'a'*49 + '-' (trailing dash)
        result = slugify(("a" * 49) + " bbbbb")
        assert result == "a" * 49

    def test_empty_input_returns_empty(self):
        assert slugify("") == ""

    def test_only_punctuation_returns_empty(self):
        assert slugify("!!!---???") == ""

    def test_unicode_treated_as_non_alphanumeric(self):
        # Keep it ASCII-only — unicode chars become dashes.
        assert slugify("café résumé") == "caf-r-sum"
