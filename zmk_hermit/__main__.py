import argparse
import logging
import os
import tempfile
from pathlib import Path
from time import time
from typing import Iterable, Optional

from .dockerstuff import VolumesMapping
from .dockerstuff import logger as docker_logger
from .dockerstuff import run_in_container

logger = logging.getLogger(__name__)


def main():

    parser = argparse.ArgumentParser(
        description = 'Compile out-of-tree ZMK keyboard in a Docker container.',
    )

    parser.add_argument('shield', nargs='?',
        metavar='SHIELD', help='ZMK shield name or out-of-tree shield directory')
    parser.add_argument('board',
        metavar='BOARD', help='ZMK board name or out-of-tree board directory')
    parser.add_argument('--keymap',
        metavar='FILE', help='user keymap file')

    group = parser.add_argument_group(title='output')
    ex = group.add_mutually_exclusive_group()
    ex.add_argument('-l', '--left-only', action='store_true',
        help="build only left side of split board/shield")
    ex.add_argument('-r', '--right-only', action='store_true',
        help="build only right side of split board/shield")
    group.add_argument('-f', nargs='*', dest='extensions', default=['uf2'],
        metavar='EXT', help="extension of the artefact(s) to retrieve (default: uf2)")
    group.add_argument('--into', default=tempfile.gettempdir(),
        metavar='DIR', help='directory to copy compiled .uf2 to (default: `%(default)s`)')
    group.add_argument('--build-dir',
        metavar='DIR', help='directory to store build files into')

    group = parser.add_argument_group(title='container and source')
    group.add_argument('--zmk-image',
        metavar='IMAGE', help='Docker ZMK-build image id')
    ex = group.add_mutually_exclusive_group()
    ex.add_argument('--zmk-git',
        metavar='URL', help='ZMK git repository url')
    ex.add_argument('--zmk-src',
        metavar='DIR', help='ZMK source directory')
    group.add_argument('--setup', action='store_true',
        help="initialize and update build environment")

    parser.add_argument('-p', '--pristine', action='store_true',
        help="clean build directories before starting")
    parser.add_argument('-n', '--dry-run', action='store_true',
        help="just print build commands; don't run them")
    parser.add_argument('-v', '--verbose', action='store_true',
        help="print more")

    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    for l in (logger, docker_logger):
        l.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    try:
        if args.setup:
            exit_code = run_setup(args)
            if exit_code:
                logger.warning('failed.')
                return exit_code
        return run_build(args)
    except ValueError as e:
        logger.error(f'error: {e}')
        return 2
    except KeyboardInterrupt:
        return 130



ZMKUSER = 'zmkuser'
ZMKUSER_HOME = Path('/home') / ZMKUSER
ZMK_HOME = ZMKUSER_HOME / 'zmk'
ZMK_CONFIG = Path('/zmk-config')
ARTEFACTS = Path('/artefacts')
BUILD = Path('/tmp/zmk-build')
DIR = Path(__file__).parent


def run_build(args: argparse.Namespace):
    volumes: VolumesMapping = {}

    if args.shield:
        shield_path = Path(args.shield)
        if shield_path.is_dir():
            shield_name = guess_shield_name(shield_path)
            logger.info(f'guessed shield name `{shield_name}` from `{shield_path}`')
            volumes[ZMK_CONFIG / 'boards' / 'shields' / shield_name] = shield_path, 'ro'
        elif shield_path.is_file():
            raise ValueError('out-of-tree board must be a directory')
        else:
            shield_name = str(args.shield)
    else:
        shield_name = None

    if args.board:
        board_path = Path(args.board)
        if board_path.exists():
            raise NotImplementedError('out-of-tree boards not implemented')
        else:
            board_name = str(args.board)
    else:
        board_name = None

    if args.keymap:
        keymap_path = Path(args.keymap)
        if keymap_path.is_file():
            keymap_name = keymap_path.stem
            tmp_name = shield_name or board_name
            volumes[ZMK_CONFIG / f'{tmp_name}.keymap'] = keymap_path, 'ro'
        else:
            raise ValueError()
    else:
        keymap_name = None

    if args.zmk_src:
        src_path = Path(args.zmk_src)
        if src_path.is_dir():
            volumes[ZMK_HOME] = src_path, 'rw' # may write to `zephyr/.cache`
            dockerfile = DIR / 'Dockerfile-user-src'
        else:
            raise ValueError('ZMK source must be a directory')
    else:
        dockerfile = DIR / 'Dockerfile-default'

    if args.into:
        into_path = Path(args.into)
        if into_path.is_dir():
            volumes[ARTEFACTS] = into_path, 'rw'
        else:
            raise ValueError('output directory not a directory')

    if args.build_dir:
        build_path = Path(args.build_dir)
        if build_path.is_dir():
            volumes[BUILD] = build_path, 'rw'
        else:
            raise ValueError('build directory not a directory')

    volumes[ZMKUSER_HOME / 'build.py'] = DIR / 'build.py', 'ro'

    output_basename = join([shield_name, board_name, keymap_name], '-')

    def container_args():
        yield 'python3'
        yield ZMKUSER_HOME / 'build.py'

        if shield_name:
            yield shield_name
        yield board_name

        yield from ('--name', output_basename)

        yield from ('-f', *args.extensions)

        if args.left_only:
            yield '--left-only'
        if args.right_only:
            yield '--right-only'

        yield from (
            '--zmk', ZMK_HOME,
            '--config', ZMK_CONFIG,
            '--into', ARTEFACTS,
            '--build', BUILD,
        )
        if args.pristine:
            yield '--pristine'
        if args.dry_run:
            yield '--dry-run'
        if args.verbose:
            yield '--verbose'

    start_time = time()
    exit_code = run_in_container(dockerfile,
        image_args(args.zmk_image, args.zmk_git),
        container_args(),
        volumes = volumes,
        tag='zmk-hermit'
    )
    if not exit_code and args.into:
        for fn in Path(args.into).glob(f'{output_basename}.*'):
            if fn.suffix.lstrip('.') in args.extensions and fn.stat().st_mtime > start_time:
                logger.info(f'retrieved `{fn}`')

    return exit_code



def run_setup(args: argparse.Namespace):
    volumes: VolumesMapping = {}
    if args.zmk_src:
        src_path = Path(args.zmk_src)
        if src_path.is_dir():
            volumes[ZMK_HOME] = src_path, 'rw'
            dockerfile = DIR / 'Dockerfile-user-src'
            cmds = 'west init -l app; west update; west zephyr-export'
            run_in_container(dockerfile, 
                image_args(zmk_image=args.zmk_image),
                ['bash', '-c', cmds],
                volumes = volumes,
                tag='zmk-hermit'
            )
        else:
            raise ValueError('ZMK source must be a directory')





def image_args(zmk_image: Optional[str], zmk_git: Optional[str]=None):
    if zmk_image:
        yield 'ZMK_IMAGE', zmk_image
    if zmk_git:
        yield 'ZMK_GIT', zmk_git
    yield 'UID', str(os.getuid())
    yield 'GID', str(os.getgid())
    yield 'USER', ZMKUSER



def guess_shield_name(path: Path):
    for child in path.iterdir():
        if child.suffix == '.keymap':
            return child.stem
    return path.stem



def join(parts: Iterable[Optional[str]], sep: str):
    return sep.join(filter(None, parts))



if __name__ == '__main__':
    exit(main())
