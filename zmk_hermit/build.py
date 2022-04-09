import argparse
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description = 'ZMK build helper; runs Zephyr build(s) and retrieves artefacts.',
    )

    parser.add_argument('shield', nargs='?',
        metavar='SHIELD', help="shield name")
    parser.add_argument('board',
        metavar='BOARD', help="board name")

    group = parser.add_argument_group(title='artefacts output')
    ex = group.add_mutually_exclusive_group()
    ex.add_argument('-l', '--left-only', action='store_true',
        help="build only left side of split board/shield")
    ex.add_argument('-r', '--right-only', action='store_true',
        help="build only right side of split board/shield")
    group.add_argument('-f', nargs='*', dest='extensions', default=['uf2'],
        metavar='EXT', help="extension of the artefact(s) to retrieve (default: uf2)")
    group.add_argument('--name', default='{shield-board}',
        metavar='NAME', help="basename used to rename the artefact(s)")

    default_zmk = Path(__file__).parent.resolve()
    default_config = default_zmk.parent / 'zmk-config'
    default_build = Path(tempfile.gettempdir()) / 'zmk-build'

    group = parser.add_argument_group(title='directories')
    group.add_argument('--zmk', default=default_zmk,
        metavar='DIR', help='ZMK base directory (default: %(default)s)')
    group.add_argument('--config', default=default_config,
        metavar='DIR', help="zmk-config directory (default: %(default)s)")
    group.add_argument('--build', default=default_build,
        metavar='DIR', help="build directory (default: %(default)s)")
    group.add_argument('--into', default=default_config,
        metavar='DIR', help="artefacts destination directory (default: %(default)s)")

    parser.add_argument('-p', '--pristine', action='store_true',
        help="clean build directories before starting")
    parser.add_argument('-n', '--dry-run', action='store_true',
        help="just print build commands; don't run them")
    parser.add_argument('-v', '--verbose', action='store_true',
        help="print more")

    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    ZMK_APP = Path(args.zmk) / 'app'
    ZMK_CFG = Path(args.config)
    ARTEFACTS = Path(args.into)
    BUILD = Path(args.build)

    def items_to_compile(board: str, shield: Optional[str]):
        if shield:
            shield_path = find_dir(
                ZMK_CFG / 'boards' / 'shields' / shield,
                ZMK_APP / 'boards' / 'shields' / shield,
            )
            if shield_path:
                logger.debug(f'found shield `{shield}` at `{shield_path}`')

            if shield_path and guess_is_shield_split(shield_path):
                logger.debug(f'guessing shield is split')
                yield board, shield, 'left'
                yield board, shield, 'right'
            else:
                yield board, shield, None
        else:
            yield board, None, None


    for board, shield, side in items_to_compile(args.board, args.shield):
        if args.left_only and side != 'left':
            continue
        if args.right_only and side != 'right':
            continue

        shield_side = join([shield, side], '_')
        build_dir = BUILD / join([shield_side, board], '-')
        basename = args.name.format(**{
            'shield': shield,
            'board': board,
            'shield-board': join([shield, board], '-'),
        })

        west_cmd = west_build_command(board, shield_side,
            app_dir=ZMK_APP,
            zmk_config=ZMK_CFG if ZMK_CFG.is_dir() else None,
            build_dir=build_dir,
            pristine=args.pristine)

        logger.info(f'run `{subprocess.list2cmdline(west_cmd)}`')
        if not args.dry_run:
            process = subprocess.Popen(west_cmd, cwd=ZMK_APP, text=True)
            process.wait()
            if process.returncode != 0:
                logger.error('build failed')
                return process.returncode

        for ext in args.extensions:
            temp_output = build_dir / 'zephyr' / f'zmk.{ext}'
            final_output = ARTEFACTS / join([basename, side, ext], '.')

            logger.info(f'copy `{temp_output}` to `{final_output}`')
            if not args.dry_run:
                if temp_output.is_file():
                    shutil.copy(temp_output, final_output)
                else:
                    logger.warning(f'`{temp_output}` is not a file')



def guess_is_shield_split(shield_dir: Path) -> bool:
    for child in shield_dir.iterdir():
        if child.match('*_left.*') \
        or child.match('*_right.*'):
            return True
    return False



def west_build_command(board: str, shield: Optional[str] = None,
                       app_dir: Optional[Path] = None,
                       build_dir: Optional[Path] = None,
                       zmk_config: Optional[Path] = None,
                       pristine: bool = False) -> List[str]:
    west_cmd = [
        'west', 'build',
        '-b', board,
        '--pristine', 'always' if pristine else 'auto',
    ]
    if app_dir:
        west_cmd += ['-s', str(app_dir)]
    if build_dir:
        west_cmd += ['-d', str(build_dir)]

    cmake_args = [f'-D{k}={v}' for k, v in [
        ('SHIELD', shield),
        ('ZMK_CONFIG', zmk_config),
    ] if v]
    if cmake_args:
        west_cmd += ['--', *cmake_args]

    return west_cmd



def find_dir(*candidates: Path) -> Optional[Path]:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate


def join(parts: Iterable[Optional[str]], sep: str) -> str:
    return sep.join(filter(None, parts))



if __name__ == '__main__':
    exit(main())
