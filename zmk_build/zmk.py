import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

logger = logging.getLogger(__name__)


@dataclass
class CompilationItem:
    zmk_board: str
    """valid zmk board name, eg. `nice_nano_v2`"""
    shield_name: str | None = None
    """shield name, without `_side` suffix, eg. `corne`"""
    shield_side: str | None = None
    """side name for split shields, `left` or `right`"""

    @property
    def zmk_shield(self) -> str | None:
        """valid zmk shield name, with `_side` prefix for split shields,
        eg. `corne_left`"""
        if self.shield_name and self.shield_side:
            return f"{self.shield_name}_{self.shield_side}"
        elif self.shield_name:
            return self.shield_name
        else:
            return None

    def filename(self, tag: str | None = None, alias: str | None = None):
        basename = alias or join([self.shield_name, self.zmk_board], "-")
        if tag:
            basename += f"[{tag}]"
        return join([basename, self.shield_side], ".")

    @classmethod
    def Find(cls, board: str, shield: str | None, shield_dirs: Iterable[Path]):
        if shield:
            shield_path = find_dir(*(dir / shield for dir in shield_dirs))
            if shield_path:
                logger.info(f"found shield `{shield}` at `{shield_path}`")

            if shield_path and (sides := guess_split_shield_sides(shield_path, shield)):
                sides = sorted(sides)
                sides_str = ", ".join(f"`{s}`" for s in sides)
                logger.info(f"guessing shield is split ({sides_str})")
                for side in sides:
                    yield cls(board, shield, side)
            else:
                yield cls(board, shield)
        else:
            yield cls(board)


def guess_board_name(board_dir: Path):
    if board_dir.is_dir():
        for line in open(board_dir / "Kconfig.board"):
            if m := re.search(r"config BOARD_(\w+)", line):
                return str(m.group(1)).lower()
    raise ValueError("could not guess board name")


def guess_board_type(board_dir: Path):
    if board_dir.is_dir():
        for child in board_dir.glob("*_defconfig"):
            if child.is_file():
                for line in open(child):
                    if m := re.search(r"CONFIG_(\w+)_MPU", line):
                        return str(m.group(1)).lower()
    raise ValueError("could not guess board type")


def guess_shield_name(shield_dir: Path):
    if shield_dir.is_dir():
        for child in shield_dir.iterdir():
            if child.suffix in (".keymap", ".conf"):
                return child.stem
    return shield_dir.stem


def guess_split_shield_sides(shield_dir: Path, shield_name: str):
    def find_all():
        defconfig = shield_dir / "Kconfig.defconfig"
        if defconfig.is_file():
            for line in open(defconfig):
                for m in re.findall(rf"SHIELD_{shield_name}_(\w+)", line, flags=re.I):
                    yield str(m).lower()

    return set(find_all())


def find_dir(*candidates: Path) -> Path | None:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate


def check_west_setup_command(zmk_app: Path):
    return ["west", "--help", "build"]


def west_setup_command(zmk_app: Path):
    return ["west", "init", "-l", str(zmk_app)]


def west_update_commands(zmk_app: Path):
    return (
        ["west", "update"],
        ["west", "zephyr-export"],
    )


def west_build_command(
    board: str,
    *shields: str,
    modules: Iterable[Path] = (),
    app_dir: Path | None = None,
    build_dir: Path | None = None,
    bin_name: str | None = None,
    zmk_config: Path | None = None,
    pristine: bool = False,
    extra_args: Iterable[str] = (),
    extra_cmake_args: Iterable[str] = (),
) -> list[str]:
    def args() -> Iterator[str]:
        yield from ("-b", board)

        yield from ("--pristine", "always" if pristine else "auto")
        if app_dir:
            yield from ("-s", str(app_dir))
        if build_dir:
            yield from ("-d", str(build_dir))

        yield from extra_args

        cmake_vals: dict[str, Any] = {
            "SHIELD": join(shields, " ") if shields else None,
            "ZMK_EXTRA_MODULES": join_paths(modules, ";") if modules else None,
            "ZMK_CONFIG": zmk_config,
            "CONFIG_KERNEL_BIN_NAME": (
                f'"{sanitize_bin_name(bin_name)}"' if bin_name else None
            ),
        }
        if cmake_args := (
            *(f"-D{name}={val}" for name, val in cmake_vals.items() if val),
            *extra_cmake_args,
        ):
            yield from ("--", *cmake_args)

    return ["west", "build", *args()]


def sanitize_bin_name(bin_name: str):
    return re.sub(r"[/\\]", "_", bin_name)


def join(parts: Iterable[str | None], sep: str) -> str:
    return sep.join(filter(None, parts))


def join_paths(paths: Iterable[Path | None], sep: str) -> str:
    return sep.join(str(path.expanduser()) for path in paths if path)
