"""``python -m veilmark``: desktop app without arguments, command line with arguments."""
import sys


def _main() -> int:
    if len(sys.argv) > 1:
        from .cli import main
    else:
        from .gui.main import main
    return main()


sys.exit(_main())
