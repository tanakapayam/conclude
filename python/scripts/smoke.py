"""conclude's own check of a built, installed package: the negation round trip.

Run by python/verify-install and python/verify-published (tanakapayam/actions) inside each
fresh install, with <distribution name> <import name> <version> as arguments. The generic
checks (version, import location, py.typed) are theirs; what a conclude install must *do* is this.
"""

import shlex
import sys

import conclude
from conclude import App, opt

assert conclude.__version__ == sys.argv[3], (conclude.__version__, sys.argv[3])

app = App(
    "smoke",
    {"cache": True, "debug": False, "verbose": opt(bool)},
    config_home_path=None,
    config_cwd_path=None,
)
parser = app.build_arg_parser(prog="smoke")


def parse(argv):
    namespace = parser.parse_args(argv)
    return {key: value for key, value in vars(namespace).items() if value is not None}


resolved = app.resolve(parse(["--no-cache", "--debug"]))
assert resolved["cache"] is False and resolved["debug"] is True, resolved
line = app.format_invocation(resolved, prog="smoke")
assert line == "smoke --no-cache --debug", line
assert app.resolve(parse(shlex.split(line)[1:])) == resolved, "an invocation does not read back"
print("conclude smoke: the negation round trip works")
