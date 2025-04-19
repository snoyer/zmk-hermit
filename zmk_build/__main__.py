from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .argparse_helper import ArgparseMixin, arg, mutually_exclusive, yes_no_arg
from .zmk import (
    CompilationItem,
    check_west_setup,
    run_west_setup,
    run_west_update,
    west_build_command,
)

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None):
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

    logging.basicConfig(
        level=logging.DEBUG if MISC.verbose else logging.INFO, format="%(message)s"
    )

    if not check_west_setup(DIRS.zmk_app):
        logger.log(
            logging.DEBUG if MISC.dry_run else logging.WARNING, "need to initalize west"
        )
        run_west_setup(DIRS.zmk_app, dry_run=MISC.dry_run)
        run_west_update(DIRS.zmk_app, dry_run=MISC.dry_run)
    elif MISC.update_west:
        run_west_update(DIRS.zmk_app, dry_run=MISC.dry_run)

    extra_cmake_args = [*FW_OPTS.cmake_args(), "-Wno-dev"]
    extra_args: list[str] = [*FW_OPTS.west_args()]
    for unknown_arg in unknown_args:
        if unknown_arg.startswith("-D"):
            extra_cmake_args.append(unknown_arg)
        else:
            extra_args.append(unknown_arg)

    shield_dirs = [
        DIRS.zmk_config / "boards" / "shields",
        DIRS.zmk_app / "boards" / "shields",
    ]
    for item in CompilationItem.Find(
        SHIELD_BOARD.board, SHIELD_BOARD.primary_shield, shield_dirs
    ):
        if ARTEFACTS.left_only and item.shield_side != "left":
            logger.info(f"not building `{item.shield_side}` side (`left` only)")
            continue
        if ARTEFACTS.right_only and item.shield_side != "right":
            logger.info(f"not building `{item.shield_side}` side (`right` only)")
            continue

        build_dir = DIRS.build / join([item.zmk_shield, item.zmk_board], "-")
        tmp_bin_name = item.filename(alias=ARTEFACTS.name)
        final_bin_name = item.filename(tag=str(FW_OPTS), alias=ARTEFACTS.name)

        shields = (
            [item.zmk_shield, *SHIELD_BOARD.secondary_shields]
            if item.zmk_shield
            else []
        )
        west_build_cmd = west_build_command(
            item.zmk_board,
            *shields,
            modules=DIRS.modules,
            app_dir=DIRS.zmk_app,
            zmk_config=DIRS.zmk_config if DIRS.zmk_config.is_dir() else None,
            build_dir=build_dir,
            bin_name=tmp_bin_name,
            pristine=MISC.pristine,
            extra_args=extra_args,
            extra_cmake_args=extra_cmake_args,
        )
        action = "would run" if MISC.dry_run else "run"
        logger.info(f"{action} `{subprocess.list2cmdline(west_build_cmd)}`")
        if not MISC.dry_run:
            try:
                subprocess.check_call(west_build_cmd, cwd=DIRS.zmk_app, text=True)
            except subprocess.CalledProcessError as e:
                logger.error("build failed")
                return e.returncode

        for ext in ARTEFACTS.extensions:
            temp_output = build_dir / "zephyr" / f"{tmp_bin_name}.{ext}"
            final_output = ARTEFACTS.directory / f"{final_bin_name}.{ext}"

            action = "would copy" if MISC.dry_run else "copy"
            logger.info(f"{action} `{temp_output}` to `{final_output}`")
            if not MISC.dry_run:
                if temp_output.is_file():
                    shutil.copy(temp_output, final_output)
                else:
                    logger.warning(f"`{temp_output}` is not a file")


@dataclass(frozen=True)
class ShieldBoard(ArgparseMixin):
    shields: list[str]
    board: str

    @property
    def primary_shield(self):
        return self.shields[0] if self.shields else None

    @property
    def secondary_shields(self):
        return self.shields[1:]

    _argparse = dict(
        shields=arg(nargs="*", metavar="SHIELD", help="shield names"),
        board=arg(metavar="BOARD", help="board name"),
    )


@dataclass(frozen=True)
class Directories(ArgparseMixin):
    zmk: Path
    zmk_config: Path
    modules: list[Path]
    build: Path

    @property
    def zmk_app(self):
        return self.zmk / "app"

    _argparse_suffix = "-dir"
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
        modules=arg(
            "--module",
            nargs="*",
            type=Path,
            metavar="DIR",
            help="zmk module directories",
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
    extensions: list[str]

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
    logging: bool | None
    usb: bool | None
    ble: bool | None
    max_bt: int | None
    kb_name: str | None

    _argparse_prefix = "with-"

    def cmake_args(self) -> Iterator[str]:
        def yn(b: bool):
            return "y" if b else "n"

        if self.logging is not None:
            yield f"-DCONFIG_ZMK_USB_LOGGING={yn(self.logging)}"
        if self.usb is not None:
            yield f"-DCONFIG_ZMK_USB={yn(self.usb)}"
        if self.ble is not None:
            yield f"-DCONFIG_ZMK_BLE={yn(self.ble)}"
        if self.max_bt:
            yield f"-DCONFIG_BT_MAX_PAIRED={self.max_bt}"
            yield f"-DCONFIG_BT_MAX_CONN={self.max_bt}"
        if self.kb_name:
            escaped_kb_name = self.kb_name.replace('"', '\\"')
            yield f'-DCONFIG_ZMK_KEYBOARD_NAME="{escaped_kb_name}"'

    def west_args(self) -> Iterator[str]:
        if self.logging is not None:
            yield from ("-S", "zmk-usb-logging")

    def __bool__(self):
        return any(self.cmake_args()) or any(self.west_args())

    def __str__(self):
        def parts():
            def yn(b: bool):
                return "y" if b else "n"

            if self.logging is not None:
                yield f"logging={yn(self.logging)}"
            if self.usb is not None:
                yield f"usb={yn(self.usb)}"
            if self.ble is not None:
                yield f"ble={yn(self.ble)}"
            if self.max_bt:
                yield f"max-bt={self.max_bt}"
            if self.kb_name:
                esc_kb_name = re.sub(r"[/\\]", "_", self.kb_name)
                yield f"name={esc_kb_name}"

        return ",".join(parts())

    _argparse = dict(
        logging=yes_no_arg("--logging", help="set CONFIG_ZMK_USB_LOGGING"),
        usb=yes_no_arg("--usb", help="set CONFIG_ZMK_USB"),
        ble=yes_no_arg("--ble", help="set CONFIG_ZMK_BLE"),
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
    update_west: bool
    pristine: bool
    dry_run: bool
    verbose: bool

    _argparse = dict(
        update_west=arg(
            "--update-west",
            action="store_true",
            help="update west before building",
        ),
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


def join(parts: Iterable[str | None], sep: str) -> str:
    return sep.join(filter(None, parts))


if __name__ == "__main__":
    exit(main())
