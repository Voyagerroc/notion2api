
from app.patcher import (
    compute_hash,
    generate_diff,
    rollback_patch,
    safe_apply_patch,
)


def test_compute_hash():
    h1 = compute_hash("hello world\n")
    h2 = compute_hash("hello world\n")
    h3 = compute_hash("hello world\r\n")
    assert h1 == h2
    assert h1 != h3


def test_generate_diff():
    diff = generate_diff("line1\nline2\n", "line1\nline_new\n", filename="test.py")
    assert "-line2" in diff
    assert "+line_new" in diff


def test_safe_apply_patch_valid(tmp_path):
    target = tmp_path / "valid.py"
    target.write_text("x = 1\n", encoding="utf-8")
    orig_hash = compute_hash("x = 1\n")

    ok, msg = safe_apply_patch(
        str(target),
        "x = 2\n",
        original_hash=orig_hash,
        auto_approve=True,
    )
    assert ok is True
    assert "başarıyla güncellendi" in msg
    assert target.read_text(encoding="utf-8") == "x = 2\n"

    # Backup should exist
    backup = tmp_path / "valid.py.bak"
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "x = 1\n"


def test_safe_apply_patch_syntax_error(tmp_path):
    target = tmp_path / "syntax_err.py"
    target.write_text("a = 10\n", encoding="utf-8")

    # Invalid python code: missing colon or unmatched bracket
    ok, msg = safe_apply_patch(
        str(target),
        "def bad_syntax(\n",
        auto_approve=True,
    )
    assert ok is False
    assert "Syntax hatası" in msg
    # Target file should not be modified
    assert target.read_text(encoding="utf-8") == "a = 10\n"


def test_safe_apply_patch_hash_mismatch(tmp_path):
    target = tmp_path / "mismatch.py"
    target.write_text("initial = 1\n", encoding="utf-8")

    ok, msg = safe_apply_patch(
        str(target),
        "initial = 2\n",
        original_hash="wrong_hash_value",
        auto_approve=True,
    )
    assert ok is False
    assert "Güvenlik uyarısı" in msg
    assert target.read_text(encoding="utf-8") == "initial = 1\n"


def test_rollback_patch(tmp_path):
    target = tmp_path / "rollback_target.py"
    target.write_text("version = 1\n", encoding="utf-8")

    # Apply patch
    safe_apply_patch(str(target), "version = 2\n", auto_approve=True)
    assert target.read_text(encoding="utf-8") == "version = 2\n"

    # Rollback
    ok, _ = rollback_patch(str(target), auto_approve=True)
    assert ok is True
    assert target.read_text(encoding="utf-8") == "version = 1\n"
