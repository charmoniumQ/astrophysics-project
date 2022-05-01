from __future__ import annotations

import fnmatch
import io
import shutil
import warnings
from pathlib import Path
from typing import Generator, Iterable, Union, cast

import invoke  # type: ignore


class FabricPath:
    def __init__(self, runner: invoke.Runner, path: Union[Path, str]) -> None:
        self.runner = runner
        self.path = path if isinstance(path, Path) else Path(path)

    def __str__(self) -> str:
        return str(self.path)

    def __truediv__(self, other: Union[str, Path]) -> FabricPath:
        return FabricPath(self.runner, self.path / other)

    def write_text(self, text: str) -> None:
        tmp_fileobj = io.BytesIO(text.encode())
        self.runner.put(tmp_fileobj, str(self))

    def read_text(self) -> str:
        tmp_fileobj = io.BytesIO()
        self.runner.get(str(self), tmp_fileobj)
        return tmp_fileobj.getvalue().decode()

    def mkdir(self, parents: bool = False, exist_ok: bool = True) -> None:
        if self.exists():
            if not exist_ok:
                raise FileExistsError(str(self))
        else:
            parents_arg = '--parents' if parents else ''
            self.runner.run(f"mkdir {parents_arg} {self!s}")

    def exists(self) -> bool:
        return bool(self.runner.run(f"ls {self!s}", hide="both", warn=True).exited == 0)

    @classmethod
    def rmtree(cls, path: Path) -> None:
        if isinstance(path, cls):
            path.runner.run(f"rm -rf {path!s}", hide="stdout")
        else:
            shutil.rmtree(path)

    @classmethod
    def _move_or_copy(
        cls, move: bool, source: Union[FabricPath, Path], dest: Union[FabricPath, Path]
    ) -> None:
        if isinstance(source, cls) and isinstance(dest, cls):
            if source.runner == dest.runner:
                source.runner.run(
                    f"{'mv' if move else 'cp'} {source!s} {dest!s}", hide="stdout"
                )
            else:
                # tmp = io.BytesIO()
                raise NotImplementedError
                tmp = Path(tempfile.gettempdir()) / secrets.token_hex(16)
                cls._move_or_copy(move, source, tmp)
                cls._move_or_copy(move, tmp, dest)
        elif isinstance(source, cls):
            source.runner.get(str(source), str(dest))
            if move:
                source.unlink()
                source.runner.run(f"rm {source!s}", hide="stdout")
        elif isinstance(dest, cls):
            dest.runner.put(str(source), str(dest))
            if move:
                source.unlink()
        else:
            assert isinstance(source, Path) and isinstance(dest, Path)
            if move:
                shutil.move(source, dest)
            else:
                shutil.copy(source, dest)

    @classmethod
    def copy(cls, source: Path, dest: Path) -> None:
        cls._move_or_copy(False, source, dest)

    @classmethod
    def move(cls, source: Path, dest: Path) -> None:
        cls._move_or_copy(True, source, dest)

    def iterdir(self) -> Generator[FabricPath, None, None]:
        proc = self.runner.run(f"ls {self!s}", hide="stdout")
        for filename in proc.stdout.split("\n"):
            if filename:
                yield self / filename

    @property
    def parent(self) -> FabricPath:
        return FabricPath(self.runner, self.path.parent)

    @property
    def name(self) -> str:
        return self.path.name

    def rmdir(self) -> None:
        self.runner.run(f"rmdir {self!s}", hide="stdout")

    def cast(self) -> Path:
        return cast(Path, self)

    def unlink(self) -> None:
        self.runner.run(f"rm {self!s}", hide="stdout")

    def is_relative_to(self, other: Union[FabricPath, Path]) -> None:
        if isinstance(other, FabricPath):
            return self.path.is_relative_to(other.path)
        else:
            return self.path.is_relative_to(other)

    def resolve(self) -> FabricPath:
        proc = self.runner.run(f"realpath {self!s}", hide="stdout")
        return FabricPath(self.runner, proc.stdout)

    def symlink_to(self, other: FabricPath) -> None:
        if self.runner != other.runner:
            raise ValueError("Cannot symlink paths on different runners {self} {other}.")
        self.runner.run(f"ln -s {other!s} {self!s}")
