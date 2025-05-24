from __future__ import annotations

import re
from argparse import (
    Action,
    ArgumentParser,
    FileType,
    Namespace,
    _ArgumentGroup,  # type: ignore
)
from collections import defaultdict
from dataclasses import (
    _MISSING_TYPE,  # type: ignore
    MISSING,
    field,
    fields,
)
from typing import Any, Callable, Iterable, Iterator, Sequence, TypeVar, cast

T = TypeVar("T")
METADATA_KEY_ARG = "_arg"
METADATA_KEY_TO_ARG = "_to_arg"


class Arg:
    def __init__(
        self,
        *name_or_flags: str,
        action: str | type[Action] | None = None,
        nargs: int | str | None = None,
        const: Any | None = None,
        default: Any | None = None,
        type: Callable[[str], T] | None = None,
        choices: Iterable[T] | None = None,
        required: bool | None = None,
        help: str | None = None,
        metavar: str | tuple[str, ...] | None = None,
        # dest: str | None = None,
        # version: str | None = None,
        # **kwargs: Any,
    ) -> None:
        self.name_or_flags = name_or_flags

        self.nargs = nargs
        self.const = const
        self.default = default
        self.type = type
        self.action = action
        self.choices = choices
        self.required = required
        self.help = help
        self.metavar = metavar

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


class ArgparseMixin:
    _argparse_mutually_exclusive: Sequence[Sequence[str]] = ()

    @classmethod
    def From_args(cls, args: Namespace | Iterable[str]):
        if isinstance(args, Namespace):
            parsed_args = args
        else:
            parser = ArgumentParser()
            cls.Add_arguments(parser)
            parsed_args, _unknown_args = parser.parse_known_args(list(args))

        return cls(
            **{
                attr_name: getattr(parsed_args, cls._prefix_dest(attr_name))
                for attr_name, _arg, _ in cls._argparse_args()
            }
        )

    def to_args(self):
        def args_iter() -> Iterator[str]:
            for attr_name, arg, to_arg in self._argparse_args():
                attr = getattr(self, attr_name, None)
                name_or_flags = self._fix_name_or_flags(arg.name_or_flags)

                if callable(to_arg):
                    yield from to_arg(name_or_flags, attr)
                elif arg.action == "store_true":
                    if attr is True:
                        yield name_or_flags[0]
                elif arg.action == "store_false":
                    if attr is False:
                        yield name_or_flags[0]
                # TODO more built-in actions?
                elif attr != arg.default:
                    yield name_or_flags[0]
                    if isinstance(attr, list):
                        yield from map(str, attr)  # type: ignore
                    else:
                        yield str(attr)

        return list(args_iter())

    @classmethod
    def Add_arguments(
        cls, parser: ArgumentParser | _ArgumentGroup, group: str | None = None
    ):
        if group:
            parser = parser.add_argument_group(title=group)

        name_to_mutex_index = {
            name: i
            for i, names in enumerate(cls._argparse_mutually_exclusive)
            for name in names
        }
        mutex_groups: dict[int, _ArgumentGroup | ArgumentParser] = defaultdict(
            lambda: parser.add_mutually_exclusive_group()
        )

        for attr_name, arg, _ in cls._argparse_args():
            try:
                add_to = mutex_groups[name_to_mutex_index[attr_name]]
            except KeyError:
                add_to = parser

            kwargs = arg.kwargs(dest=attr_name)
            kwargs["dest"] = cls._prefix_dest(attr_name)

            name_or_flags = cls._fix_name_or_flags(arg.name_or_flags)
            if not all(f.startswith("-") for f in name_or_flags):
                name_or_flags = []

            try:
                add_to.add_argument(*name_or_flags, **kwargs)  # type: ignore
            except TypeError as e:
                if re.search(r"unexpected.*metavar", str(e)):
                    kwargs.pop("metavar")
                    add_to.add_argument(*name_or_flags, **kwargs)  # type: ignore
                else:
                    raise

    @classmethod
    def _argparse_args(
        cls,
    ) -> Iterable[
        tuple[str, Arg, Callable[[Sequence[str], Any], Iterable[str]] | None]
    ]:
        class_fields = fields(cls)  # type: ignore
        for f in class_fields:
            try:
                arg = cast(Arg, f.metadata[METADATA_KEY_ARG])
                if not arg.name_or_flags:
                    auto_flag = f"-{f.name}" if len(f.name) == 1 else f"--{f.name}"
                    arg.name_or_flags = (auto_flag,)
                yield f.name, arg, f.metadata.get(METADATA_KEY_TO_ARG)
            except KeyError:
                pass

    @classmethod
    def _fix_name_or_flags(cls, name_or_flags: tuple[str, ...]):
        return list(name_or_flags)

    @classmethod
    def _prefix_dest(cls, dest: str):
        return f"{cls.__qualname__}_{dest}"


def arg_field(
    *name_or_flags: str,
    nargs: int | str | None = None,
    const: T | None = None,
    default: Any = MISSING,
    type: Callable[[str], T] | FileType | None = None,
    action: str | None = None,
    choices: Iterable[T] | None = None,
    required: bool | None = None,
    help: str | None = None,
    metavar: str | tuple[str, ...] | None = None,
    #
    _to_arg: Callable[[Sequence[str], T], Iterable[str]] | None = None,
) -> Any:
    missing_default = isinstance(default, _MISSING_TYPE)
    typed_default = type(default) if callable(type) and not missing_default else default
    arg = Arg(
        *name_or_flags,
        nargs=nargs,
        const=const,
        default=None if missing_default else typed_default,
        type=type,
        action=action,
        choices=choices,
        required=required,
        help=help,
        metavar=metavar,
    )
    return field(
        default_factory=lambda: typed_default,
        metadata={METADATA_KEY_ARG: arg, METADATA_KEY_TO_ARG: _to_arg},
    )
