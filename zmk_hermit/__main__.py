from __future__ import annotations

import argparse
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Iterable, Iterator, List, Optional, Sequence

import zmk_build
from zmk_build.argparse_helper import ArgparseMixin, arg
from zmk_build.zmk import guess_board_name, guess_board_type, guess_shield_name

from .dockerstuff import Volumes
from .dockerstuff import logger as docker_logger
from .dockerstuff import run_in_container

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

    parsed_args, extra_args = parser.parse_known_args()

    kb_args = KbArgs.From_parsed_args(parsed_args)
    out_args = OutputArgs.From_parsed_args(parsed_args)
    zmk_args = ZmkArgs.From_parsed_args(parsed_args)

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    for log in (logger, docker_logger):
        log.setLevel(logging.DEBUG if out_args.verbose else logging.INFO)

    try:
        return run_build(kb_args, out_args, zmk_args, extra_args)
    except ValueError as e:
        logger.error(f"error: {e}")
        return 2
    except KeyboardInterrupt:
        return 130


def run_build(
    kb_args: KbArgs, out_args: OutputArgs, zmk_args: ZmkArgs, extra_args: Sequence[str]
):
    volumes = Volumes()

    if kb_args.zmk_config:
        zmk_config_path = Path(kb_args.zmk_config).expanduser()
        if zmk_config_path.is_dir():
            volumes[ZMK_CONFIG] = zmk_config_path, "ro"
        else:
            raise ValueError("zmk-config must be a directory")

    if kb_args.shield:
        shield_path = Path(kb_args.shield).expanduser()
        if shield_path.is_file() or shield_path.is_dir():
            shield_name = guess_shield_name(shield_path)
            logger.info(f"guessed shield name `{shield_name}` from `{shield_path}`")
            shield_dir = shield_path if shield_path.is_dir() else shield_path.parent
            volumes[ZMK_CONFIG / "boards" / "shields" / shield_name] = shield_dir, "ro"
        else:
            shield_name = str(kb_args.shield)
    else:
        shield_name = None

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

    if kb_args.keymap:
        keymap_path = Path(kb_args.keymap).expanduser()
        if keymap_path.is_file():
            keymap_name = keymap_path.stem
            tmp_name = shield_name or board_name
            volumes[ZMK_CONFIG / f"{tmp_name}.keymap"] = keymap_path, "ro"
        else:
            raise ValueError("out-of-tree keymap must be a file")
    else:
        keymap_name = None

    output_basename = join([shield_name, board_name, keymap_name], "-")

    if out_args.into:
        into_path = Path(out_args.into).expanduser()
        if into_path.is_dir():
            volumes[ARTEFACTS] = into_path, "rw"
        else:
            raise ValueError("output directory not a directory")

    patch_behaviors: list[str] = []
    if zmk_args.behaviors:
        paths = map(Path, zmk_args.behaviors)
        for base in set(path.with_suffix("") for path in paths):
            for oot, proper in behavior_patch_files(base):
                if Path(oot).is_file():
                    volumes[ZMK_HOME / proper] = oot, "ro"
                    patch_behaviors.append(proper)

    if out_args.build_dir:
        build_path = Path(out_args.build_dir)
        if build_path.is_dir():
            volumes[BUILD] = build_path, "rw"
        else:
            raise ValueError("build directory not a directory")

    py_module_dir = Path(zmk_build.__file__).parent
    volumes[ZMKUSER_HOME / "zmk_build"] = py_module_dir, "ro"

    if zmk_args.zmk and Path(zmk_args.zmk).is_dir():
        volumes[ZMK_HOME] = Path(zmk_args.zmk).expanduser(), "rw"
        dockerfile = DIR / "Dockerfile-local-src"
        image_args = docker_image_args(zmk_args.zmk_image)
    else:
        repo = ZmkGitSource.Parse(zmk_args.zmk)
        dockerfile = DIR / "Dockerfile-git-src"
        image_args = docker_image_args(zmk_args.zmk_image, repo.repo, repo.branch)

    def build_py_ags() -> Iterator[str | Path]:
        if shield_name:
            yield shield_name
        yield board_name

        yield from ("--name", output_basename)
        if out_args.extensions:
            yield from ("-f", *out_args.extensions)

        yield from ("--zmk", ZMK_HOME)
        yield from ("--zmk-config", ZMK_CONFIG)
        yield from ("--into", ARTEFACTS)
        yield from ("--build", BUILD)
        yield from extra_args

        if out_args.verbose:
            yield "--verbose"

    start_time = time()
    if patch_behaviors:
        volumes[ZMKUSER_HOME / "patch_and_build.py"] = DIR / "patch_and_build.py", "ro"
        build_script = (
            "python3",
            ZMKUSER_HOME / "patch_and_build.py",
            *patch_behaviors,
            "--",
        )
    else:
        build_script = "python3", "-m", "zmk_build"

    exit_code = run_in_container(
        dockerfile,
        image_args,
        (*build_script, *build_py_ags()),
        volumes=volumes,
        tag="zmk-hermit",
    )

    if not exit_code and out_args.into:
        into_path = Path(out_args.into).expanduser()
        for fn in into_path.glob(f"{output_basename}*.*"):
            if (
                fn.suffix.lstrip(".") in out_args.extensions
                and fn.stat().st_mtime > start_time
            ):
                logger.info(f"retrieved `{out_args.into/ fn.name}`")

    return exit_code


def behavior_patch_files(path: Path):
    base, name = path.with_suffix(""), path.stem
    yield f"{base}.c", f"app/src/behaviors/behavior_{name}.c"
    yield f"{base}.yaml", f"app/dts/bindings/behaviors/zmk,behavior-{name}.yaml"
    yield f"{base}.dtsi", f"app/dts/behaviors/{name}.dtsi"
    yield f"{base}.h", f"app/include/dt-bindings/zmk/{name}.h"


@dataclass
class KbArgs(ArgparseMixin):
    shield: str
    board: str
    keymap: Optional[str]
    zmk_config: Path

    _argparse = dict(
        shield=arg(
            nargs="?",
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
    build_dir: Optional[Path]
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
    behaviors: List[str]
    zmk: str
    zmk_image: str

    _argparse = dict(
        behaviors=arg(
            "--behavior",
            "--behaviors",
            nargs="+",
            metavar="FILE",
            help="out-of-tree behavior file(s)",
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
            default="zmkfirmware/zmk-build-arm:3.2",
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
    zmk_image: Optional[str],
    zmk_git: Optional[str] = None,
    zmk_git_branch: Optional[str] = None,
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


def join(parts: Iterable[Optional[str]], sep: str):
    return sep.join(filter(None, parts))


if __name__ == "__main__":
    exit(main())
