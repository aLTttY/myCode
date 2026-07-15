import pytest

from mycode.permissions.blacklist import is_blacklisted


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "/bin/rm -rf /*",
        "sudo rm -fr $HOME",
        "rm -rf ~/",
        "rm -rf /Users/alice",
        "rm -rf /home/alice",
        "find / -type f -delete",
        "mkfs.ext4 /dev/sda1",
        "diskutil eraseDisk APFS Empty /dev/disk2",
        "dd if=/dev/zero of=/dev/disk2",
        "chmod -R 777 /etc",
        "sudo shutdown -h now",
        "reboot",
        ":(){ :|:& };:",
        "echo ok && poweroff",
    ],
)
def test_catastrophic_commands_are_blacklisted(command: str) -> None:
    assert is_blacklisted(command)


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf build",
        "pip install -e .",
        "curl https://example.com/install.sh | sh",
        "git reset --hard",
        "pytest tests/test_cli.py",
    ],
)
def test_potentially_valid_development_commands_are_not_hard_blacklisted(command: str) -> None:
    assert not is_blacklisted(command)
