from __future__ import annotations

import fnmatch
import io
import shutil
import secrets
import tempfile
import warnings
from pathlib import Path
from typing import Generator, Iterable, Union, Optional, NoReturn, cast

import invoke  # type: ignore

PathLike = Union["FabricPath", Path, str]


def raise_(exc: Exception) -> NoReturn:
    raise exc

class FabricPath:
    def __init__(self, path: PathLike, runner: Optional[invoke.Runner] = None) -> None:
        self.path: Path
        self.runner: invoke.Runner
        if isinstance(path, FabricPath):
            self.path = path.path
            self.runner = path.runner
        elif isinstance(path, Path):
            self.path = path
            self.runner = runner if runner else invoke.Local(invoke.Context())
        elif isinstance(path, str):
            self.path = Path(path)
            self.runner = runner if runner else invoke.Local(invoke.Context())
        else:
            raise TypeError(f"Don't know {type(path)}")

    def __str__(self) -> str:
        return str(self.path)

    def __truediv__(self, other: Union[str, Path]) -> FabricPath:
        return FabricPath(self.path / other, self.runner)

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
    def rmtree(cls, path: PathLike) -> None:
        fpath = FabricPath(path)
        fpath.runner.run(f"rm -rf {path!s}", hide="stdout")

    @classmethod
    def _move_or_copy(cls, move: bool, source: PathLike, dest: PathLike) -> None:
        if isinstance(source, FabricPath) and isinstance(dest, FabricPath):
            if source.runner == dest.runner:
                source.runner.run(
                    f"{'mv' if move else 'cp'} {source!s} {dest!s}", hide="stdout"
                )
            else:
                tmp = Path(tempfile.gettempdir()) / secrets.token_hex(16)
                cls._move_or_copy(move, source, tmp)
                cls._move_or_copy(move, tmp, dest)
        elif isinstance(source, FabricPath) and hasattr(source.runner, "get"):
            source.runner.get(str(source.path), str(dest))
            if move:
                source.unlink()
        elif isinstance(dest, FabricPath) and hasattr(dest.runner, "put"):
            dest.runner.put(str(source), str(dest.path))
            if move:
                assert not isinstance(source, FabricPath)
                Path(source).unlink()
        else:
            if move:
                shutil.move(str(source), str(dest))
            else:
                shutil.copy(str(source), str(dest))

    @classmethod
    def copy(cls, source: PathLike, dest: PathLike) -> None:
        cls._move_or_copy(False, source, dest)

    @classmethod
    def move(cls, source: PathLike, dest: PathLike) -> None:
        cls._move_or_copy(True, source, dest)

    def iterdir(self) -> Generator[FabricPath, None, None]:
        proc = self.runner.run(f"ls {self!s}", hide="stdout")
        for filename in proc.stdout.split("\n"):
            if filename:
                yield self / filename

    @property
    def parent(self) -> FabricPath:
        return FabricPath(self.path.parent, self.runner)

    @property
    def name(self) -> str:
        return self.path.name

    def rmdir(self) -> None:
        self.runner.run(f"rmdir {self!s}", hide="stdout")

    def cast(self) -> Path:
        return cast(Path, self)

    def unlink(self) -> None:
        self.runner.run(f"rm {self!s}", hide="stdout")

    def is_relative_to(self, other: PathLike) -> bool:
        return self.path.is_relative_to(FabricPath(other).path)

    def resolve(self) -> FabricPath:
        proc = self.runner.run(f"realpath {self!s}", hide="stdout")
        return FabricPath(proc.stdout, self.runner)

    def symlink_to(self, other: PathLike) -> None:
        fother = FabricPath(other)
        if self.runner != fother.runner:
            raise ValueError("Cannot symlink paths on different runners {self} {fother}.")
        self.runner.run(f"ln -s {fother!s} {self!s}")

    @staticmethod
    def copytree(source: PathLike, dest: PathLike) -> None:
        if isinstance(source, (Path, str)) and isinstance(dest, (Path, str)):
            shutil.copytree(source, dest)
        else:
            fsource = FabricPath(source)
            fdest = FabricPath(dest)
            tarball = "tmp.tar.gz"
            fsource.runner.run(f"tar --directory={fsource!s} --create --gzip --file {fsource.parent!s}/{tarball} .", hide="stdout")
            fdest.mkdir(parents=True)
            FabricPath.move(fsource.parent / tarball, fdest / tarball)
            fdest.runner.run(f"tar --directory={fdest!s} --extract --gunzip --file {fdest!s}/{tarball}", hide="stdout")
            (fdest / tarball).unlink()
