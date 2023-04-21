import argparse
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description = "ZMK build helper; runs Zephyr build(s) and retrieves artefacts.",
        epilog = "Extra arguments are passed to `west build` command."
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
        metavar='NAME', help="basename used to rename the artefact(s) (default: %(default)s)")

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

    args, extra_args = parser.parse_known_args()

    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    ZMK = Path(args.zmk)
    ZMK_APP = ZMK / 'app'
    ZMK_CFG = Path(args.config)
    ARTEFACTS = Path(args.into)
    BUILD = Path(args.build)

    try:
        check_west_cmd = ['west', '--help', 'build']
        subprocess.check_call(check_west_cmd, cwd=ZMK_APP, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        logger.warning('need to initalize west')
        for west_init_cmd in [
            ['west', 'init', '-l', ZMK_APP],
            ['west', 'update'],
            ['west', 'zephyr-export'],
        ]:
            logger.info(f'run `{subprocess.list2cmdline(west_init_cmd)}`')
            subprocess.check_call(west_init_cmd, cwd=ZMK, text=True)

    def items_to_compile(board: str, shield: Optional[str]):
        if shield:
            shield_path = find_dir(
                ZMK_CFG / 'boards' / 'shields' / shield,
                ZMK_APP / 'boards' / 'shields' / shield,
            )
            if shield_path:
                logger.debug(f'found shield `{shield}` at `{shield_path}`')

            if shield_path:
                sides = guess_split_shield_sides(shield_path, shield)
                if sides:
                    logger.debug(f'guessing shield is split ({", ".join(sides)})')
                    for side in sides:
                        yield board, shield, side
                else:
                    yield board, shield, None
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

        west_build_cmd = west_build_command(board, shield_side,
            app_dir=ZMK_APP,
            zmk_config=ZMK_CFG if ZMK_CFG.is_dir() else None,
            build_dir=build_dir,
            pristine=args.pristine,
            extra_args=extra_args)

        logger.info(f'run `{subprocess.list2cmdline(west_build_cmd)}`')
        if not args.dry_run:
            try:
                subprocess.check_call(west_build_cmd, cwd=ZMK_APP, text=True)
            except subprocess.CalledProcessError as e:
                logger.error('build failed')
                return e.returncode

        for ext in args.extensions:
            temp_output = build_dir / 'zephyr' / f'zmk.{ext}'
            final_output = ARTEFACTS / join([basename, side, ext], '.')

            logger.info(f'copy `{temp_output}` to `{final_output}`')
            if not args.dry_run:
                if temp_output.is_file():
                    shutil.copy(temp_output, final_output)
                else:
                    logger.warning(f'`{temp_output}` is not a file')



def guess_split_shield_sides(shield_path: Path, shield_name: str):
    def find_all():
        for line in open(shield_path / 'Kconfig.defconfig'):
            for m in re.findall(fr'SHIELD_{shield_name}_(\w+)', line, flags=re.I):
                yield str(m).lower()
    return set(find_all())


def west_build_command(board: str, shield: Optional[str] = None,
                       app_dir: Optional[Path] = None,
                       build_dir: Optional[Path] = None,
                       zmk_config: Optional[Path] = None,
                       pristine: bool = False,
                       extra_args: Optional[Iterable[str]]=None) -> List[str]:
    def args():
        yield from ('-b', board)
        
        yield from ('--pristine', 'always' if pristine else 'auto')
        if app_dir:
            yield from ('-s', str(app_dir))
        if build_dir:
            yield from ('-d', str(build_dir))
        
        if extra_args:
            yield from extra_args
        
        cmake_args = [f'-D{k}={v}' for k, v in [
            ('SHIELD', shield),
            ('ZMK_CONFIG', zmk_config),
        ] if v]
        if cmake_args:
            yield from ('--', *cmake_args)
    
    return ['west', 'build', *args()]



def find_dir(*candidates: Path) -> Optional[Path]:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate


def join(parts: Iterable[Optional[str]], sep: str) -> str:
    return sep.join(filter(None, parts))



if __name__ == '__main__':
    exit(main())
