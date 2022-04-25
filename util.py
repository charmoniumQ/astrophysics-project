from typing import Sequence, Mapping, Union, Optional, BinaryIO
import itertools
import textwrap
import shlex
import os
import re
import subprocess
from pathlib import Path
import datetime

def common_ancestor(path0: Path, path1: Path) -> Path:
    if path0.is_absolute() != path1.is_absolute():
        raise ValueError("path0 and path1 should both be absolute or both be relative.")
    for i, (part0, part1) in enumerate(itertools.zip_longest(path0.parts, path1.parts)):
        if part0 != part1:
            break
    ret = Path(path0.parts[0]).joinpath(*path0.parts[1:i])
    assert ret.is_relative_to(path0) and ret.is_relative_to(path1)
    return ret

def relative_to(dest: Path, source: Path) -> Path:
    ancestor = common_ancestor(dest, source)
    for _ in range(len(ancestor.parts) - len(source.parts)):
        source = source / ".."
    assert source.resolve() == ancestor
    return source / dest.relative_to(ancestor)

class CalledProcessError(Exception):
    # unfortunately, Exception is not compatible with @dataclass
    def __init__(
            self,
            args: Sequence[str],
            cwd: Path,
            env: Mapping[str, str],
            stdout: Union[str, bytes],
            stderr: Union[str, bytes],
            returncode: int,
    ) -> None:
        self.args2 = args
        self.cwd = cwd
        self.env = env
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

    def __str__(self) -> str:
        env_var_str = shlex.join(
            f"{key}={val}"
            for key, val in self.env.items()
            if key not in os.environ or os.environ[key] != val
        )
        if env_var_str:
            env_var_str += " "
        cwd_str = f"-C {shlex.quote(str(self.cwd))} " if self.cwd.resolve() != Path().resolve() else ""
        env_cmd_str = f"env {cwd_str}{env_var_str}" if env_var_str or cwd_str else ""
        cmd_str = f"{env_cmd_str}{shlex.join(self.args2)}"
        stdout_str = self.stdout if isinstance(self.stdout, str) else self.stdout.decode()
        stderr_str = self.stderr if isinstance(self.stderr, str) else self.stderr.decode()
        stdout_fmt = ("\nstdout:\n" + textwrap.indent(stdout_str, "  ")) if self.stdout is not None else ""
        stderr_fmt = ("\nstderr:\n" + textwrap.indent(stderr_str, "  ")) if self.stderr is not None else ""

        return f"""Command returned non-zero exit status {self.returncode}\ncommand: {cmd_str}{stdout_fmt}{stderr_fmt}"""


def subprocess_run(
    cmd: Sequence[Union[Path, str, int]],
    cwd: Optional[Union[Path, str]] = None,
    check: bool = True,
    env: Optional[Mapping[str, str]] = None,
    env_override: Optional[Mapping[str, str]] = None,
    capture_output: bool = True,
    stdout: Optional[BinaryIO] = None,
    text: bool = True,
) -> Union[subprocess.CompletedProcess[bytes], subprocess.CompletedProcess[str]]:
    """Wrapper around of subprocess.run.

    I will progressively port arguments by need.

    env_override is a mapping used to update (not replace) env.

    If the subprocess's returns non-zero and the return code is
    checked (`subprocess_run(..., check=True)`), all captured output
    is dumped.

    """

    cmd2 = list(map(str, cmd))
    env = dict(env if env is not None else os.environ)
    cwd = (cwd if isinstance(cwd, Path) else Path(cwd)) if cwd is not None else Path()
    if env_override:
        env.update(env_override)

    proc = subprocess.run(cmd2, env=env, cwd=cwd, capture_output=capture_output, stdout=stdout, text=text)

    if check:
        if proc.returncode != 0:
            raise CalledProcessError(
                cmd2, cwd, env, proc.stdout, proc.stderr, proc.returncode
            )
    return proc

format_directives_invalid_for_timedeltas = \
    "%a %A %w %d %b %B %m %y %U %W %c %x %X %G %u %V".split(" ")

def strftimedelta(time_delta: datetime.timedelta, format_string: str) -> str:
    """format a positive timedelta

    Borrowed from datetime.datetime.strftime, with the following changes:
    - %D: the total number of days.
    - %Y: the total number of years (not zero padded).
    - %j: the remaining number of days after %Y years (not zero padded).

    """

    if time_delta < datetime.timedelta():
        raise ValueError("Cannot format a negative timedelta")

    for directive in format_directives_invalid_for_timedeltas:
        if directive in format_string:
            raise ValueError(f"Invalid directive {directive} in format string {format_string}")

    years, days_modulo_year = divmod(time_delta.days, 365)
    format_string = (
        format_string
        .replace("%D", str(time_delta.days))
        .replace("%j", str(days_modulo_year))
        .replace("%Y", str(years))
    )

    midnight_on_arbitrary_day = datetime.datetime(year=1, month=1, day=1)

    # Note that I have disallowed references to the current month and current week.
    # I have already handled references to the day, year, and day of the year.
    # Only the units of time less than a day remain.
    # These can be handled by strftime.

    return (midnight_on_arbitrary_day + time_delta).strftime(format_string)

def strptimedelta(time_string: str, format_string: str) -> datetime.timedelta:
    return datetime.datetime.strptime(time_string, format_string) - datetime.datetime.strptime("", "")


import contextlib
from typing import TypeVar, Union, Generic, Generator
import pickle

T = TypeVar("T")
class PersistentObject(Generic[T]):
    @contextlib.contextmanager
    def transaction(self) -> Generator[T, None, None]:
        assert self.path.exists()
        obj = pickle.loads(self.path.read_bytes())
        yield obj
        self.path.write_bytes(pickle.dumps(obj))
        del obj

    def __init__(self, default: T, path: Union[str, Path]) -> None:
        self.path = Path(path)
        if not self.path.exists():
            self.path.write_bytes(pickle.dumps(default))
