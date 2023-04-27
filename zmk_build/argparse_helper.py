from __future__ import annotations

import re
from argparse import _ArgumentGroup  # type: ignore
from argparse import ArgumentParser, FileType, Namespace
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Tuple, TypeVar

T = TypeVar("T")


class arg:
    def __init__(
        self,
        *option_strings: str,
        nargs: Optional[int | str] = None,
        const: Optional[T] = None,
        default: Optional[T | str] = None,
        type: Optional[Callable[[str], T] | FileType] = None,
        action: Optional[str] = None,
        choices: Optional[Iterable[T]] = None,
        required: Optional[bool] = None,
        help: Optional[str] = None,
        metavar: Optional[str | Tuple[str, ...]] = None,
        _parse: Optional[Callable[[str], T]] = None,
        _dump: Optional[Callable[[Any], str]] = None,
    ) -> None:
        if not all(x.startswith("-") for x in option_strings):
            self.option_strings: tuple[str] = tuple()
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

        self.parse = _parse or (lambda x: x)
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


class mutually_exclusive(Dict[str, arg]):
    pass


class ArgparseMixin:
    _argparse: dict[str, arg] | Sequence[dict[str, arg]]

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
        cls, parser: ArgumentParser | _ArgumentGroup, group: Optional[str] = None
    ):
        if group:
            parser = parser.add_argument_group(title=group)

        for argparse_group in cls._argparse_groups():
            if isinstance(argparse_group, mutually_exclusive):
                add_to = parser.add_mutually_exclusive_group()
            else:
                add_to = parser

            for attr_name, arg in argparse_group.items():
                kwargs = arg.kwargs(dest=attr_name)
                kwargs["dest"] = cls._prefix_dest(attr_name)
                try:
                    add_to.add_argument(*arg.option_strings, **kwargs)
                except TypeError as e:
                    if re.search(r"unexpected.*metavar", str(e)):
                        kwargs.pop("metavar")
                        add_to.add_argument(*arg.option_strings, **kwargs)
                    else:
                        raise

    @classmethod
    def _argparse_groups(cls):
        if isinstance(cls._argparse, dict):
            return [cls._argparse]
        else:
            return cls._argparse

    @classmethod
    def _argparse_args(cls):
        for group in cls._argparse_groups():
            yield from group.items()

    @classmethod
    def _prefix_dest(cls, dest: str):
        return f"{cls.__name__}_{dest}"


def yes_no_arg(*option_strings: str, help: str):
    def yn_to_bool(s: Optional[str]):
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
        metavar="Yes/no",
        _parse=yn_to_bool,
        _dump=yn_from_bool,
    )
