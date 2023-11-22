import atexit
import io
import os
import re
import shlex
import threading
import time
from functools import partial
from subprocess import PIPE, Popen

from .non_blocking_pipe import is_linux, is_windows, set_non_blocking


__all__ = ['is_windows', 'is_linux', 'write_buffer', 'shell_args', 'python_args',
           'ShellExit', 'Command', 'Shell',
           'ShellInterface', 'BashShell', 'LinuxShell', "WindowsPowerShell", "WindowsCmdShell"]


def write_buffer(fp, bts):
    """Write bytes to the given file object/buffer."""
    try:
        fp.buffer.write(bts)  # Allows always writing bytes for sys.stdout
    except (AttributeError, Exception):
        try:
            fp.write(bts)
        except:
            try:
                fp.write(bts.decode('utf-8', 'replace'))
            except:
                pass
    try:
        fp.flush()
    except (AttributeError, Exception):
        pass


ANSI_ESCAPE = re.compile(r"(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]")


def escape_ansi(line):
    return ANSI_ESCAPE.sub('', line)


def windows_get_pids(ppid=None, cmdline=None):
    """Retrun a list of pids"""
    # Get PID
    where_li = []
    fa = {}
    if ppid:
        where_li.append('ParentProcessId={}'.format(ppid))
    # if cmdline:
    #     where_li.append('CommandLine={}'.format(' '.join(cmdline)))

    where = ''
    if where_li:
        where = 'where ({}) '.format(','.join(where_li))

    cmd = 'wmic process {where} get CommandLine,ProcessId'.format(where=where)

    # Technically wmic is deprecated except for PowerShell
    p = Popen(cmd, stdout=PIPE, stderr=PIPE)

    pids = []
    for line in p.stdout:
        try:
            line = line.strip().decode('utf-8')
            if line:
                split = line.split(' ')
                pid = int(split[-1])
                cla = [a for a in split[:-1] if a]
                if not cmdline or cmdline == cla:
                    pids.append(pid)
        except (TypeError, ValueError, Exception):
            pass

    return pids


class shell_args(object):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = [str(a) for a in args]
        self.kwargs = kwargs

    @staticmethod
    def quote(text):
        if isinstance(text, (bytes, bytearray)):
            return b'"' + text.replace(b'"', b'\\"') + b'"'
        else:
            return '"' + str(text).replace('"', '\\"') + '"'

    def cmdline(self):
        return str(self).split(' ')
        # return shlex.split(str(self))

    @property
    def named_cli(self):
        return ['--{} {}'.format(k, self.quote(v)) for k, v in self.kwargs.items() if k and v]

    def __str__(self):
        return ' '.join(self.args + self.named_cli)

    def __bytes__(self):
        return self.__str__().encode('utf-8')

    def __format__(self, format_str):
        return self.__str__().__format__(format_str)

    def __len__(self):
        return len(self.named_cli)


class python_args(shell_args):

    PYTHON = 'python'  # Change this to change the default

    def __init__(self, *args, venv=None, windows=None, python_call=None, **kwargs):
        super().__init__(*args, **kwargs)
        if python_call is None:
            python_call = self.PYTHON

        self.venv = venv
        self.windows = windows
        self.python_call = python_call

    def __str__(self):
        cmd = [self.python_call]
        if self.venv:
            if is_windows or (self.windows is None and is_windows()):
                cmd = ['"{}\\Scripts\\activate.ps1"'.format(self.venv), '&&'] + cmd
            else:
                cmd = ['source "{}/bin/activate"'.format(self.venv), '&&'] + cmd

        args = self.args
        if len(args) > 0 and args[0] == '-c':
            args = ['-c'] + [self.quote('; '.join(args[1:]))]

        return ' '.join(cmd + args + self.named_cli)


class parallel_args(shell_args):
    def __str__(self):
        cli_args = ' '.join(self.named_cli)
        scripts = ' & '.join((f"{script} {cli_args}" for script in self.args))
        return '(\n' + scripts + '\n) '


class ShellExit(Exception):
    """Exception to indicate the Shell exited through some shell command."""
    pass


class Command(object):
    """Command that was run with the results."""
    DEFAULT_EXIT_CODE = -1

    def __init__(self, cmd=None, exit_code=None, stdout='', stderr='', stdin='', shell=None, **kwargs):
        super().__init__()
        if exit_code is None:
            exit_code = self.DEFAULT_EXIT_CODE

        self.cmd = cmd
        self.exit_code = exit_code
        self.raw_stdout = stdout.encode(errors='ignore')
        self.raw_stderr = stderr.encode(errors="ignore")
        self.stdin = stdin  # Not really used. Maybe used with pipe?
        self.shell = shell
        self._last_pipe_data_time = 0

    def cmdline(self):
        try:
            return self.cmd.cmdline()
        except (AttributeError, Exception):
            return shlex.split(str(self.cmd))

    @property
    def stdout(self):
        return self.raw_stdout.decode(errors="ignore")

    @stdout.setter
    def stdout(self, value):
        if not value:
            value = b''
        elif isinstance(value, str):
            value = value.encode()
        self.raw_stdout = value

    @property
    def stderr(self):
        return self.raw_stderr.decode(errors="ignore")

    @stderr.setter
    def stderr(self, value):
        if not value:
            value = b''
        elif isinstance(value, str):
            value = value.encode()
        self.raw_stderr = value

    def add_pipe_data(self, pipe_name, data):
        """Add output data to the proper file/pipe handler."""
        if not pipe_name.startswith('std'):
            pipe_name = 'std' + pipe_name

        self._last_pipe_data_time = time.time()
        setattr(self, pipe_name, getattr(self, 'raw_' + pipe_name, '') + data)

    def has_output(self):
        """Return if this command has any stdout."""
        return bool(self.stdout)

    def has_error(self):
        """Return if this command has any stderr."""
        return bool(self.stderr)

    def is_finished(self):
        """Return if this command finished."""
        return self.exit_code != self.DEFAULT_EXIT_CODE

    def as_dict(self):
        """Return the results as a dictionary."""
        return {'cmd': self.cmd, 'exit_code': self.exit_code, 'stdout': self.stdout, 'stderr': self.stderr}

    def update(self, d):
        try:
            d = d.as_dict()
        except:
            pass
        for k, v in d.items():
            setattr(self, k, v)

    def __str__(self):
        return str(self.cmd)

    def __bytes__(self):
        return str(self.cmd).encode('utf-8')

    def __format__(self, format_str):
        return self.__str__().__format__(format_str)

    def __int__(self):
        return self.exit_code

    def __getitem__(self, item):
        value = getattr(self, item)
        if value is None:
            raise KeyError('Invalid key given!')
        return value

    def __setitem__(self, item, value):
        setattr(self, item, value)

    def __getstate__(self):
        return self.as_dict()

    def __setstate__(self, state):
        self.update(state)

    def __or__(self, other_cmd):
        if not isinstance(other_cmd, (str, shell_args)):
            raise TypeError('Cannot PIPE type of {}'.format(type(other_cmd)))
        elif not self.has_output():
            raise RuntimeError('Command has no output to PIPE!')

        return self.shell.pipe(self.stdout, other_cmd)

    def redirect(self, arg, stream='stdout', mode='w', **kwargs):
        """Handle redirect >> or >. Cannot use 2> due to syntax error, but can > filename > &2.

        Args:
            arg (str/filename/pathlib.Path): Filename, None or 'nul' for where to write the stream
            stream (str)['stdout']: Name of the stream to write.
            mode (str)['w']: File mode.
        """
        file_handle = None
        write = None

        data = getattr(self, stream, None)
        if isinstance(data, (bytes, bytearray)) and not mode.endswith('b'):
            mode = mode + 'b'

        if arg is None or arg == 'nul':
            write = lambda *args, **kwargs: None
        if arg == 'PRN' or arg == 'LPT1':
            write = print
        elif isinstance(arg, str) or hasattr(arg, '__fspath__'):
            file_handle = open(arg, mode, newline='\n')
            write = file_handle.write
        else:
            raise TypeError('Invalid filename given "{}"!'.format(arg))

        try:
            write(data)
        finally:
            try:
                file_handle.close()
            except (AttributeError, TypeError, Exception):
                pass

    def __gt__(self, filename):
        self.redirect(filename, mode='w')
        return self

    def __rshift__(self, filename):
        # Write stdout to file
        self.redirect(filename, mode='a')
        return self


class ShellInterface(object):
    """Continuous Shell process to run a series of commands."""
    is_windows = staticmethod(is_windows)
    is_linux = staticmethod(is_linux)
    is_windows_cmd = staticmethod(lambda: False)
    is_powershell = staticmethod(lambda: False)
    shell_args = shell_args
    python_args = python_args
    parallel_args = parallel_args
    quote = staticmethod(shell_args.quote)
    write_buffer = staticmethod(write_buffer)

    NEWLINE = os.linesep
    NEWLINE_BYTES = NEWLINE.encode('utf-8')

    def __init__(self, *tasks, stdout=None, stderr=None, shell=False,
                 blocking=True, wait_on_exit=True, close_on_exit=True, python_call=None,
                 show_all_output: bool = False, show_commands: bool = False, **kwargs):
        """Initialize the Shell object.

        Args:
            *tasks (tuple/str/object): List of string commands to run.
            stdout (io.TextIOWrapper/object)[None]: Standard out to redirect the separate process standard out to.
            stderr (io.TextIOWrapper/object)[None]: Standard error to redirect the separate process standard out to.
            blocking (bool/float)[True]: If False write to stdin without waiting for the previous command to finish.
            wait_on_exit (bool)[True]: If True on context manager exit wait for all commands to finish.
            close_on_exit (bool)[True]: If True close the process when the context manager exits. This may be useful
                to be false for running multiple processes. Method "wait" can always be called to wait for all commands.
            python_call (str)[None]: Python executable to use. Can be a full path or "python3". Default is "python".
            show_all_output (bool)[False]: If True do not hide echo result statements when writing to stdout
            show_commands (bool)[False]: If True print the commands that are running.
        """
        # Public Variables
        self.stdout = None
        self.stderr = None
        self.shell = shell
        self.proc = None
        self._blocking = blocking
        self.wait_on_exit = wait_on_exit
        self.close_on_exit = close_on_exit
        self.python_call = python_call
        self.show_all_output = show_all_output
        self.show_commands = show_commands

        self._parallel_shell = []  # Keep parallel shells to close when we close
        self.history = []
        self.finished_count = 0
        self._end_command = '####### SHELL END COMMAND #######'
        self._end_command_bytes = self._end_command.encode('utf-8')

        # Private Variables
        self._th_out = None
        self._th_err = None
        self._buffers = {"out": bytearray(), "err": bytearray()}

        # Check the given stdout and stderr values
        if stdout is not None:
            self.stdout = stdout
        if stderr is not None:
            self.stderr = stderr

        # Run the given tasks
        for task in tasks:
            self.run(task)

    @property
    def stdin(self):
        try:
            return self.proc.stdin
        except (AttributeError, Exception):
            return None

    def get_file(self, pipe_name):
        """Return the file for the given pipe_name (self.stdout or self.stderr)."""
        var_name = 'std{}'.format(pipe_name)
        return getattr(self, var_name, None)

    def is_blocking(self):
        """Return if the commands are blocking."""
        return self._blocking

    def set_blocking(self, blocking):
        """Set if the commands are blocking.

        If True each shell command will wait until the command is complete.

        Args:
            blocking (bool): If the shell should block and wait for each command.
        """
        self._blocking = blocking

    def finish_command(self, exit_code: int = -1, cmd: Command = None):
        """Finish a command that was run.

        This always increments the finished count to change the current command.

        Args:
            exit_code (int)[-1]: Exit code to set the command to
            cmd (Command)[None]: Command to finish or use the current command if None
        """
        if cmd is None:
            cmd = self.current_command
        try:
            cmd.exit_code = exit_code
        except AttributeError:
            pass
        self.finished_count += 1
        if self.finished_count > len(self.history):
            self.finished_count = len(self.history)  # 1 past the history meaning all commands completed

    @property
    def current_command(self):
        """Return the current command that is still running or was last_completed."""
        try:
            idx = -1
            if not self.is_finished():
                idx = self.finished_count
            return self.history[idx]
        except (IndexError, KeyError, TypeError, AttributeError):
            return None

    @property
    def last_command(self):
        """Return the last task that was sent to run."""
        try:
            return self.history[-1]
        except (IndexError, KeyError, TypeError, AttributeError):
            return None

    @property
    def exit_code(self):
        """Return the exit code for the last command."""
        try:
            return self.last_command.exit_code
        except (IndexError, KeyError, TypeError, AttributeError):
            return -1

    def get_end_command(self):
        """Return the end command as a string"""
        return self._end_command

    def get_end_command_bytes(self):
        """Return the end command as bytes"""
        return self._end_command_bytes

    def set_end_command(self, value):
        """Set the end command string."""
        if isinstance(value, (bytes, bytearray)):
            self._end_command_bytes = value
            self._end_command = self._end_command_bytes.decode('utf-8', 'replace')
        else:
            self._end_command = str(value)
            self._end_command_bytes = self._end_command.encode('utf-8')

    end_command = property(get_end_command, set_end_command)
    end_command_bytes = property(get_end_command_bytes, set_end_command)

    def get_echo_results_cmd(self):
        cmd = 'echo "{end_cmd} {report}"'.format(end_cmd=self.end_command, report='$?')
        return cmd.encode()

    def echo_results(self):
        """Send the echo command to find the results of the previous command."""
        echo = self.get_echo_results_cmd()
        self.proc.stdin.write(echo + self.NEWLINE_BYTES)
        self.proc.stdin.flush()

    def _run(self, cmd, pipe_text='', extra=b'', end=b'', echo_results=True, **kwargs):
        """Run the given text command."""
        if extra:
            extra = b' ' + extra

        if end:
            end = b' ' + end
        end += self.NEWLINE_BYTES

        # Check for pipe
        if pipe_text:
            if not isinstance(pipe_text, (bytes, bytearray)):
                pipe_text = str(pipe_text).encode('utf-8')
            pipe_text = self.quote(pipe_text)
            self.proc.stdin.write(b'echo ' + pipe_text + b' | ')

        # Run the command
        echo = b''
        if echo_results:
            echo = b' ; ' + self.get_echo_results_cmd()
        self.proc.stdin.write(bytes(cmd) + extra + echo + end)
        self.proc.stdin.flush()

        return cmd

    def run(self, *args, pipe_text='', block=None, extra=None, end=None, echo_results=True, **kwargs):
        """Run the given task.

        Args:
            *args (tuple/object): Arguments to combine into a runnable string.
            pipe_text (str)['']: Text to pipe into the task
            block (float/bool)[None]: If None use Shell setting else sleep the number of seconds given.
            extra (str/bytes)[None]: Extra arguments or commands before the echo result.
            end (str/bytes)[None]: Set end of the command before the newline. Useful for '&' background
            echo_results (bool)[True]: If True send the echo results command.
            **kwargs (dict/object): Keyword arguments to combine into a runnable string with "--key value".

        Returns:
            cmd (Command): Command object where output will be stored
        """
        # Check if running
        if not self.is_running():
            self.start()
        elif not self.is_proc_running():
            raise ShellExit('The internal shell process was closed and is no longer running!')

        # Format the arguments
        if len(args) == 1 and isinstance(args, shell_args):
            arg = args[0]
        else:
            arg = self.shell_args(*args, **kwargs)

        # Create command structure to save output
        cmd = Command(arg, stdin=pipe_text, shell=self, **kwargs)
        self.history.append(cmd)

        # Run the command
        if isinstance(extra, str):
            extra = extra.encode()
        if isinstance(end, str):
            end = end.encode()
        cmd = self._run(
            cmd,
            pipe_text=pipe_text,
            extra=bytes(extra or 0),
            end=bytes(end or 0),
            echo_results=echo_results
        )

        # Check for completion
        if block is None:
            block = self.is_blocking()
        if block is True:
            self.wait()
        else:
            time.sleep(block or 0)

        return cmd

    def input(self, value, wait: bool = False, block: bool = False, extra=None, end=None):
        """Input text into the process' stdin. Do not expect this to be a command and do not wait to finish.

        Args:
            value (str/bytes): Value to pass into stdin.
            wait (bool)[False]: If True wait for all previous commands to finish.
            block (float/bool)[False]: If None use Shell setting else sleep the number of seconds given.
            extra (str/bytes)[None]: Extra arguments or commands
            end (str/bytes)[None]: Set end of the command before the newline. Useful for '&' background
        """
        if isinstance(extra, str):
            extra = extra.encode()
        if extra:
            extra = b' ' + extra
        extra = bytes(extra or 0)

        if isinstance(end, str):
            end = end.encode()
        if end:
            end = b' ' + end
        end = bytes(end or 0) + self.NEWLINE_BYTES

        # Convert to bytes
        if isinstance(value, str):
            value = value.encode()

        # Remove end newlines, so we can add end
        value = value.rstrip(b'\r\n')

        # Write to stdin
        self.proc.stdin.write(value + extra + end)
        self.proc.stdin.flush()

        # Check for completion
        if block is None:
            block = self.is_blocking()
        if wait or block is True:
            self.wait()
        else:
            time.sleep(block or 0)

    def pipe(self, pipe_text, *args, block=None, extra=None, end=None, **kwargs):
        """Run the given task and pipe the given text to it.

        Args:
            pipe_text (str): Text to pipe into the task
            *args (tuple/object): Arguments to combine into a runnable string.
            block (float/bool)[None]: If None use Shell setting else sleep the number of seconds given.
            extra (str/bytes)[None]: Extra arguments or commands before the echo result.
            end (str/bytes)[None]: Set end of the command before the newline. Useful for '&' background
            **kwargs (dict/object): Keyword arguments to combine into a runnable string with "--key value".

        Returns:
            cmd (Command): Command object where output will be stored
        """
        return self.run(*args, pipe_text=pipe_text, block=block, extra=extra, end=end, **kwargs)

    def python(self, *args, pipe_text='', block=None, venv=None, windows=None, python_call=None,
               extra=None, end=None, **kwargs):
        """Run the given lines as a python script.

        Args:
            *args (tuple/object): Series of python lines of code to run.
            pipe_text (str)['']: Text to pipe into the task
            block (float/bool)[None]: If None use Shell setting else sleep the number of seconds given.
            venv (str)[None]: Venv path to activate before calling python.
            windows (bool)[None]: Manually give if the venv is in windows.
            python_call (str)[None]: Python command. By default this is "python"
            extra (str/bytes)[None]: Extra arguments or commands before the echo result.
            end (str/bytes)[None]: Set end of the command before the newline. Useful for '&' background
            **kwargs (dict/object): Additional keyword arguments.

        Returns:
            cmd (Command): Command object where output will be stored
        """
        # Format the arguments
        python_call = python_call or self.python_call
        arg = self.python_args(*args, venv=venv, windows=windows, python_call=python_call, **kwargs)

        # Run the command
        return self.run(arg, pipe_text=pipe_text, block=block, extra=extra, end=end)

    def _run_parallel(self, cmd, pipe_text='', extra=b'', end=b'', echo_results=True, **kwargs):
        """Run the given text command."""
        if extra:
            extra = b' ' + extra
        if end:
            end = b' ' + end
        end += self.NEWLINE_BYTES

        # Check for pipe
        if pipe_text:
            if not isinstance(pipe_text, (bytes, bytearray)):
                pipe_text = str(pipe_text).encode('utf-8')
            pipe_text = self.quote(pipe_text)
            self.proc.stdin.write(b'echo ' + pipe_text + b' | ')

        # Run the command
        echo = b''
        if echo_results:
            echo = b' ; ' + self.get_echo_results_cmd()
        self.proc.stdin.write(bytes(cmd) + extra + echo + end)
        self.proc.stdin.flush()

        return cmd

    def parallel(self, *scripts, pipe_text='', block=None, extra=None, end=None, echo_results=True, **kwargs):
        """Run the given scripts in parallel.

        Args:
            *scripts (tuple/object): Series of python lines of code to run.
            pipe_text (str)['']: Text to pipe into the task
            block (float/bool)[None]: If None use Shell setting else sleep the number of seconds given.
            extra (str/bytes)[None]: Extra arguments or commands before the echo result.
            end (str/bytes)[None]: Set end of the command before the newline. Useful for '&' background
            echo_results (bool)[True]: If True send the echo results command.
            **kwargs (dict/object): Additional keyword arguments.

        Returns:
            cmd (Command): Command object where output will be stored
        """
        # Check if running
        if not self.is_running():
            self.start()
        elif not self.is_proc_running():
            raise ShellExit('The internal shell process was closed and is no longer running!')

        # Format the arguments
        arg = self.parallel_args(*scripts, **kwargs)

        # Create command structure to save output
        cmd = Command(arg, stdin=pipe_text, shell=self, **kwargs)
        self.history.append(cmd)

        # Run the command
        if isinstance(extra, str):
            extra = extra.encode()
        if isinstance(end, str):
            end = end.encode()
        cmd = self._run_parallel(
            cmd,
            pipe_text=pipe_text,
            extra=bytes(extra or 0),
            end=bytes(end or 0),
            echo_results=echo_results,
        )

        # Check for completion
        if block is None:
            block = self.is_blocking()
        if block is True:
            self.wait()
        else:
            time.sleep(block or 0)

        return cmd

    @staticmethod
    def read_pipe(pipe, callback):
        """Continuously read the given pipe.

        Args:
            pipe (io.TextIOOWrapper): File object/buffer from the subprocess to read from and redirect with.
            callback (function/callable): Function that handles the data read from the pipe.
        """
        # Change pipe to non-blocking. Popen requires bufsize=0
        set_non_blocking(pipe)
        buffer = io.BufferedReader(pipe)

        no_read_count = 0
        while True:
            try:
                # Read all data from the buffer 1 time non-blocking
                try:
                    data = buffer.read1()
                except (BlockingIOError, OSError):  # Windows non-blocking can cause OSError
                    data = b''
                if not data:
                    no_read_count += 1  # Process buffer data without NEWLINE after a few attempts

                has_data = len(data) > 0
                if has_data or no_read_count > 1:
                    no_read_count = 0
                    callback(data)
                else:
                    time.sleep(0.1)
            except BrokenPipeError:
                break

    def parse_output(self, line):
        """Parse the end command echo results."""
        # Return variables
        is_cmd = False
        parsed = line
        exit_code = None

        # Check the finished flag
        end_cmd = self.end_command_bytes
        if end_cmd in line:
            try:
                idx = line.index(end_cmd)
                end_idx = line[idx+1:].index(self.NEWLINE_BYTES)

                # Strip echo portion of output
                parsed = line[:idx]
                if parsed.endswith(b' ; echo "') or parsed.endswith(b' & echo "'):
                    parsed = parsed[:-9] + line[idx+1+end_idx:]

                # If no exit code it is an echo of cmd
                output = line[idx + len(end_cmd): idx + 1 + end_idx]
                status = output.strip().decode()
                try:
                    exit_code = int(status)
                except (TypeError, AttributeError, Exception):
                    # Windows Powershell 🤦
                    if status == "True":
                        exit_code = 0
                    elif status == "False":
                        exit_code = 1
            except (IndexError, TypeError, AttributeError, Exception):
                pass

        # Skip parsing the current command
        try:
            cmd = bytes(self.current_command)
            if parsed.strip().endswith(cmd):
                is_cmd = True
        except (AttributeError, TypeError, Exception):
            pass

        return is_cmd, parsed, exit_code, line

    def check_pipe(self, msg, pipe_name):
        """Check the output of a message."""
        buffer = self._buffers[pipe_name]
        if msg:
            buffer.extend(msg)
            lines = buffer.split(self.NEWLINE_BYTES)
            self._buffers[pipe_name] = lines[-1]
            lines = [l + self.NEWLINE_BYTES for l in lines[:-1]]
        elif buffer:
            # Timeout occurred process all output
            lines, self._buffers[pipe_name] = [buffer], buffer[0:0]
        else:
            # No data to process
            return

        # Iterate through lines
        stdfile = getattr(self, "std"+pipe_name)
        for line in lines:
            # Parse output for echo results
            is_cmd, parsed, exit_code, line = self.parse_output(line)

            # Write output to stdout, stderr
            if self.show_all_output:
                self.write_buffer(stdfile, line)
            elif parsed and (not is_cmd or self.show_commands):
                self.write_buffer(stdfile, parsed)

            # Add output to command history
            if parsed and not is_cmd:
                try:
                    # Only add output to the running command
                    self.history[self.finished_count].add_pipe_data(pipe_name, parsed)
                except (AttributeError, IndexError, TypeError, ValueError, Exception):
                    pass

            # Set the command exit code
            if exit_code is not None:
                self.finish_command(exit_code)

    def is_running(self, *additional, check_parallel=True, **kwargs):
        """Return if the continuous shell process is running."""
        if self.proc is not None:
            return True

        p_shells = list(additional)
        if check_parallel:
            p_shells.extend(self._parallel_shell)
        return any((p.is_running() for p in p_shells if hasattr(p, 'is_running')))

    def is_proc_running(self, *additional, check_parallel=True, **kwargs):
        """Return if the process is running."""
        if self.proc is not None and self.proc.poll() is None:
            return True

        p_shells = list(additional)
        if check_parallel:
            p_shells.extend(self._parallel_shell)
        return any((p.is_proc_running() for p in p_shells if hasattr(p, 'is_proc_running')))

    def is_finished(self, *additional, check_parallel=True, **kwargs):
        """Return if all of the shell commands have finished"""
        # check if finished count is less than commands
        if len(self.history) > self.finished_count:
            return False

        p_shells = list(additional)
        if check_parallel:
            p_shells.extend(self._parallel_shell)
        return all((p.is_finished() for p in p_shells if hasattr(p, 'is_finished')))

    def wait(self, *additional, check_parallel=True, **kwargs):
        """Wait until all of the commands are finished or until the process exits."""
        while self.is_proc_running(*additional, check_parallel=check_parallel, **kwargs) and \
                not self.is_finished(*additional, check_parallel=check_parallel, **kwargs):
            time.sleep(0.1)
        return self

    def _start(self):
        """Open the process"""
        self.proc = Popen('/bin/bash', bufsize=0, stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=self.shell)

    def start(self):
        """Start the continuous shell process."""
        if self.is_running():
            self.close()

        # Create the continuous terminal process
        self._start()

        # Command count
        self.history = []
        self.finished_count = 0

        # Start stderr and stdout threads
        check_output = partial(self.check_pipe, pipe_name="out")
        self._th_out = threading.Thread(target=self.read_pipe, args=(self.proc.stdout, check_output))
        self._th_out.daemon = True
        self._th_out.start()

        check_error = partial(self.check_pipe, pipe_name="err")
        self._th_err = threading.Thread(target=self.read_pipe, args=(self.proc.stderr, check_error))
        self._th_err.daemon = True
        self._th_err.start()
        atexit.register(self.stop)

        # Wait for process and read thread to start
        time.sleep(0.1)

        return self

    def stop(self):
        """Stop the continuous shell process. This method does not wait and closes everything immediately."""
        try:
            atexit.unregister(self.stop)
        except:
            pass

        try:
            self._th_out.join(0)
        except:
            pass
        finally:
            self._th_out = None
        try:
            self._th_err.join(0)
        except:
            pass
        finally:
            self._th_err = None
        try:
            self.proc.stdin.close()
        except:
            pass
        try:
            self.proc.terminate()
        except:
            pass
        finally:
            self.proc = None

        return self

    def close(self):
        """Close the continuous shell process. This method does not wait and closes everything immediately."""
        try:
            self.stop()
        except:
            pass

        for i in reversed(range(len(self._parallel_shell))):
            try:
                sh = self._parallel_shell.pop(i)
                sh.close()
            except (AttributeError, Exception):
                pass

    def __del__(self):
        """Close the continuous shell process. This method does not wait and closes everything immediately."""
        try:
            self.close()
        except:
            pass

    def __call__(self, *args, pipe_text='', block=None, **kwargs):
        """Run the given task.

        Args:
            *args (tuple/object): Arguments to combine into a runnable string.
            pipe_text (str)['']: Text to pipe into the task
            block (float/bool)[None]: If None use Shell setting else sleep the number of seconds given.
            **kwargs (dict/object): Keyword arguments to combine into a runnable string with "--key value".

        Returns:
            success (bool)[True]: If True the call did not print any output to stderr.
                If False there was some output printed to stderr.
        """
        try:
            return self.run(*args, pipe_text=pipe_text, block=block, **kwargs)
        except ShellExit as err:
            # "from None" changes traceback to here without chaining
            raise ShellExit(str(err)) from None

    def __enter__(self, stdout=None, stderr=None):
        """Enter to use for the 'with' context manager."""
        if stdout is not None:
            self.stdout = stdout
        if stderr is not None:
            self.stderr = stderr

        if not self.is_running():
            self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the 'with' context manager."""
        no_error = exc_type is None

        # Check to wait on context manager exit even if non blocking
        if no_error and self.wait_on_exit:
            self.wait()  # Also waits for parallel

        if self.close_on_exit:
            self.close()  # Also closes parallel

        return no_error


class BashShell(ShellInterface):

    def _linux_start(self):
        """Open the process"""
        self.proc = Popen(
            '/bin/bash',
            bufsize=0,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            shell=self.shell
        )

    _start = _linux_start

    def _linux_get_echo_results_cmd(self):
        cmd = 'echo "{end_cmd} {report}"'.format(end_cmd=self.end_command, report='$?')
        return cmd.encode()

    get_echo_results_cmd = _linux_get_echo_results_cmd

    def _linux_run(self, cmd, pipe_text='', extra=b'', end=b'', echo_results=True, **kwargs):
        """Run the given text command."""
        if extra:
            extra = b' ' + extra
        if end:
            end = b' ' + end
        end += self.NEWLINE_BYTES

        if self.show_all_output or self.show_commands:
            self.write_buffer(self.stdout, b'$> ')

        # Run the echo for the pipe
        if pipe_text:
            if not isinstance(pipe_text, (bytes, bytearray)):
                pipe_text = str(pipe_text).encode('utf-8')
            pipe_text = self.quote(pipe_text)  # Key is quote
            echo_pipe = b'echo ' + pipe_text + b' | '

            if self.show_all_output or self.show_commands:
                self.write_buffer(self.stdout, echo_pipe)
            self.proc.stdin.write(echo_pipe)
            # self.proc.stdin.flush()

        # Print commands if configured.
        # Bash does not send commands to stdout by default. Windows does.
        echo = b''
        if echo_results:
            echo = b' ; ' + self.get_echo_results_cmd()
        if self.show_all_output:
            self.write_buffer(self.stdout, bytes(cmd) + extra + echo + end)
        elif self.show_commands:
            self.write_buffer(self.stdout, bytes(cmd) + extra + end)

        # Run the command
        self.proc.stdin.write(bytes(cmd) + extra + echo + end)
        self.proc.stdin.flush()

        return cmd

    _run = _linux_run
    _run_parallel = _linux_run


LinuxShell = BashShell


class powershell_args(shell_args):
    @staticmethod
    def quote(text):
        # Windows Powershell 🤦 ... Yes 3 \ with 2 "
        if isinstance(text, (bytes, bytearray)):
            return b'"' + text.replace(b'"', b'\\\""') + b'"'
        else:
            return '"' + text.replace('"', '\\\""') + '"'


class powershell_python_args(python_args):
    quote = staticmethod(powershell_args.quote)


class parallel_powershell_args(parallel_args):
    @staticmethod
    def quote(text):
        # Windows Powershell 🤦 ... Yes 3 \ with 2 "
        if isinstance(text, (bytes, bytearray)):
            text = text.replace(b'\\\""', b'"')  # Revert normal powershell escape
            return b'"' + text.replace(b'"', b'`"') + b'"'
        else:
            text = text.replace('\\\""', '"')  # Revert normal powershell escape
            return '"' + str(text).replace('"', '`"') + '"'

    def __str__(self):
        cli_args = ' '.join(self.named_cli)
        scripts = []
        for script in self.args:
            cmd, args = script.split(" ", 1)
            args = self.quote(args + ' ' + cli_args)
            scripts.append(f"Start-Process -NoNewWindow -FilePath {cmd} -ArgumentList {args}")
        return '\r\n'.join(scripts)


class WindowsPowerShell(ShellInterface):
    is_powershell = staticmethod(lambda: True)
    quote = staticmethod(powershell_args.quote)
    shell_args = powershell_args
    python_args = powershell_python_args
    parallel_args = parallel_powershell_args

    def _powershell_start(self):
        """Open the process"""
        self.proc = Popen(
            'powershell.exe -NoLogo -NoExit',
            bufsize=0,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            shell=self.shell
        )

    _start = _powershell_start

    def _powershell_get_echo_results_cmd(self):
        cmd = 'echo "{end_cmd} {report}"'.format(end_cmd=self.end_command, report='$?')
        return cmd.encode()

    get_echo_results_cmd = _powershell_get_echo_results_cmd

    def _powershell_run(self, cmd, pipe_text='', extra=b'', end=b'', echo_results=True, **kwargs):
        """Run the given text command."""
        if extra:
            extra = b' ' + extra
        if end:
            end = b' ' + end
        end += self.NEWLINE_BYTES

        # Check for pipe
        if pipe_text:
            if not isinstance(pipe_text, (bytes, bytearray)):
                pipe_text = str(pipe_text).encode()
            pipe_text = pipe_text.rstrip(self.NEWLINE_BYTES) + self.NEWLINE_BYTES
            self.proc.stdin.write(b"$SHELL_PIPE_VAR=@'" + self.NEWLINE_BYTES +
                                  pipe_text +
                                  b"'@" + self.NEWLINE_BYTES + self.NEWLINE_BYTES)
            self.proc.stdin.write(b"echo $SHELL_PIPE_VAR | ")

        # Run the command
        echo = b''
        if echo_results:
            echo = b' ; ' + self.get_echo_results_cmd()
        self.proc.stdin.write(bytes(cmd) + extra + echo + end)
        self.proc.stdin.flush()

        return cmd

    _run = _powershell_run
    _run_parallel = _powershell_run

    def _powershell_parse_output(self, line):
        """Parse the end command echo results.

        Windows cmd does not respect ; so we use &
        """
        is_cmd, parsed, exit_code, line = super().parse_output(line)

        # # Check if ending in newline or waiting for command.
        # if parsed.endswith(b"> "):
        #     is_cmd = True

        return is_cmd, parsed, exit_code, line

    parse_output = _powershell_parse_output


class windows_cmd_parallel_args(parallel_args):
    def __str__(self):
        cli_args = ' '.join(self.named_cli)
        scripts = [f'start "shell_proc" /b {script} {cli_args}' for script in self.args]
        scripts = '\r\n'.join(scripts) + " ".join(self.named_cli)

        # Best effort to wait for all commands to finish
        return '(\r\n' + scripts + '\r\n)'


class WindowsCmdShell(ShellInterface):
    is_windows_cmd = staticmethod(lambda: True)
    parallel_args = windows_cmd_parallel_args

    def _windows_cmd_start(self):
        """Open the process"""
        # /K run command and remain (disables the banner)
        # /Q echo off
        # /V:ON Enable delayed expansion allowing %errorlevel%
        env = os.environ.copy()
        env["PROMPT"] = "> "
        self.proc = Popen(
            'cmd.exe /q /K',
            bufsize=0,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            shell=self.shell,
            env=env,
        )

    _start = _windows_cmd_start

    def start(self):
        """Start the continuous shell process."""
        res = super().start()
        time.sleep(0.1)
        return res

    def _windows_cmd_get_echo_results_cmd(self):
        cmd = 'echo {end_cmd} {report}'.format(end_cmd=self.end_command, report='%errorlevel%')
        return cmd.encode()

    get_echo_results_cmd = _windows_cmd_get_echo_results_cmd

    def _windows_cmd_run(self, cmd, pipe_text='', extra=b'', end=b'', echo_results=True, **kwargs):
        """Run the given text command."""
        if extra:
            extra = b' ' + extra
        if end:
            end = b' ' + end
        end += self.NEWLINE_BYTES

        if self.show_all_output or self.show_commands:
            self.write_buffer(self.stdout, b'$> ')

        # Check for pipe
        if pipe_text:
            if not isinstance(pipe_text, (bytes, bytearray)):
                pipe_text = str(pipe_text).encode()
            pipe_text = pipe_text.rstrip(self.NEWLINE_BYTES)
            echo_pipe = b"(" + self.NEWLINE_BYTES
            for line in pipe_text.split(self.NEWLINE_BYTES):
                echo_pipe += b'echo ' + self.quote(line) + self.NEWLINE_BYTES
            echo_pipe += b") | "

            if self.show_all_output or self.show_commands:
                self.write_buffer(self.stdout, echo_pipe)
            self.proc.stdin.write(echo_pipe)

        # Print commands if configured.
        # Bash does not send commands to stdout by default. Windows does.
        echo = b''
        if echo_results:
            echo = b' & ' + self.get_echo_results_cmd()
        if self.show_all_output:
            self.write_buffer(self.stdout, bytes(cmd) + extra + echo + end)
        elif self.show_commands:
            self.write_buffer(self.stdout, bytes(cmd) + extra + end)

        # Run the command
        self.proc.stdin.write(bytes(cmd) + extra + echo + end)
        self.proc.stdin.flush()

        return cmd

    _run = _windows_cmd_run
    _run_parallel = _windows_cmd_run

    def _windows_cmd_parse_output(self, line):
        """Parse the end command echo results.

        Windows cmd does not respect ; so we use &
        """
        # Changed prompt so we can remove it to mimic bash
        while True:
            trimmed = False
            if line.startswith(b"> "):
                line = line[2:]
                trimmed = True
            if line.startswith(b"More? "):
                trimmed = True
                line = line[6:]
            if not trimmed:
                break
        return super().parse_output(line)

    parse_output = _windows_cmd_parse_output


# Set the default shell type
if is_windows():
    if os.environ.get("WINDOWS_SHELLPROC", "").lower() == "powershell":
        Shell = WindowsPowerShell
    else:
        Shell = WindowsCmdShell
else:
    Shell = BashShell
