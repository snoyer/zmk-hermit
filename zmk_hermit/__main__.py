from __future__ import annotations

import argparse
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Iterable, Iterator, Sequence

import zmk_build
from zmk_build.__main__ import FwOptions
from zmk_build.argparse_dataclass import ArgparseMixin, arg_field
from zmk_build.zmk import guess_board_name, guess_board_type, guess_shield_name

from .dockerstuff import Volumes, run_in_container
from .dockerstuff import logger as docker_logger

logger = logging.getLogger(__name__)


ZMKUSER = "zmkuser"
ZMKUSER_HOME = Path("/home") / ZMKUSER
ZMK_HOME = ZMKUSER_HOME / "zmk"
ZMK_CONFIG = Path("/zmk-config")
ZMK_MODULES = Path("/zmk-modules")
ARTEFACTS = Path("/artefacts")
BUILD = Path("/tmp/zmk-build")
DIR = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser(
        description="Compile out-of-tree ZMK keyboard in a Docker container.",
    )

    group = parser.add_argument_group("keyboard")
    KbArgs.Add_arguments(group)
    FwOptions.Add_arguments(group)
    OutputArgs.Add_arguments(parser, group="artefacts")
    ZmkArgs.Add_arguments(parser, group="ZMK")
    parser.add_argument("-v", "--verbose", action="store_true", help="print more")
    parser.add_argument("--docker-security-opt", help="Docker security-opt")

    parser._action_groups.sort(key=lambda g: 1 if g.title == "options" else 0)

    parsed_args, extra_args = parser.parse_known_args()
    extra_args += FwOptions.From_args(parsed_args).to_args()

    kb_args = KbArgs.From_args(parsed_args)
    out_args = OutputArgs.From_args(parsed_args)
    zmk_args = ZmkArgs.From_args(parsed_args)

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    for log in (logger, docker_logger):
        log.setLevel(logging.DEBUG if parsed_args.verbose else logging.INFO)

    try:
        zmk_args.build_dir.mkdir(parents=True, exist_ok=True)
        return run_build(
            kb_args,
            out_args,
            zmk_args,
            extra_args,
            security_opt=parsed_args.docker_security_opt,
            verbose=parsed_args.verbose,
        )
    except ValueError as e:
        logger.error(f"error: {e}")
        return 2
    except KeyboardInterrupt:
        return 130


def run_build(
    kb_args: KbArgs,
    out_args: OutputArgs,
    zmk_args: ZmkArgs,
    extra_args: Sequence[str],
    security_opt: str | None = None,
    verbose: bool = False,
):
    volumes = Volumes()

    if kb_args.zmk_config:
        zmk_config_path = Path(kb_args.zmk_config).expanduser()
        if zmk_config_path.is_dir():
            volumes[ZMK_CONFIG] = zmk_config_path, "ro"
        else:
            raise ValueError("zmk-config must be a directory")

    shield_names: list[str] = []
    for shield in kb_args.shields:
        shield_path = Path(shield).expanduser()
        if shield_path.is_file() or shield_path.is_dir():
            primary_shield_name = guess_shield_name(shield_path)
            logger.info(
                f"guessed shield name `{primary_shield_name}` from `{shield_path}`"
            )
            shield_dir = shield_path if shield_path.is_dir() else shield_path.parent
            volumes[ZMK_CONFIG / "boards" / "shields" / primary_shield_name] = (
                shield_dir,
                "ro",
            )
            shield_names.append(primary_shield_name)
        else:
            shield_names.append(str(shield))

    if kb_args.board:
        board_path = Path(kb_args.board).expanduser()
        if board_path.is_dir():
            board_name = guess_board_name(board_path)
            board_type = guess_board_type(board_path)
            logger.info(
                f"guessed board name `{board_name}` ({board_type}) from `{board_path}`"
            )
            volumes[ZMK_CONFIG / "boards" / board_type / board_name] = board_path, "ro"
        elif board_path.is_file():
            raise ValueError("out-of-tree board must be a directory")
        else:
            board_name = str(kb_args.board)
    else:
        raise ValueError("no board")

    primary_shield_name = shield_names[0] if shield_names else None

    if kb_args.keymap:
        keymap_path = Path(kb_args.keymap).expanduser()
        if keymap_path.is_file():
            keymap_name = keymap_path.stem
            tmp_name = primary_shield_name or board_name
            volumes[ZMK_CONFIG / f"{tmp_name}.keymap"] = keymap_path, "ro"
        else:
            raise ValueError("out-of-tree keymap must be a file")
    else:
        keymap_name = None

    output_basename = join([primary_shield_name, board_name, keymap_name], "-")

    if out_args.into:
        into_path = Path(out_args.into).expanduser()
        if into_path.is_dir():
            volumes[ARTEFACTS] = into_path, "rw"
        else:
            raise ValueError("output directory not a directory")

    extra_modules: list[Path] = []
    if zmk_args.modules:
        for module_dir in map(Path, zmk_args.modules):
            if module_dir.is_dir():
                module_dir_inside = ZMK_MODULES / module_dir.name
                volumes[module_dir_inside] = module_dir, "ro"
                extra_modules.append(module_dir_inside)
            else:
                raise ValueError(f"module directory {module_dir} is not a directory")

    if zmk_args.build_dir:
        if zmk_args.build_dir.is_dir():
            volumes[BUILD] = zmk_args.build_dir, "rw"
        else:
            raise ValueError(f"build directory {zmk_args.build_dir} is not a directory")

    py_module_dir = Path(zmk_build.__file__).parent
    volumes[ZMKUSER_HOME / "py_zmk_build"] = py_module_dir, "ro"
    build_script = "python3", "-m", "py_zmk_build"

    if zmk_args.zmk_src and Path(zmk_args.zmk_src).is_dir():
        volumes[ZMK_HOME] = Path(zmk_args.zmk_src).expanduser(), "rw"
        image_args = docker_image_args(zmk_args.zmk_image)
    else:
        raise ValueError(f"source directory {zmk_args.build_dir} is not a directory")

    def build_py_ags() -> Iterator[str | Path]:
        yield from shield_names
        yield board_name

        if extra_modules:
            yield from ("--module-dir", *extra_modules)

        yield from ("--name", output_basename)
        if out_args.extensions:
            yield from ("-f", *out_args.extensions)
        yield from ("--into", ARTEFACTS)

        yield from ("--zmk-src", ZMK_HOME)
        yield from ("--zmk-config", ZMK_CONFIG)
        yield from ("--build-dir", BUILD)
        yield from extra_args

        if verbose:
            yield "--verbose"

    start_time = time()

    exit_code = run_in_container(
        DIR / "Dockerfile",
        image_args,
        (*build_script, *build_py_ags()),
        volumes=volumes,
        tag="zmk-hermit",
        security_opt=[security_opt] if security_opt else None,
    )

    if not exit_code and out_args.into:
        into_path = Path(out_args.into).expanduser()
        for fn in into_path.glob(f"{output_basename}*.*"):
            if (
                fn.suffix.lstrip(".") in out_args.extensions
                and fn.stat().st_mtime > start_time
            ):
                logger.info(f"retrieved `{out_args.into / fn.name}`")

    return exit_code


@dataclass
class KbArgs(ArgparseMixin):
    shields: list[str] = arg_field(
        "shield",
        nargs="*",
        metavar="SHIELD",
        default=[],
        help="ZMK shield name or out-of-tree shield directory",
    )
    board: str = arg_field(
        "board",
        metavar="BOARD",
        help="ZMK board name or out-of-tree board directory",
    )
    keymap: str | None = arg_field(
        "--keymap", metavar="FILE", help="out-of-tree keymap file"
    )
    zmk_config: Path = arg_field("--zmk-config", metavar="DIR", help="ZMK-config dir")


@dataclass
class OutputArgs(ArgparseMixin):
    extensions: list[str] = arg_field(
        "-f",
        nargs="*",
        default=["uf2"],
        metavar="EXT",
        help="extension of the artefact(s) to retrieve (default: uf2)",
    )
    into: Path = arg_field(
        "--into",
        type=Path,
        default=tempfile.gettempdir(),
        metavar="DIR",
        help="directory to copy compiled .uf2 to (default: `%(default)s`)",
    )


@dataclass
class ZmkArgs(ArgparseMixin):
    zmk_src: str = arg_field(
        "--zmk-src", required=True, metavar="DIR", help="ZMK source directory"
    )
    modules: list[str] = arg_field(
        "--zmk-module",
        "--zmk-modules",
        nargs="+",
        metavar="FILE",
        help="out-of-tree module directories",
    )
    zmk_image: str = arg_field(
        "--zmk-image",
        default="zmkfirmware/zmk-build-arm:3.5",
        metavar="IMAGE",
        help="ZMK-build Docker image (default: `%(default)s`)",
    )
    build_dir: Path = arg_field(
        "--build-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "zmk-build",
        metavar="DIR",
        help="build directory for ZMK (default: %(default)s)",
    )


def docker_image_args(zmk_image: str):
    yield "ZMK_IMAGE", zmk_image
    yield "UID", str(os.getuid())
    yield "GID", str(os.getgid())
    yield "USER", ZMKUSER


def join(parts: Iterable[str | None], sep: str):
    return sep.join(filter(None, parts))


if __name__ == "__main__":
    exit(main())
