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
    check_west_setup_command,
    sanitize_bin_name,
    west_build_command,
    west_setup_command,
    west_update_commands,
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

    if not try_command(check_west_setup_command(DIRS.zmk_app), zmk_app=DIRS.zmk_app):
        logger.log(
            logging.DEBUG if MISC.dry_run else logging.WARNING, "need to initalize west"
        )
        run_command(
            west_setup_command(DIRS.zmk_app),
            *west_update_commands(DIRS.zmk_app),
            zmk_app=DIRS.zmk_app,
            dry_run=MISC.dry_run,
        )
    elif MISC.update_west:
        run_command(
            *west_update_commands(DIRS.zmk_app),
            zmk_app=DIRS.zmk_app,
            dry_run=MISC.dry_run,
        )

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
        tmp_bin_name = sanitize_bin_name(item.filename(alias=ARTEFACTS.name))
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
        try:
            run_command(west_build_cmd, zmk_app=DIRS.zmk_app, dry_run=MISC.dry_run)
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


def run_command(
    *commands: Sequence[str], zmk_app: Path, dry_run: bool = False, quiet: bool = False
):
    action = "would run" if dry_run else "run"
    for command in commands:
        logger.log(
            logging.INFO if dry_run else logging.DEBUG,
            f"{action} `{subprocess.list2cmdline(command)}`",
        )
        if not dry_run:
            subprocess.check_call(
                command,
                cwd=zmk_app,
                text=True,
                stdout=subprocess.DEVNULL if quiet else None,
                stderr=subprocess.DEVNULL if quiet else None,
            )


def try_command(command: Sequence[str], zmk_app: Path, dry_run: bool = False):
    try:
        run_command(command, zmk_app=zmk_app, dry_run=dry_run, quiet=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


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

    def __iter__(self):
        def yn(b: bool | None):
            return None if b is None else "y" if b else "n"

        if v := yn(self.logging):
            yield FwOption(
                f"logging={v}",
                f"-DCONFIG_ZMK_USB_LOGGING={v}",
                "-S=zmk-usb-logging" if self.logging else (),
            )
        if v := yn(self.usb):
            yield FwOption(f"usb={v}", f"-DCONFIG_ZMK_USB={v}")
        if v := yn(self.ble):
            yield FwOption(f"ble={v}", f"-DCONFIG_ZMK_BLE={v}")
        if (v := self.max_bt) is not None:
            yield FwOption(
                f"max-bt={v}",
                (f"-DCONFIG_BT_MAX_PAIRED={v}", f"-DCONFIG_BT_MAX_CONN={v}"),
            )
        if v := self.kb_name:
            escaped_var = v.replace('"', '\\"')
            escaped_str = re.sub(r"[/\\]", "_", v)
            yield FwOption(
                f"name={escaped_str}", f'-DCONFIG_ZMK_KEYBOARD_NAME="{escaped_var}"'
            )
        if v := yn(self.studio):
            yield FwOption(
                f"studio={v}",
                f"-DCONFIG_ZMK_STUDIO={v}",
                "-S=studio-rpc-usb-uart" if self.studio else (),
            )
        if v := yn(self.split_battery):
            yield FwOption(
                f"split-battery={v}",
                (
                    f"-DCONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_PROXY={v}",
                    f"-DCONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_FETCHING={v}",
                ),
            )
        if v := yn(self.pointing):
            yield FwOption(f"pointing={v}", f"-DCONFIG_ZMK_POINTING={v}")

    def __bool__(self):
        return any(self)

    def args(self):
        west_args: list[str] = []
        cmake_args: list[str] = []

        for opt in self:
            west_args += opt.west_args
            cmake_args += opt.cmake_args

        return west_args, cmake_args

    def __str__(self):
        return ",".join(opt.name for opt in self)


class FwOption:
    def __init__(
        self, name: str, cmake: str | Iterable[str] = (), west: str | Iterable[str] = ()
    ) -> None:
        self.name = name
        self.cmake_args = (cmake,) if isinstance(cmake, str) else tuple(cmake)
        self.west_args = (west,) if isinstance(west, str) else tuple(west)


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
