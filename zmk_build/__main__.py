from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Iterable, List, Optional

from .argparse_helper import ArgparseMixin, arg, mutually_exclusive, yes_no_arg
from .zmk import CompilationItem, check_west_setup, run_west_setup, west_build_command

logger = logging.getLogger(__name__)


def main(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(
        description="ZMK build helper; runs Zephyr build(s) and retrieves artefacts.",
        epilog="Extra arguments are passed to `west build` command.",
    )

    ShieldBoard.Add_arguments(parser)
    Artefacts.Add_arguments(parser, group="artefacts")
    FwOptions.Add_arguments(parser, group="firmware options")
    Directories.Add_arguments(parser, group="directories")
    Misc.Add_arguments(parser)

    args, unknown_args = parser.parse_known_args(argv)

    SHIELD_BOARD = ShieldBoard.From_parsed_args(args)
    DIRS = Directories.From_parsed_args(args)
    FW_OPTS = FwOptions.From_parsed_args(args)
    ARTEFACTS = Artefacts.From_parsed_args(args)
    MISC = Misc.From_parsed_args(args)

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logger.setLevel(logging.DEBUG if MISC.verbose else logging.INFO)

    if not check_west_setup(DIRS.zmk_app):
        logger.warning("need to initalize west")
        if not MISC.dry_run:
            run_west_setup(DIRS.zmk_app)

    extra_cmake_args = [f"-DCONFIG_{k}={v}" for k, v in FW_OPTS]
    extra_cmake_args += ["-Wno-dev"]

    shield_dirs = [
        DIRS.zmk_config / "boards" / "shields",
        DIRS.zmk_app / "boards" / "shields",
    ]
    for item in CompilationItem.Find(
        SHIELD_BOARD.board, SHIELD_BOARD.shield, shield_dirs
    ):
        if ARTEFACTS.left_only and item.shield_side != "left":
            continue
        if ARTEFACTS.right_only and item.shield_side != "right":
            continue

        build_dir = DIRS.build / join([item.zmk_shield, item.zmk_board], "-")
        bin_name = item.filename(tag=str(FW_OPTS), alias=ARTEFACTS.name)

        west_build_cmd = west_build_command(
            item.zmk_board,
            item.zmk_shield,
            app_dir=DIRS.zmk_app,
            zmk_config=DIRS.zmk_config if DIRS.zmk_config.is_dir() else None,
            build_dir=build_dir,
            bin_name=bin_name,
            pristine=MISC.pristine,
            extra_args=unknown_args,
            extra_cmake_args=extra_cmake_args,
        )

        logger.info(f"run `{subprocess.list2cmdline(west_build_cmd)}`")
        if not MISC.dry_run:
            try:
                subprocess.check_call(west_build_cmd, cwd=DIRS.zmk_app, text=True)
            except subprocess.CalledProcessError as e:
                logger.error("build failed")
                return e.returncode

        for ext in ARTEFACTS.extensions:
            temp_output = build_dir / "zephyr" / f"{bin_name}.{ext}"
            final_output = ARTEFACTS.directory / f"{bin_name}.{ext}"

            logger.info(f"copy `{temp_output}` to `{final_output}`")
            if not MISC.dry_run:
                if temp_output.is_file():
                    shutil.copy(temp_output, final_output)
                else:
                    logger.warning(f"`{temp_output}` is not a file")


@dataclass(frozen=True)
class ShieldBoard(ArgparseMixin):
    shield: Optional[str]
    board: str

    _argparse = dict(
        shield=arg(nargs="?", metavar="SHIELD", help="shield name"),
        board=arg(metavar="BOARD", help="board name"),
    )


@dataclass(frozen=True)
class Directories(ArgparseMixin):
    zmk: Path
    zmk_config: Path
    build: Path

    @property
    def zmk_app(self):
        return self.zmk / "app"

    _argparse = dict(
        zmk=arg(
            "--zmk",
            type=Path,
            default=".",
            metavar="DIR",
            help="ZMK base directory (default: %(default)s)",
        ),
        zmk_config=arg(
            "--zmk-config",
            type=Path,
            default="./zmk-config",
            metavar="DIR",
            help="zmk-config directory (default: %(default)s)",
        ),
        build=arg(
            "--build",
            type=Path,
            default=Path(tempfile.gettempdir()) / "zmk-build",
            metavar="DIR",
            help="build directory (default: %(default)s)",
        ),
    )


@dataclass(frozen=True)
class Artefacts(ArgparseMixin):
    left_only: bool
    right_only: bool
    directory: Path
    name: str
    extensions: List[str]

    _argparse = (
        mutually_exclusive(
            left_only=arg(
                "-l",
                "--left-only",
                action="store_true",
                help="build only left side of split board/shield",
            ),
            right_only=arg(
                "-r",
                "--right-only",
                action="store_true",
                help="build only right side of split board/shield",
            ),
        ),
        dict(
            directory=arg(
                "--into",
                type=Path,
                default=tempfile.gettempdir(),
                metavar="DIR",
                help="artefacts destination directory (default: %(default)s)",
            ),
            name=arg(
                "--name",
                metavar="NAME",
                help="basename used to rename the artefact(s)",
            ),
            extensions=arg(
                "-f",
                nargs="*",
                default=["uf2"],
                metavar="EXT",
                help="extension of the artefact(s) to retrieve (default: uf2)",
            ),
        ),
    )


@dataclass(frozen=True)
class FwOptions(ArgparseMixin):
    logging: Optional[bool]
    usb: Optional[bool]
    bt: Optional[bool]
    max_bt: Optional[int]
    kb_name: Optional[str]

    def __iter__(self):
        return chain.from_iterable(
            conf.items() for _name, conf in self._names_and_confs()
        )

    def __bool__(self):
        for _ in self._names_and_confs():
            return True
        return False

    def __str__(self):
        return ",".join(name for name, _conf in self._names_and_confs())

    def _names_and_confs(self):
        def yn(b: bool):
            return "y" if b else "n"

        if self.logging is not None:
            yield f"logging={yn(self.logging)}", {"ZMK_USB_LOGGING": yn(self.logging)}
        if self.usb is not None:
            yield f"usb={yn(self.usb)}", {"ZMK_USB": yn(self.usb)}
        if self.bt is not None:
            yield f"bt={yn(self.bt)}", {"ZMK_BLE": yn(self.bt)}
        if self.max_bt:
            yield f"max-bt={self.max_bt}", {
                "BT_MAX_PAIRED": self.max_bt,
                "BT_MAX_CONN": self.max_bt,
            }
        if self.kb_name:
            esc_kb_name = '"' + self.kb_name.replace('"', '\\"') + '"'
            yield f"name={self.kb_name}", {"ZMK_KEYBOARD_NAME": esc_kb_name}

    _argparse = dict(
        logging=yes_no_arg("--logging", help="set CONFIG_ZMK_USB_LOGGING"),
        usb=yes_no_arg("--usb", help="set CONFIG_ZMK_USB"),
        bt=yes_no_arg("--bt", help="set CONFIG_ZMK_BLE"),
        max_bt=arg(
            "--max-bt",
            type=int,
            metavar="N",
            help="set CONFIG_BT_MAX_PAIRED and CONFIG_BT_MAX_CONN",
        ),
        kb_name=arg("--kb-name", help="set CONFIG_ZMK_KEYBOARD_NAME"),
    )


@dataclass(frozen=True)
class Misc(ArgparseMixin):
    pristine: bool
    dry_run: bool
    verbose: bool

    _argparse = dict(
        pristine=arg(
            "-p",
            "--pristine",
            action="store_true",
            help="clean build directories before starting",
        ),
        dry_run=arg(
            "-n",
            "--dry-run",
            action="store_true",
            help="just print build commands; don't run them",
        ),
        verbose=arg("-v", "--verbose", action="store_true", help="print more"),
    )


def join(parts: Iterable[Optional[str]], sep: str) -> str:
    return sep.join(filter(None, parts))


if __name__ == "__main__":
    exit(main())
