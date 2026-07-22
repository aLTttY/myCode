from pathlib import Path

from mycode.instructions import InstructionLoader


def test_instruction_priority_and_include(tmp_path: Path) -> None:
    user = tmp_path / "home" / ".mycode"
    user.mkdir(parents=True)
    (user / "MYCODE.md").write_text("user", encoding="utf-8")
    (tmp_path / "MYCODE.md").write_text("root\n@include shared.md\n", encoding="utf-8")
    (tmp_path / "shared.md").write_text("shared", encoding="utf-8")
    (tmp_path / ".mycode").mkdir()
    (tmp_path / ".mycode" / "MYCODE.md").write_text("local", encoding="utf-8")

    bundle = InstructionLoader().load(tmp_path, user)

    assert bundle.content.index("local") < bundle.content.index("root") < bundle.content.index("user")
    assert "shared" in bundle.content


def test_instruction_rejects_cycle_and_escape(tmp_path: Path) -> None:
    (tmp_path / "MYCODE.md").write_text("@include a.md\n@include ../secret.md\n", encoding="utf-8")
    (tmp_path / "a.md").write_text("@include MYCODE.md\n", encoding="utf-8")

    bundle = InstructionLoader().load(tmp_path, tmp_path / "home")

    assert {warning.code for warning in bundle.warnings} == {"cycle", "outside_scope"}


def test_instruction_stops_at_sixth_nested_include(tmp_path: Path) -> None:
    (tmp_path / "MYCODE.md").write_text("@include level-1.md\n", encoding="utf-8")
    for level in range(1, 7):
        next_line = f"@include level-{level + 1}.md\n" if level < 6 else "too deep"
        (tmp_path / f"level-{level}.md").write_text(next_line, encoding="utf-8")

    bundle = InstructionLoader().load(tmp_path, tmp_path / "home")

    assert "too deep" not in bundle.content
    assert any(warning.code == "max_depth" for warning in bundle.warnings)


def test_instruction_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text("hidden", encoding="utf-8")
    (tmp_path / "linked.md").symlink_to(outside)
    (tmp_path / "MYCODE.md").write_text("@include linked.md\n", encoding="utf-8")

    bundle = InstructionLoader().load(tmp_path, tmp_path / "home")

    assert "hidden" not in bundle.content
    assert any(warning.code == "symlink_escape" for warning in bundle.warnings)
