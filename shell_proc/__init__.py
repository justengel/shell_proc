from .__meta__ import version as __version__

from .non_blocking_pipe import is_windows, is_linux, set_non_blocking
from .shell import write_buffer, quote, shell_args, python_args, ShellExit, Command, Shell, ParallelShell
