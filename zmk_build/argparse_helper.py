from __future__ import annotations

import re
from argparse import (
    ArgumentParser,
    FileType,
    Namespace,
    _ArgumentGroup,  # type: ignore
)
from typing import Any, Callable, Iterable, Sequence, TypeVar

T = TypeVar("T")


class arg:
    def __init__(
        self,
        *option_strings: str,
        nargs: int | str | None = None,
        const: T | None = None,
        default: T | str | None = None,
        type: Callable[[str], T] | FileType | None = None,
        action: str | None = None,
        choices: Iterable[T] | None = None,
        required: bool | None = None,
        help: str | None = None,
        metavar: str | tuple[str, ...] | None = None,
        _parse: Callable[[str], T] | None = None,
        _dump: Callable[[Any], str] | None = None,
    ) -> None:
        if not all(x.startswith("-") for x in option_strings):
            self.option_strings: tuple[str, ...] = tuple()
        else:
            self.option_strings = option_strings

        self.nargs = nargs
        self.const = const
        self.default = default
        self.type = type
        self.action = action
        self.choices = choices
        self.required = required
        self.help = help
        self.metavar = metavar

        self.parse: Callable[[str], Any] = _parse or (lambda x: x)
        self.dump = _dump or str

    def kwargs(self, dest: str):
        all_kwargs = dict(
            dest=dest,
            nargs=self.nargs,
            const=self.const,
            default=self.default,
            type=self.type,
            action=self.action,
            choices=self.choices,
            required=self.required,
            help=self.help,
            metavar=self.metavar,
        )
        kwargs = {k: v for k, v in all_kwargs.items() if v is not None}

        if not self.metavar:
            kwargs["metavar"] = dest.upper()

        return kwargs


class mutually_exclusive(dict[str, arg]):
    pass


class ArgparseMixin:
    _argparse: dict[str, arg] | Sequence[dict[str, arg]]
    _argparse_prefix: str = ""
    _argparse_suffix: str = ""

    @classmethod
    def From_args(cls, args: list[str]):
        parser = ArgumentParser()
        cls.Add_arguments(parser)
        parsed_args, _unknown_args = parser.parse_known_args(args)
        return cls.From_parsed_args(parsed_args)

    @classmethod
    def From_parsed_args(cls, parsed_args: Namespace):
        return cls(
            **{
                k: _v.parse(getattr(parsed_args, cls._prefix_dest(k)))
                for k, _v in cls._argparse_args()
            }
        )

    def to_args(self):
        def args_iter():
            for attr_name, arg in self._argparse_args():
                attr = getattr(self, attr_name, None)
                if attr is not None:
                    yield arg.option_strings[0]
                    yield arg.dump(attr)

        return list(args_iter())

    @classmethod
    def Add_arguments(
        cls, parser: ArgumentParser | _ArgumentGroup, group: str | None = None
    ):
        if group:
            parser = parser.add_argument_group(title=group)

        for argparse_group in cls._argparse_groups():
            if isinstance(argparse_group, mutually_exclusive):
                add_to = parser.add_mutually_exclusive_group()
            else:
                add_to = parser

            for attr_name, arg in argparse_group.items():
                args = arg.option_strings
                if cls._argparse_prefix or cls._argparse_suffix:
                    args = [
                        re.sub(
                            r"^--(.+)",
                            rf"--{cls._argparse_prefix}\1{cls._argparse_suffix}",
                            arg,
                        )
                        for arg in args
                    ]
                kwargs = arg.kwargs(dest=attr_name)
                kwargs["dest"] = cls._prefix_dest(attr_name)
                try:
                    add_to.add_argument(*args, **kwargs)  # type: ignore
                except TypeError as e:
                    if re.search(r"unexpected.*metavar", str(e)):
                        kwargs.pop("metavar")
                        add_to.add_argument(*args, **kwargs)  # type: ignore
                    else:
                        raise

    @classmethod
    def _argparse_groups(cls) -> Sequence[dict[str, arg]]:
        if isinstance(cls._argparse, dict):
            return [cls._argparse]
        else:
            return cls._argparse

    @classmethod
    def _argparse_args(cls) -> Iterable[tuple[str, arg]]:
        for group in cls._argparse_groups():
            yield from group.items()

    @classmethod
    def _prefix_dest(cls, dest: str):
        return f"{cls.__name__}_{dest}"


def yes_no_arg(*option_strings: str, help: str):
    def yn_to_bool(s: str | None):
        if s is not None:
            return s.lower().startswith("y")

    def yn_from_bool(b: bool):
        return "yes" if b else "no"

    return arg(
        *option_strings,
        help=help,
        choices=["yes", "no", "y", "n"],
        nargs="?",
        const="y",
        metavar="yes/no",
        _parse=yn_to_bool,
        _dump=yn_from_bool,
    )
