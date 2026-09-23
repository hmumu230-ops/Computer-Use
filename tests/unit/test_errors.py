"""Structured error model."""
import errors


def test_cuerror_shape():
    e = errors.StaleRef("gone", hint="re-snapshot")
    d = e.to_dict()
    assert d["code"] == "STALE_REF"
    assert d["message"] == "gone"
    assert d["hint"] == "re-snapshot"
    assert d["retryable"] is True


def test_confirm_required_carries_token():
    e = errors.ConfirmRequired("danger", token="tok123")
    d = e.to_dict()
    assert d["code"] == "CONFIRM_REQUIRED"
    assert d["confirmToken"] == "tok123"


def test_ambiguous_lists_candidates():
    e = errors.AmbiguousRef("two", candidates=["@e1", "@e2"])
    assert e.to_dict()["candidates"] == ["@e1", "@e2"]


def test_unsupported_compositor():
    e = errors.UnsupportedCompositor("no api", compositor="gnome")
    assert e.to_dict()["compositor"] == "gnome"


def test_generic_exception_normalized():
    d = errors.to_error_dict(ValueError("nope"))
    assert d["code"] == "INTERNAL"
    assert "nope" in d["message"]


def test_file_not_found_is_tool_missing():
    d = errors.to_error_dict(FileNotFoundError(2, "x", "xdotool"))
    assert d["code"] == "TOOL_NOT_FOUND"


def test_permission_error():
    d = errors.to_error_dict(PermissionError("denied"))
    assert d["code"] == "PERMISSION_REQUIRED"
