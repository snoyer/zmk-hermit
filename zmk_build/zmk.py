from dataclasses import dataclass
import logging
import re
import subprocess
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CompilationItem:
    zmk_board: str
    """valid zmk board name, eg. `nice_nano_v2`"""
    shield_name: Optional[str]
    """shield name, without `_side` suffix, eg. `corne`"""
    shield_side: Optional[str]
    """side name for split shields, `left` or `right`"""

    @property
    def zmk_shield(self):
        """valid zmk shield name, with `_side` prefix for split shields,
        eg. `corne_left`"""
        if self.shield_name and self.shield_side:
            return f"{self.shield_name}_{self.shield_side}"
        elif self.shield_name:
            return self.shield_name
        else:
            return None

    def filename(self, tag: Optional[str] = None, alias: Optional[str] = None):
        basename = alias or join([self.shield_name, self.zmk_board], "-")
        if tag:
            basename += f"[{tag}]"
        return join([basename, self.shield_side], ".")

    @classmethod
    def Find(cls, board: str, shield: Optional[str], shield_dirs: Iterable[Path]):
        if shield:
            shield_path = find_dir(*(dir / shield for dir in shield_dirs))
            if shield_path:
                logger.debug(f"found shield `{shield}` at `{shield_path}`")

            if shield_path:
                sides = guess_split_shield_sides(shield_path, shield)
                if sides:
                    logger.debug(f'guessing shield is split ({", ".join(sides)})')
                    for side in sides:
                        yield cls(board, shield, side)
                else:
                    yield cls(board, shield, None)
            else:
                yield cls(board, shield, None)
        else:
            yield cls(board, None, None)


def guess_board_name(board_dir: Path):
    if board_dir.is_dir():
        for line in open(board_dir / "Kconfig.board"):
            if m := re.search(r"config BOARD_(\w+)", line):
                return m.group(1).lower()
    raise ValueError("could not guess board name")


def guess_board_type(board_dir: Path):
    if board_dir.is_dir():
        for child in board_dir.glob("*_defconfig"):
            if child.is_file():
                for line in open(child):
                    if m := re.search(r"CONFIG_(\w+)_MPU", line):
                        return m.group(1).lower()
    raise ValueError("could not guess board type")


def guess_shield_name(shield_dir: Path):
    if shield_dir.is_dir():
        for child in shield_dir.iterdir():
            if child.suffix == ".keymap":
                return child.stem
    return shield_dir.stem


def guess_split_shield_sides(shield_dir: Path, shield_name: str):
    def find_all():
        for line in open(shield_dir / "Kconfig.defconfig"):
            for m in re.findall(rf"SHIELD_{shield_name}_(\w+)", line, flags=re.I):
                yield str(m).lower()

    return set(find_all())


def find_dir(*candidates: Path) -> Optional[Path]:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate


def check_west_setup(zmk_app: Path):
    try:
        check_west_cmd = ["west", "--help", "build"]
        logger.debug(f"run `{subprocess.list2cmdline(check_west_cmd)}`")
        subprocess.check_call(
            check_west_cmd,
            cwd=zmk_app,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False
    except FileNotFoundError:
        return False


def run_west_setup(zmk_app: Path, dry_run:bool=False):
    west_init_cmd = ["west", "init", "-l", zmk_app]
    logger.info(f"run `{subprocess.list2cmdline(west_init_cmd)}`")
    try:
        if not dry_run:
            subprocess.check_call(west_init_cmd, cwd=zmk_app, text=True)
    except subprocess.CalledProcessError:
        pass


def run_west_update(zmk_app: Path, dry_run:bool=False):
    for west_update_cmd in [
        ["west", "update"],
        ["west", "zephyr-export"],
    ]:
        logger.info(f"run `{subprocess.list2cmdline(west_update_cmd)}`")
        if not dry_run:
            subprocess.check_call(west_update_cmd, cwd=zmk_app, text=True)


def west_build_command(
    board: str,
    shield: Optional[str] = None,
    app_dir: Optional[Path] = None,
    build_dir: Optional[Path] = None,
    bin_name: Optional[str] = None,
    zmk_config: Optional[Path] = None,
    pristine: bool = False,
    extra_args: Optional[Iterable[str]] = None,
    extra_cmake_args: Optional[Iterable[str]] = None,
) -> List[str]:
    def args() -> Iterator[str]:
        yield from ("-b", board)

        yield from ("--pristine", "always" if pristine else "auto")
        if app_dir:
            yield from ("-s", str(app_dir))
        if build_dir:
            yield from ("-d", str(build_dir))

        if extra_args:
            yield from extra_args

        cmake_vals = {
            "SHIELD": shield,
            "ZMK_CONFIG": zmk_config,
            "CONFIG_KERNEL_BIN_NAME": f'"{bin_name}"' if bin_name else None,
        }
        cmake_args = [f"-D{name}={val}" for name, val in cmake_vals.items() if val]
        if extra_cmake_args:
            cmake_args += extra_cmake_args

        if cmake_args:
            yield from ("--", *cmake_args)

    return ["west", "build", *args()]


def join(parts: Iterable[Optional[str]], sep: str) -> str:
    return sep.join(filter(None, parts))
