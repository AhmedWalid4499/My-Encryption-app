"""Start VeilMark: no arguments -> desktop app, otherwise the command line (see veilmark/cli.py)."""
import sys


def _main() -> int:
    if len(sys.argv) > 1:
        from veilmark.cli import main
        return main()
    from veilmark.gui.main import main
    return main()


if __name__ == "__main__":
    sys.exit(_main())
