"""The command-line surface conclude derives for each setting: one flag
per setting, plus a negation (``--no-flag``) for every ``bool``, and the
check that no two settings claim the same flag.
"""

import argparse
from collections.abc import Iterable, Mapping
from typing import Any

from conclude.infer import Opt
from conclude.naming import cli_flag_name, cli_negated_flag_name


class NegatableFlag(argparse.Action):
    """A ``bool`` setting's flag and its negation as one argparse
    action: ``--flag`` stores ``True``, ``--no-flag`` stores ``False``,
    and the last one given wins. With ``default=None`` (what
    :meth:`conclude.App.add_arguments` passes), giving neither leaves
    the setting unset -- "no opinion" -- so a lower layer decides.

    Not :class:`argparse.BooleanOptionalAction`: that one derives the
    negation as ``--no-`` plus the flag, so it cannot make ``--color``
    the opposite of ``--no-color``.
    """

    def __init__(
        self, option_strings: list[str], dest: str, *, negated: str, **kwargs: Any
    ) -> None:
        super().__init__([*option_strings, negated], dest, nargs=0, **kwargs)
        self._negated = negated

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, option_string != self._negated)


def cli_flags(defaults: Mapping[str, Any], skip: Iterable[str] = ()) -> list[tuple[str, str, bool]]:
    """``(key, flag, is_negation)`` for every CLI flag the settings in
    ``defaults`` get, in declaration order -- a setting's own flag, then,
    for a ``bool``, its negation. Raises ``ValueError`` if two settings
    claim the same flag (a ``bool`` ``cache`` and a setting ``no_cache``,
    say: both want ``--no-cache``).
    """
    skip = set(skip)
    owners: dict[str, str] = {}
    flags: list[tuple[str, str, bool]] = []
    for key, default in defaults.items():
        if key in skip:
            continue
        type_ = default.type if isinstance(default, Opt) else type(default)
        mine = [(cli_flag_name(key), False)]
        if type_ is bool:
            mine.append((cli_negated_flag_name(key), True))
        for flag, negated in mine:
            if flag in owners:
                raise ValueError(
                    f"settings {owners[flag]!r} and {key!r} both claim the CLI flag {flag}"
                )
            owners[flag] = key
            flags.append((key, flag, negated))
    return flags
