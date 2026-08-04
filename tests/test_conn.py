from __future__ import annotations

import base64
import textwrap

import pytest

from pytest_mh.conn import Bash, Powershell


def _ps_encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _ps_script(body: str) -> str:
    return f"$ProgressPreference = 'SilentlyContinue'\n{body}"


@pytest.mark.parametrize(
    "input, expected",
    [
        ("echo hello world", "echo hello world"),
        ('echo "hello world"', 'echo "hello world"'),
        ("echo 'hello world'", "echo '\"'\"'hello world'\"'\"'"),
    ],
    ids=[
        "no-quotes",
        "double-quotes",
        "single-quotes",
    ],
)
def test_conn__shell_bash__script(input: str, expected: str):
    shell = Bash()

    assert shell.name == "bash"
    assert shell.shell_command == "/usr/bin/env bash -c"

    cmd = shell.build_command_line(input, cwd=None, env={})
    assert cmd == f"{shell.shell_command} '{expected}'"


def test_conn__shell_bash__cwd():
    shell = Bash()

    assert shell.name == "bash"
    assert shell.shell_command == "/usr/bin/env bash -c"

    cmd = shell.build_command_line("echo hello world", cwd="/home/test", env={})
    expected = textwrap.dedent("""
        cd /home/test

        echo hello world
        """).strip()
    assert cmd == f"{shell.shell_command} '{expected}'"


def test_conn__shell_bash__env():
    shell = Bash()

    assert shell.name == "bash"
    assert shell.shell_command == "/usr/bin/env bash -c"

    cmd = shell.build_command_line("echo hello world", cwd=None, env={"HELLO": "WORLD", "JOHN": "DOE"})
    expected = textwrap.dedent("""
        export HELLO=WORLD
        export JOHN=DOE

        echo hello world
        """).strip()
    assert cmd == f"{shell.shell_command} '{expected}'"


def test_conn__shell_bash__cwd_env():
    shell = Bash()

    assert shell.name == "bash"
    assert shell.shell_command == "/usr/bin/env bash -c"

    cmd = shell.build_command_line("echo hello world", cwd="/home/test", env={"HELLO": "WORLD", "JOHN": "DOE"})
    expected = textwrap.dedent("""
        export HELLO=WORLD
        export JOHN=DOE
        cd /home/test

        echo hello world
        """).strip()
    assert cmd == f"{shell.shell_command} '{expected}'"


@pytest.mark.parametrize(
    "input",
    [
        "Write-Output hello world",
        'Write-Output "hello world"',
        "Write-Output 'hello world'",
    ],
    ids=[
        "no-quotes",
        "double-quotes",
        "single-quotes",
    ],
)
def test_conn__shell_powershell__script(input: str):
    shell = Powershell()

    assert shell.name == "powershell"
    assert shell.shell_command == "powershell -NonInteractive -OutputFormat Text -EncodedCommand"

    cmd = shell.build_command_line(input, cwd=None, env={})
    assert cmd == f"{shell.shell_command} {_ps_encoded(_ps_script(input))}"


def test_conn__shell_powershell__cwd():
    shell = Powershell()

    assert shell.name == "powershell"
    assert shell.shell_command == "powershell -NonInteractive -OutputFormat Text -EncodedCommand"

    cmd = shell.build_command_line("Write-Output hello world", cwd="/home/test", env={})
    expected = _ps_script(textwrap.dedent("""
        cd /home/test

        Write-Output hello world
        """).strip())
    assert cmd == f"{shell.shell_command} {_ps_encoded(expected)}"


def test_conn__shell_powershell__env():
    shell = Powershell()

    assert shell.name == "powershell"
    assert shell.shell_command == "powershell -NonInteractive -OutputFormat Text -EncodedCommand"

    cmd = shell.build_command_line("Write-Output hello world", cwd=None, env={"HELLO": "WORLD", "JOHN": "DOE"})
    expected = _ps_script(textwrap.dedent("""
        $Env:HELLO = WORLD
        $Env:JOHN = DOE

        Write-Output hello world
        """).strip())
    assert cmd == f"{shell.shell_command} {_ps_encoded(expected)}"


def test_conn__shell_powershell__cwd_env():
    shell = Powershell()

    assert shell.name == "powershell"
    assert shell.shell_command == "powershell -NonInteractive -OutputFormat Text -EncodedCommand"

    cmd = shell.build_command_line("echo hello world", cwd="/home/test", env={"HELLO": "WORLD", "JOHN": "DOE"})
    expected = _ps_script(textwrap.dedent("""
        $Env:HELLO = WORLD
        $Env:JOHN = DOE
        cd /home/test

        echo hello world
        """).strip())
    assert cmd == f"{shell.shell_command} {_ps_encoded(expected)}"


def test_conn__shell_powershell__sanitize_stderr_progress_only():
    shell = Powershell()
    ns = "http://schemas.microsoft.com/powershell/2004/04"
    clixml = "\n".join(
        [
            "#< CLIXML",
            f'<Objs Version="1.1.0.1" xmlns="{ns}">'
            '<Obj S="progress" RefId="0">'
            '<TN RefId="0"><T>System.Management.Automation.PSCustomObject</T>'
            "<T>System.Object</T></TN>"
            '<MS><I64 N="SourceId">1</I64>'
            '<PR N="Record"><AV>Loading Active Directory module</AV>'
            "<AI>0</AI><Nil /><PI>-1</PI><PC>100</PC>"
            "<T>Completed</T><SR>-1</SR><SD> </SD></PR></MS></Obj></Objs>",
        ]
    )
    assert shell.sanitize_stderr(clixml.splitlines()) == []


def test_conn__shell_powershell__sanitize_stderr_keeps_errors():
    shell = Powershell()
    ns = "http://schemas.microsoft.com/powershell/2004/04"
    clixml = "\n".join(
        [
            "#< CLIXML",
            f'<Objs Version="1.1.0.1" xmlns="{ns}">'
            '<Obj S="progress" RefId="0">'
            '<TN RefId="0"><T>System.Management.Automation.PSCustomObject</T>'
            "<T>System.Object</T></TN>"
            '<MS><I64 N="SourceId">1</I64>'
            '<PR N="Record"><AV>Loading Active Directory module</AV>'
            "<AI>0</AI><Nil /><PI>-1</PI><PC>100</PC>"
            "<T>Completed</T><SR>-1</SR><SD> </SD></PR></MS></Obj>"
            '<S S="Error">Get-ADComputer : Cannot find an object '
            "with identity: 'client'._x000D__x000A_</S>"
            '<S S="Error">At line:2 char:1_x000D__x000A_</S></Objs>',
        ]
    )
    assert shell.sanitize_stderr(clixml.splitlines()) == [
        "Get-ADComputer : Cannot find an object with identity: 'client'.",
        "At line:2 char:1",
    ]
