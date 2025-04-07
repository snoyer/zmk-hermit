import re
import tempfile
from pathlib import Path
from typing import Iterable


def modular_behaviors_shield_contents(behavior_files: Iterable[Path], shield_dir: Path):
    behavior_files = list(behavior_files)
    shield_name = re.sub(r"\W", "_", shield_dir.name)

    # new `.overlay` and `Kconfig.shield` files needed for the shield to be valid
    yield shield_dir / f"{shield_name}.overlay", [""]
    Kconfig = [
        f"config SHIELD_{shield_name.upper()}",
        f"   def_bool $(shields_list_contains,{shield_name})",
    ]
    yield (shield_dir / "Kconfig.shield", Kconfig)

    # new `CMakeLists.txt` file needed to include each behavior's `.cmake` file
    CMakeLists = [
        "target_include_directories(app PRIVATE ${CMAKE_SOURCE_DIR}/include)",
        *(f"include({f.name})" for f in behavior_files if f.suffix == ".cmake"),
    ]
    yield (shield_dir / "CMakeLists.txt", CMakeLists)

    # existing source files are relocated
    for behavior_file in behavior_files:
        yield shield_dir / _location_for_file(behavior_file), behavior_file


LOCATION_TEMPLATE_BY_SUFFIX = {
    ".dt.h": "include/dt-bindings/zmk/{stem}.h",
    ".h": "include/{name}",
    ".yaml": "dts/bindings/behaviors/{name}",
    ".dtsi": "include/behaviors/{name}",
}


def _location_for_file(path: Path):
    for suffix, template in LOCATION_TEMPLATE_BY_SUFFIX.items():
        if path.name.endswith(suffix):
            return template.format(name=path.name, stem=path.name.removesuffix(suffix))
    return path.name


class ModularBehaviorsShieldFiles:
    def __init__(self, behavior_files: Iterable[Path], shield_dir: Path):
        self.files: dict[Path, Path] = {}
        self.temp_files: set[Path] = set()

        for path_in_shield, contents in modular_behaviors_shield_contents(
            behavior_files, shield_dir
        ):
            if isinstance(contents, Path):
                self.files[path_in_shield] = contents
            else:
                with tempfile.NamedTemporaryFile(
                    "w", suffix=path_in_shield.suffix, delete=False
                ) as f:
                    for line in contents:
                        f.write(line)
                        f.write("\n")
                    self.files[path_in_shield] = Path(f.name)
                    self.temp_files.add(Path(f.name))

    def __iter__(self):
        return (
            (actual_path, path_in_shield)
            for path_in_shield, actual_path in self.files.items()
        )
