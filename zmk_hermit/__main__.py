from __future__ import annotations

import argparse
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Iterable, Iterator, Sequence

import zmk_build
from zmk_build.argparse_helper import ArgparseMixin, arg
from zmk_build.zmk import guess_board_name, guess_board_type, guess_shield_name

from .dockerstuff import Volumes, run_in_container
from .dockerstuff import logger as docker_logger
from .modular_behaviors import ModularBehaviorsShieldFiles

logger = logging.getLogger(__name__)


ZMKUSER = "zmkuser"
ZMKUSER_HOME = Path("/home") / ZMKUSER
ZMK_HOME = ZMKUSER_HOME / "zmk"
ZMK_CONFIG = Path("/zmk-config")
ARTEFACTS = Path("/artefacts")
BUILD = Path("/tmp/zmk-build")
DIR = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser(
        description="Compile out-of-tree ZMK keyboard in a Docker container.",
    )

    KbArgs.Add_arguments(parser, group="Keyboard")
    OutputArgs.Add_arguments(parser, group="Output")
    ZmkArgs.Add_arguments(parser, group="ZMK")
    parser.add_argument("--security-opt", help="Docker security-opt")

    parsed_args, extra_args = parser.parse_known_args()

    kb_args = KbArgs.From_parsed_args(parsed_args)
    out_args = OutputArgs.From_parsed_args(parsed_args)
    zmk_args = ZmkArgs.From_parsed_args(parsed_args)

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    for log in (logger, docker_logger):
        log.setLevel(logging.DEBUG if out_args.verbose else logging.INFO)

    try:
        return run_build(
            kb_args,
            out_args,
            zmk_args,
            extra_args,
            security_opt=str(parsed_args.security_opt),
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

    modular_behaviors_shield_files = None
    if zmk_args.behaviors:
        behavior_shield_name = "zmk_hermit_behaviors"
        logger.debug(
            f"creating `{behavior_shield_name}` shield to hold extra behavior sources"
        )
        shield_names.append(behavior_shield_name)

        behavior_shield = ZMK_CONFIG / "boards" / "shields" / behavior_shield_name

        modular_behaviors_shield_files = ModularBehaviorsShieldFiles(
            map(Path, zmk_args.behaviors), behavior_shield
        )
        for contents, path_in_shield in modular_behaviors_shield_files:
            volumes[path_in_shield] = contents, "ro"

    if out_args.build_dir:
        build_path = Path(out_args.build_dir)
        if build_path.is_dir():
            volumes[BUILD] = build_path, "rw"
        else:
            raise ValueError("build directory not a directory")

    py_module_dir = Path(zmk_build.__file__).parent
    volumes[ZMKUSER_HOME / "py_zmk_build"] = py_module_dir, "rw"
    build_script = "python3", "-m", "py_zmk_build"

    if zmk_args.zmk and Path(zmk_args.zmk).is_dir():
        volumes[ZMK_HOME] = Path(zmk_args.zmk).expanduser(), "rw"
        dockerfile = DIR / "Dockerfile-local-src"
        image_args = docker_image_args(zmk_args.zmk_image)
    else:
        repo = ZmkGitSource.Parse(zmk_args.zmk)
        dockerfile = DIR / "Dockerfile-git-src"
        image_args = docker_image_args(zmk_args.zmk_image, repo.repo, repo.branch)

    def build_py_ags() -> Iterator[str | Path]:
        yield from shield_names
        yield board_name

        yield from ("--name", output_basename)
        if out_args.extensions:
            yield from ("-f", *out_args.extensions)
        yield from ("--into", ARTEFACTS)

        yield from ("--zmk-dir", ZMK_HOME)
        yield from ("--zmk-config-dir", ZMK_CONFIG)
        yield from ("--build-dir", BUILD)
        yield from extra_args

        if out_args.verbose:
            yield "--verbose"

    start_time = time()

    exit_code = run_in_container(
        dockerfile,
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

    if modular_behaviors_shield_files:
        for temp_path in modular_behaviors_shield_files.temp_files:
            try:
                temp_path.unlink()
                logger.debug(f"removed temporary file `{temp_path}`")
            except IOError:
                logger.warning(f"could not remove temporary file `{temp_path}`")

    return exit_code


@dataclass
class KbArgs(ArgparseMixin):
    shields: list[str]
    board: str
    keymap: str | None
    zmk_config: Path

    _argparse = dict(
        shields=arg(
            nargs="*",
            metavar="SHIELD",
            help="ZMK shield name or out-of-tree shield directory",
        ),
        board=arg(
            "board",
            metavar="BOARD",
            help="ZMK board name or out-of-tree board directory",
        ),
        keymap=arg("--keymap", metavar="FILE", help="out-of-tree keymap file"),
        zmk_config=arg("--zmk-config", metavar="IMAGE", help="ZMK-config dir"),
    )


@dataclass
class OutputArgs(ArgparseMixin):
    extensions: list[str]
    into: Path
    build_dir: Path | None
    verbose: bool

    _argparse = dict(
        extensions=arg(
            "-f",
            nargs="*",
            default=["uf2"],
            metavar="EXT",
            help="extension of the artefact(s) to retrieve (default: uf2)",
        ),
        into=arg(
            "--into",
            type=Path,
            default=tempfile.gettempdir(),
            metavar="DIR",
            help="directory to copy compiled .uf2 to (default: `%(default)s`)",
        ),
        build_dir=arg(
            "--build-dir",
            type=Path,
            metavar="DIR",
            help="build directory for ZMK",
        ),
        verbose=arg("-v", "--verbose", action="store_true", help="print more"),
    )


@dataclass
class ZmkArgs(ArgparseMixin):
    behaviors: list[str]
    zmk: str
    zmk_image: str

    _argparse = dict(
        behaviors=arg(
            "--behavior",
            "--behaviors",
            nargs="+",
            metavar="FILE",
            help="out-of-tree behavior files",
        ),
        zmk=arg(
            "--zmk",
            default="zmkfirmware:main",
            metavar="REPO",
            help=(
                "ZMK git repository (github-user:branch) or ZMK source directory"
                " (default: `%(default)s`)"
            ),
        ),
        zmk_image=arg(
            "--zmk-image",
            default="zmkfirmware/zmk-build-arm:3.5",
            metavar="IMAGE",
            help="Docker ZMK-build image id (default: `%(default)s`)",
        ),
    )


@dataclass
class ZmkGitSource:
    repo: str
    branch: str

    @classmethod
    def Parse(cls, txt: str):
        if m := re.match(r"([-_\w]+)(:(.+))?$", txt):
            user = m.group(1)
            branch = m.group(3) or "main"
            return cls(f"https://github.com/{user}/zmk.git", branch=branch)
        raise ValueError(txt)


def docker_image_args(
    zmk_image: str | None,
    zmk_git: str | None = None,
    zmk_git_branch: str | None = None,
):
    if zmk_image:
        yield "ZMK_IMAGE", zmk_image
    if zmk_git:
        yield "ZMK_GIT", zmk_git
    if zmk_git_branch:
        yield "ZMK_GIT_BRANCH", zmk_git_branch
    yield "UID", str(os.getuid())
    yield "GID", str(os.getgid())
    yield "USER", ZMKUSER


def join(parts: Iterable[str | None], sep: str):
    return sep.join(filter(None, parts))


if __name__ == "__main__":
    exit(main())
