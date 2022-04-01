import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO, Dict, Iterable, Literal, Tuple

import docker

logger = logging.getLogger(__name__)


VolumesMapping = Dict[Path, Tuple[Path, Literal['ro','rw']]]


def run_in_container(dockerfile: Path, image_args: Iterable[Tuple[str, str]], container_args: Iterable[str], volumes: VolumesMapping):
    client = docker.from_env()

    logger.debug('building image...')
    image_id = build_docker_image(open(dockerfile, 'rb'),
        buildargs = dict(image_args),
        tag = 'zmk-hermit',
    )

    if logger.isEnabledFor(logging.DEBUG):
        container_args = list(container_args)
        logger.debug('running container...')
        for path,(bind,mode) in volumes.items():
            logger.debug(f'  using `{path}` as `{bind}` ({mode})')
        logger.debug(f'  with args: {subprocess.list2cmdline(map(str, container_args))}')

    container = client.containers.run(image_id,
        list(map(str, container_args)),
        volumes = {path.resolve(): dict(bind=str(bind.resolve()), mode=mode)
                   for path, (bind, mode) in volumes.items()},
        user = os.getuid(),
        detach = True,
        tty = True,
    )
    try:
        out = sys.stdout.buffer
        for b in quote_stream(container.logs(stream=True)):
            out.write(b)
            out.flush()
    except KeyboardInterrupt:
        logger.warning('interrupted')
    finally:
        container.stop(timeout=1)
        status_code = int(container.wait().get('StatusCode', -1))
        container.remove()
        logger.debug('removed container.')

        return status_code


def build_docker_image(dockerfile: BinaryIO, tag: str, buildargs: Dict[str, str]):
    client = docker.APIClient()

    image_id = None

    for data in map(json.loads, client.build(
        fileobj = dockerfile,
        buildargs = buildargs,
        rm = True,
        tag = tag,
    )):
        if 'stream' in data:
            for line in data['stream'].splitlines():
                if line.startswith(' --->') or re.search(r'^Step \d+/\d+ : ', line):
                    continue
                if line.strip():
                    logger.debug(line)
        if 'aux' in data:
            image_id = data['aux'].get('ID')
        if 'errorDetail' in data:
            raise IOError(data['errorDetail'].get('message'))

    return image_id



def quote_stream(stream: Iterable[bytes]):
    yield f'╭─────┄┈\n'.encode()
    yield from indent_stream(stream, '│ '.encode())
    yield f'╰─────┄┈\n'.encode()


def indent_stream(stream: Iterable[bytes], indent: bytes=b'| '):
    prev = b'\n'
    for chunk in stream:
        for i in range(len(chunk)):
            b = chunk[i:i+1]
            if prev==b'\r' and b!=b'\n':
                yield indent
            elif prev == b'\n':
                yield indent
            yield b
            prev = b
    if not prev in b'\n\r':
        yield b'\r'
