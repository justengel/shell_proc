from .__meta__ import version as __version__

from .shell import is_windows, is_linux, write_buffer, quote, shell_args, python_args, \
    ShellExit, Command, Shell, ParallelShell
