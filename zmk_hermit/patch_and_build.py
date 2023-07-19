from __future__ import annotations
import argparse
from dataclasses import asdict, dataclass, field
from itertools import takewhile
import json
import logging
from pathlib import Path
import re
import shutil
from contextlib import ExitStack, contextmanager
import sys
from typing import List, Literal, TextIO, Tuple

from zmk_build.__main__ import main as build_main
from zmk_build.__main__ import Directories

CMakeListsPatch = Tuple[str, Literal["before", "after"], str]

logger = logging.getLogger(__name__)


def main(argv: list[str]):
    it = iter(argv[1:])
    args = list(takewhile(lambda a: not a.startswith("--"), it))
    unknown_args = list(it)

    logging.basicConfig(level=logging.DEBUG)

    DIRECTORIES = Directories.From_args(unknown_args)

    behaviors = [str(Path(a).relative_to("app")) for a in args]
    patch = ZmkPatch(
        behavior_c_sources=[f for f in behaviors if f.endswith(".c")],
        behavior_dtsi_sources=[f for f in behaviors if f.endswith(".dtsi")],
    )

    with patch.patch_applied(DIRECTORIES.zmk_app):
        return build_main(unknown_args)


@dataclass
class ZmkPatch:
    behavior_c_sources: List[str] = field(default_factory=list)
    behavior_dtsi_sources: List[str] = field(default_factory=list)
    patch_comment = "zmk-hermit"

    @contextmanager
    def patch_applied(self, zmk_app: Path):
        def files_to_patch():
            if self.behavior_c_sources:
                yield zmk_app / "CMakeLists.txt", self.patch_CMakeLists
            if self.behavior_dtsi_sources:
                yield zmk_app / "dts" / "behaviors.dtsi", self.patch_behaviors_dtsi

        with ExitStack() as stack:
            for path, patch_func in files_to_patch():
                stack.enter_context(backedup_file(Path(path)))
                patch_func(Path(path))
            yield

    def patch_behaviors_dtsi(self, behaviors_dtsi: Path):
        if not self.behavior_dtsi_sources:
            return

        with open(behaviors_dtsi, "a") as f:
            f.write("\n")
            for fn in self.behavior_dtsi_sources:
                fn = Path(fn).relative_to(Path("dts"))
                f.write(f"#include <{fn}> // {self.patch_comment}\n")
            f.write("\n")

    def patch_CMakeLists(self, cmakelist_txt: Path):
        if not self.behavior_c_sources:
            return

        cmakelist_txt_contents = open(cmakelist_txt).readlines()
        with open(cmakelist_txt, "w") as f:
            for line in cmakelist_txt_contents:
                if re.match(r"\s*if \(CONFIG_ZMK_BLE\)", line):
                    for fn in self.behavior_c_sources:
                        target_sources = f"target_sources(app PRIVATE {fn})"
                        f.write(f"  {target_sources} # {self.patch_comment}\n")
                    f.write(line)
                else:
                    f.write(line)

    def __bool__(self):
        return bool(self.behavior_c_sources) or bool(self.behavior_dtsi_sources)


@contextmanager
def backedup_file(fn: Path):
    fn_bak = Path(f"{fn}.bak")
    logger.debug("backing up %s -> %s", fn, fn_bak)
    shutil.copy(fn, fn_bak)
    try:
        yield fn_bak
    finally:
        logger.debug("restoring %s <- %s", fn, fn_bak)
        shutil.copy(fn_bak, fn)
        fn_bak.unlink()


if __name__ == "__main__":
    exit(main(sys.argv))
