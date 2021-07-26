import argparse
import hashlib
import json
import io
import os
import re
import shlex
import tarfile
import tempfile
from pathlib import Path

import docker

from zmk_hermit import *


ZMK_REPO = 'https://github.com/zmkfirmware/zmk.git'
ZMK_IMAGE = 'zmkfirmware/zmk-build-arm:2.5'




def main():

    parser = argparse.ArgumentParser(
        description = 'Compile out-of-tree ZMK keyboard in a Docker container.',
    )

    group = parser.add_argument_group(title='Keyboard')
    group.add_argument('shield', nargs='?',
        metavar='SHIELD', help='ZMK shield name or out-of-tree shield directory')
    group.add_argument('board',
        metavar='BOARD',  help='ZMK board name or out-of-tree board directory')
    group.add_argument('--keymap',
        metavar='FILE',  help='user keymap file')


    group = parser.add_argument_group(title='Output')
    group.add_argument('--into', default=tempfile.gettempdir(),
        metavar='DIR', help='directory to copy compiled .uf2 to (default: `%(default)s`)')
    excl = group.add_mutually_exclusive_group()
    excl.add_argument('-l', '--left-only', action='store_true',
        help='build only left side (for split keyboards)')
    excl.add_argument('-r', '--right-only', action='store_true',
        help='build only right side (for split keyboards)')


    group = parser.add_argument_group(title='Container')
    group.add_argument('--zmk-image', default=ZMK_IMAGE,
        metavar='IMAGE', help='Docker ZMK-build image id (default: `%(default)s`)')
    group.add_argument('--zmk-repo', default=ZMK_REPO,
        metavar='URL', help='ZMK git repository url (default: `%(default)s`)')


    try:
        return _main(parser.parse_args())
    except KeyboardInterrupt:
        return 1


def _main(args):


    ZMK_CONFIG = Path('/zmk-config')
    ARTEFACTS = Path('/artefacts')

    volumes = {}


    if args.into:
        path = Path(args.into)
        if path.is_dir():
            volumes[path.resolve()] = ARTEFACTS, 'rw'
        else:
            raise ValueError('output directory not a directory')


    if args.shield:
        path = Path(args.shield)
        if path.is_dir():
            shield_name = guess_shield_name(path)
            print(f'guessed shield name `{shield_name}` from `{path}`')
            volumes[path.resolve()] = ZMK_CONFIG / 'boards/shields' / shield_name, 'ro'
        elif path.is_file():
            raise ValueError()
        else:
            shield_name = args.shield
    else:
        shield_name = args.shield


    if Path(args.board).is_dir():
        raise NotImplementedError('out-of-tree boards not implemented yet')
    else:
        board_name = args.board


    if args.keymap:
        path = Path(args.keymap)
        if path.is_file():
            volumes[path.resolve()] = ZMK_CONFIG / f'{shield_name}.keymap', 'ro'
            keymap_name = path.stem
        else:
            raise ValueError()
    else:
        keymap_name = None



    def container_args():
        output_name = '-'.join(filter_none(shield_name, board_name, keymap_name))

        yield from (
            *filter_none(shield_name, board_name),
            '--name', output_name,
            '--zmk-config', ZMK_CONFIG,
            '--artefacts', ARTEFACTS,
        )

        if args.left_only:
            yield '--left-only'
        if args.right_only:
            yield '--right-only'


    client = docker.from_env()

    print('building image...')

    image_id = build_docker_image(Path(__file__).parent,
        buildargs = dict(
            ZMK_IMAGE = args.zmk_image,
            ZMK_REPO  = args.zmk_repo,
            UID = str(os.getuid()),
            GID = str(os.getgid()),
        ),
        tag = 'zmk-hermit',
    )


    print('running container...')
    if volumes:
        print('  with ' + '\n       '.join(f'`{path}` as `{bind}` ({mode})'
                                           for path,(bind,mode) in volumes.items()))
    print()

    container = client.containers.run(image_id,
        list(map(str, container_args())),
        volumes = {path: dict(bind=str(bind), mode=mode) for path,(bind,mode) in volumes.items()},
        detach = True,
        user = os.getuid(),
    )
    try:
        for line in container.logs(stream=True):
            line = line.decode().rstrip()

            # override `[xx/yy] ...` lines to limit output
            if re.search(r'^\W*\[\d+/\d+\]', line):
                print('\033[F\033[K', end='') # up and clear line

            print(line)

    except KeyboardInterrupt:
        logger.warning('interrupted')
    finally:
        container.stop(timeout=1)
        status_code = container.wait().get('StatusCode', -1)
        print('removing container...')
        container.remove()
        print('done.')

        return status_code




def build_docker_image(path, tag=None, client=None, buildargs=None):
    client = docker.APIClient()

    image_data = {}

    def output_lines():
        for data in map(json.loads, client.build(
                str(path),
                buildargs = buildargs,
                rm = True,
                tag = tag,
            )):
            if 'stream' in data:
                for line in data['stream'].splitlines():
                    if line.startswith(' --->') or re.search(r'^Step \d+/\d+ : ', line):
                        continue
                    if line.strip():
                        yield line
            if 'aux' in data:
                image_data['id'] = data['aux'].get('ID')
            if 'errorDetail' in data:
                raise IOError(data['errorDetail'].get('message'))

    blockquote_lines(output_lines())

    return image_data.get('id')




if __name__ == '__main__':
    main()
