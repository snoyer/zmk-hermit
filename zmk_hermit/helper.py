import shutil
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description = 'Compile out-of-tree QMK keyboard/layouts.',
    )

    parser.add_argument('shield', nargs='?',
        metavar='SHIELD', help='ZMK shield name')
    parser.add_argument('board',
        metavar='BOARD',  help='ZMK board name')


    ex = parser.add_mutually_exclusive_group()
    ex.add_argument('-l', '--left-only', action='store_true',
        help='build only left side')
    ex.add_argument('-r', '--right-only', action='store_true',
        help='build only right side')

    parser.add_argument('--name',
        metavar='NAME',  help='basename for the artefact(s)')


    parser.add_argument('--zmk-home', default='/home/zmkuser/zmk',
        metavar='DIR',  help='ZMK directory')
    parser.add_argument('--zmk-config', default='/zmk-config',
        metavar='DIR',  help='user configuration directory')
    parser.add_argument('--artefacts', default='/artefacts',
        metavar='DIR',  help='artefacts destination directory')


    args = parser.parse_args()


    APP = Path(args.zmk_home) / 'app'
    CONF = Path(args.zmk_config)
    ARTEFACTS = Path(args.artefacts)


    def to_compile():
        if args.shield:
            shield_path = find_dir(
                CONF / 'boards/shields' / args.shield,
                APP  / 'boards/shields' / args.shield,
            )

            if shield_path and guess_is_split(shield_path):
                print(f'guessing shield `{shield_path}` is split')
                if not args.right_only:
                    yield f'{args.shield}_left' , args.board, 'left'
                if not args.left_only:
                    yield f'{args.shield}_right', args.board, 'right'
            else:
                yield args.shield, args.board, None
        else:
            yield None, args.board, None


    for shield, board, tag in to_compile():
        basename = args.name if args.name else '-'.join(filter_none(shield, board))
        output_name = '.'.join(filter_none(basename, tag, 'uf2'))

        status_code = run_command(west_build_command(board, shield, conf_dir=CONF))

        if status_code != 0:
            raise IOError('build failed')
        elif ARTEFACTS.is_dir():
            copy_file('build/zephyr/zmk.uf2', ARTEFACTS / output_name)




def guess_is_split(path):
    for child in path.iterdir():
        if child.match('*_left.conf') \
        or child.match('*_right.conf'):
            return True

def guess_shield_name(path):
    for child in path.iterdir():
        if child.suffix == '.keymap':
            return child.stem




def west_build_command(board, shield=None, conf_dir=None):

    west_cmd = [
        'west', 'build',
        '--pristine',
        '-s', 'app',
        '-b', board,
    ]

    cmake_args = [f'-D{k}={v}' for k,v in [
        ('SHIELD', shield),
        ('ZMK_CONFIG', conf_dir),
    ] if v]


    if cmake_args:
        return *west_cmd ,'--', *cmake_args
    else:
        return west_cmd


def find_dir(*candidates):
    for candidate in map(Path, candidates):
        if candidate.is_dir():
            return candidate


def run_command(cmd):
    print(f'`{subprocess.list2cmdline(cmd)}`')
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    blockquote_process_output(process)
    process.wait()

    return process.returncode


def copy_file(src, dst):
    shutil.copy(src, dst)
    print(f'copied `{src}` to `{dst}`')




def blockquote_stream_lines(stream, prefix='', suffix='', tmp_prefix='', read_by=1):
    prev = '\n'
    for c in iter(lambda: stream.read(read_by), ''):
        if prefix and prev == '\n':
            if tmp_prefix:
                yield '\r'
            yield prefix
        if suffix and c == '\n':
            yield suffix
        yield c
        if prefix and tmp_prefix and c == '\n':
            yield tmp_prefix
        prev = c


def blockquote_process_output(process, out=sys.stdout):
    out.write('┎─\n')
    for c in blockquote_stream_lines(process.stdout, prefix='┃ ', tmp_prefix='┋'):
        out.write(c)
        out.flush()
    out.write('\r┖─\n')


def blockquote_lines(lines, out=sys.stdout):
    out.write('┎─\n')
    for line in lines:
        out.write('┃ '+line+'\n')
        out.flush()
    out.write('\r┖─\n')




def filter_none(*xs):
    return filter(None, xs)


if __name__ == '__main__':
    import argparse
    main()
