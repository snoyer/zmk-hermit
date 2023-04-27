import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Literal, Mapping, Optional, Tuple, Union

import docker

logger = logging.getLogger(__name__)


VolumeMode = Literal["ro", "rw"]
VolumesMapping = dict[Path, Tuple[Path, VolumeMode]]
DeviceMode = Literal["ro", "rw", "rwm"]
DevicesMapping = dict[Path, Tuple[Path, DeviceMode]]

PathLike = Union[Path, str]

class Volumes(VolumesMapping):
    def __setitem__(
        self,
        key: PathLike,
        value: Union[Tuple[PathLike, VolumeMode], PathLike],
    ):
        if isinstance(value, tuple):
            path, mode = value[:2]
        else:
            path, mode = value, "ro"
        super().__setitem__(Path(key), (Path(path), mode))


def run_in_container(
    dockerfile: Path,
    image_args: Iterable[Tuple[str, str]],
    container_args: Iterable[Any],
    volumes: Optional[VolumesMapping] = None,
    devices: Optional[DevicesMapping] = None,
    tag: Optional[str] = None,
    **extra_run_kwargs: Any,
):
    client = docker.from_env()

    logger.debug("building image...")
    image_id = build_docker_image(
        open(dockerfile, "rb"),
        buildargs=dict(image_args),
        tag=tag,
    )

    container_args = map(str, container_args)

    if logger.isEnabledFor(logging.DEBUG):
        container_args = list(container_args)
        logger.debug("running container...")
        if volumes:
            for bind, (path, mode) in resolve_mappings_overlaps(volumes).items():
                logger.debug(f"  using `{path}` as `{bind}` ({mode})")
        logger.debug(f"  with args: {subprocess.list2cmdline(container_args)}")

    container = client.containers.run(
        image=image_id,
        command=list(map(str, container_args)),
        volumes=format_path_mappings(volumes) if volumes else None,
        devices=format_path_mappings(devices) if devices else None,
        user=os.getuid(),
        detach=True,
        tty=True,
        **extra_run_kwargs,
    )
    try:
        out = sys.stdout.buffer
        for b in quote_stream(container.logs(stream=True)):
            out.write(b)
            out.flush()
    finally:
        container.stop(timeout=1)
        status_code = int(container.wait().get("StatusCode", -1))
        container.remove()
        logger.debug("removed container.")

        return status_code


def find_conflicts(volumes: VolumesMapping):
    for dst in volumes:
        for p in dst.parents:
            if p in volumes:
                yield p
                break


def resolve_mappings_overlaps(volumes: VolumesMapping):
    volumes_copy = dict(volumes)

    while conflicts := set(find_conflicts(volumes_copy)):
        for dst in conflicts:
            src, mode = volumes_copy[dst]
            del volumes_copy[dst]
            for x in src.iterdir():
                new_dst = dst / x.relative_to(src)
                if new_dst not in volumes_copy:
                    volumes_copy[new_dst] = x, mode

    return volumes_copy


def format_path_mappings(mapping: Mapping[Path, Tuple[Path, str]]):
    return [
        f"{path.resolve()}:{bind.resolve()}:{mode}"
        for bind, (path, mode) in mapping.items()
        if path.resolve().exists()
    ]


def build_docker_image(
    dockerfile: BinaryIO, tag: Optional[str], buildargs: Mapping[str, str]
):
    client = docker.APIClient()

    image_id = None

    for data in map(
        json.loads,
        client.build(
            fileobj=dockerfile,
            buildargs=buildargs,
            rm=True,
            tag=tag,
        ),
    ):
        if "stream" in data:
            for line in data["stream"].splitlines():
                if line.startswith(" ---> ") or re.search(r"^Step \d+/\d+ : ", line):
                    continue
                if line.strip():
                    logger.debug(line)
        if "aux" in data:
            image_id = data["aux"].get("ID")
        if "errorDetail" in data:
            raise IOError(data["errorDetail"].get("message"))

    return image_id


def quote_stream(stream: Iterable[bytes]):
    try:
        yield "\r╭─────┄┈\n".encode()
        yield from indent_stream(stream, "│ ".encode())
    finally:
        yield "\r╰─────┄┈\n".encode()


def indent_stream(stream: Iterable[bytes], indent: bytes = b"| "):
    prev = b"\n"
    for chunk in stream:
        for i in range(len(chunk)):
            b = chunk[i : i + 1]
            if prev == b"\r" and b != b"\n":
                yield indent
            elif prev == b"\n":
                yield indent
            yield b
            prev = b
    if prev not in b"\n\r":
        yield b"\r"
