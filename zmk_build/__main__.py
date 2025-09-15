from __future__ import annotations

import argparse
import hashlib
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .argparse_dataclass import ArgparseMixin, arg_field
from .zmk import (
    CompilationItem,
    check_west_setup,
    run_west_setup,
    run_west_update,
    sanitize_bin_name,
    west_build_command,
)

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="ZMK build helper; runs Zephyr build(s) and retrieves artefacts.",
        epilog="Extra arguments are passed to `west build` command.",
    )

    group = parser.add_argument_group("firmware")
    ShieldBoard.Add_arguments(group)
    FwOptions.Add_arguments(group)
    Artefacts.Add_arguments(parser, group="artefacts")
    Directories.Add_arguments(parser, group="directories")
    Misc.Add_arguments(parser)

    args, unknown_args = parser.parse_known_args(argv)

    SHIELD_BOARD = ShieldBoard.From_args(args)
    DIRS = Directories.From_args(args)
    FW_OPTS = FwOptions.From_args(args)
    ARTEFACTS = Artefacts.From_args(args)
    MISC = Misc.From_args(args)

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

    extra_west_args, extra_cmake_args = FW_OPTS.args()
    for unknown_arg in unknown_args:
        if unknown_arg.startswith("-D"):
            extra_cmake_args.append(unknown_arg)
        else:
            extra_west_args.append(unknown_arg)

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

        # if there's more than 1 shield or snippet, compute a hash to have a unique build sub directory
        build_id = (
            *SHIELD_BOARD.shields,
            *(arg for arg in extra_west_args if arg.startswith("-S=")),
        )
        build_hash = (
            hashlib.md5(repr(build_id).encode()).hexdigest()[-8:] if build_id else None
        )
        build_dir = DIRS.build / join(
            [item.zmk_shield, item.zmk_board, build_hash], "-"
        )
        tmp_bin_name = item.filename(alias=ARTEFACTS.name)
        final_bin_name = item.filename(tag=str(FW_OPTS), alias=ARTEFACTS.name)
        final_bin_name = sanitize_bin_name(final_bin_name)

        shields = (
            (item.zmk_shield, *SHIELD_BOARD.secondary_shields)
            if item.zmk_shield
            else ()
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
            extra_args=extra_west_args,
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
    shields: list[str] = arg_field(
        "shield", nargs="*", metavar="SHIELD", help="shield names"
    )
    board: str = arg_field("board", metavar="BOARD", help="board name")

    @property
    def primary_shield(self):
        return self.shields[0] if self.shields else None

    @property
    def secondary_shields(self):
        return self.shields[1:]


@dataclass(frozen=True)
class Directories(ArgparseMixin):
    zmk: Path = arg_field(
        "--zmk-src",
        type=Path,
        default=".",
        metavar="DIR",
        help="ZMK base directory (default: %(default)s)",
    )
    zmk_config: Path = arg_field(
        "--zmk-config",
        type=Path,
        default="./zmk-config",
        metavar="DIR",
        help="zmk-config directory (default: %(default)s)",
    )
    modules: list[Path] = arg_field(
        "--module-dir",
        "--module-dirs",
        nargs="*",
        type=Path,
        metavar="DIR",
        help="zmk module directories",
    )
    build: Path = arg_field(
        "--build-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "zmk-build",
        metavar="DIR",
        help="build directory (default: %(default)s)",
    )

    @property
    def zmk_app(self):
        return self.zmk / "app"


@dataclass(frozen=True)
class Artefacts(ArgparseMixin):
    _argparse_mutually_exclusive = (("left_only", "right_only"),)

    left_only: bool = arg_field(
        "-l",
        "--left-only",
        action="store_true",
        help="build only left side of split board/shield",
    )
    right_only: bool = arg_field(
        "-r",
        "--right-only",
        action="store_true",
        help="build only right side of split board/shield",
    )
    directory: Path = arg_field(
        "--into",
        type=Path,
        default=tempfile.gettempdir(),
        metavar="DIR",
        help="artefacts destination directory (default: %(default)s)",
    )
    name: str = arg_field(
        "--name",
        metavar="NAME",
        help="basename used to rename the artefact(s)",
    )
    extensions: list[str] = arg_field(
        "-f",
        nargs="*",
        default=["uf2"],
        metavar="EXT",
        help="extension of the artefact(s) to retrieve (default: uf2)",
    )


def opt_yn_arg_field(
    *name_or_flags: str, default: bool | None = None, help: str | None = None
):
    def to_arg(name_or_flags: Sequence[str], val: bool | None):
        if val is not None:
            v = "y" if val else "n"
            yield f"{min(name_or_flags, key=len)}={v}"

    def bool_from_yn(arg: str | bool | None):
        if arg is None or isinstance(arg, bool):
            return arg
        elif arg.lower() in ("yes", "y", "true", "1"):
            return True
        elif arg.lower() in ("no", "n", "false", "0"):
            return False
        else:
            raise ValueError()

    return arg_field(
        *name_or_flags,
        default=default,
        type=bool_from_yn,
        nargs="?",
        const=True,
        help=help,
        metavar="y/n",
        _to_arg=to_arg,
    )


@dataclass(frozen=True)
class FwOptions(ArgparseMixin):
    logging: bool | None = opt_yn_arg_field(
        "--with-logging",
        help="set CONFIG_ZMK_USB_LOGGING select zmk-usb-logging snippet",
    )
    usb: bool | None = opt_yn_arg_field("--with-usb", help="set CONFIG_ZMK_USB")
    ble: bool | None = opt_yn_arg_field("--with-ble", help="set CONFIG_ZMK_BLE")
    max_bt: int | None = arg_field(
        "--with-max-bt",
        type=int,
        metavar="N",
        help="set CONFIG_BT_MAX_PAIRED and CONFIG_BT_MAX_CONN",
    )
    kb_name: str | None = arg_field(
        "--with-kb-name", help="set CONFIG_ZMK_KEYBOARD_NAME"
    )
    studio: bool | None = opt_yn_arg_field(
        "--with-studio",
        help="set CONFIG_ZMK_STUDIO and select studio-rpc-usb-uart snippet",
    )
    split_battery: bool | None = opt_yn_arg_field(
        "--with-split-battery",
        help="set CONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_PROXY and CONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_FETCHING",
    )
    pointing: bool | None = opt_yn_arg_field(
        "--with-pointing", help="set CONFIG_ZMK_POINTING"
    )

    def __bool__(self):
        west_args, cmake_args = self.args()
        return any(cmake_args) or any(west_args)

    def args(self):
        west_args: list[str] = []
        cmake_args: list[str] = []

        def yn(b: bool):
            return "y" if b else "n"

        if self.logging is not None:
            if self.logging:
                west_args += ("-S=zmk-usb-logging",)
            cmake_args += (f"-DCONFIG_ZMK_USB_LOGGING={yn(self.logging)}",)
        if self.usb is not None:
            cmake_args += (f"-DCONFIG_ZMK_USB={yn(self.usb)}",)
        if self.ble is not None:
            cmake_args += (f"-DCONFIG_ZMK_BLE={yn(self.ble)}",)
        if self.max_bt:
            cmake_args += (
                f"-DCONFIG_BT_MAX_PAIRED={self.max_bt}",
                f"-DCONFIG_BT_MAX_CONN={self.max_bt}",
            )
        if self.kb_name:
            escaped_kb_name = self.kb_name.replace('"', '\\"')
            cmake_args += (f'-DCONFIG_ZMK_KEYBOARD_NAME="{escaped_kb_name}"',)
        if self.studio is not None:
            if self.studio:
                west_args += ("-S=studio-rpc-usb-uart",)
            cmake_args += (f"-DCONFIG_ZMK_STUDIO={yn(self.studio)}",)
        if self.split_battery is not None:
            cmake_args += (
                f"-DCONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_PROXY={yn(self.split_battery)}",
                f"-DCONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_FETCHING={yn(self.split_battery)}",
            )
        if self.pointing is not None:
            cmake_args += (f"-DCONFIG_ZMK_POINTING={yn(self.pointing)}",)
        return west_args, cmake_args

    def __str__(self):
        def parts():
            def yn(b: bool):
                return "y" if b else "n"

            if self.studio is not None:
                yield f"studio={yn(self.studio)}"
            if self.split_battery is not None:
                yield f"split-battery={yn(self.split_battery)}"
            if self.pointing is not None:
                yield f"pointing={yn(self.pointing)}"
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


@dataclass(frozen=True)
class Misc(ArgparseMixin):
    update_west: bool = arg_field(
        "--west-update",
        action="store_true",
        help="update west before building",
    )
    pristine: bool = arg_field(
        "-p",
        "--pristine",
        action="store_true",
        help="clean build directories before starting",
    )
    dry_run: bool = arg_field(
        "-n",
        "--dry-run",
        action="store_true",
        help="just print build commands; don't run them",
    )
    verbose: bool = arg_field("-v", "--verbose", action="store_true", help="print more")


def join(parts: Iterable[str | None], sep: str) -> str:
    return sep.join(filter(None, parts))


if __name__ == "__main__":
    exit(main())
