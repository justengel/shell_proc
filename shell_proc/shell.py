import io
import os
import sys
import platform
import time
import threading
import atexit
import shlex
import signal
from functools import partial
from subprocess import Popen, PIPE
from .non_blocking_pipe import is_windows, is_linux, set_non_blocking


__all__ = ['is_windows', 'is_linux', 'write_buffer', 'quote', 'shell_args', 'python_args',
           'ShellExit', 'Command', 'Shell', 'ParallelShell']


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


def quote(text):
    # return '"{}"'.format(text.replace('"', '\\"').replace("'", "\\'"))
    return '"{}"'.format(str(text).replace('"', '\\"'))


def escape_echo_windows(text):
    # Replace special characters
    text = str(text).replace('^', '^^').replace('<', '^<').replace('>', '^>').replace('|', '^|').replace('&', '^&')
    return text


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

    def cmdline(self):
        return str(self).split(' ')
        # return shlex.split(str(self))

    @property
    def named_cli(self):
        return ['--{} {}'.format(k, quote(v)) for k, v in self.kwargs.items()]

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
                cmd = ['"{}\\Scripts\\activate.bat"'.format(self.venv), '&&'] + cmd
            else:
                cmd = ['source "{}/bin/activate"'.format(self.venv), '&&'] + cmd

        args = self.args
        if len(args) > 0 and args[0] == '-c':
            args = ['-c'] + [quote(';'.join(args[1:]))]

        return ' '.join(cmd + args + self.named_cli)


class ShellExit(Exception):
    """Exception to indicate the Shell exited through some shell command."""
    pass


class Command(object):
    """Command that was run with the results."""
    DEFAULT_EXIT_CODE = -1

    def __init__(self, cmd='', exit_code=None, stdout='', stderr='', stdin='', shell=None, **kwargs):
        super().__init__()
        if exit_code is None:
            exit_code = self.DEFAULT_EXIT_CODE

        self.cmd = cmd
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.stdin = stdin  # Not really used. Maybe used with pipe?
        self.shell = shell
        self._last_pipe_data_time = 0

    def cmdline(self):
        try:
            return self.cmd.cmdline()
        except (AttributeError, Exception):
            return shlex.split(str(self.cmd))

    def add_pipe_data(self, pipe_name, data):
        """Add output data to the proper file/pipe handler."""
        if not pipe_name.startswith('std'):
            pipe_name = 'std' + pipe_name
        if isinstance(data, (bytes, bytearray)):
            data = data.decode('utf-8', 'replace')

        self._last_pipe_data_time = time.time()
        setattr(self, pipe_name, getattr(self, pipe_name, '') + data)

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


class Shell(object):
    """Continuous Shell process to run a series of commands."""
    is_windows = staticmethod(is_windows)
    is_linux = staticmethod(is_linux)
    shell_args = shell_args
    python_args = python_args
    write_buffer = staticmethod(write_buffer)

    NEWLINE = os.linesep
    NEWLINE_BYTES = NEWLINE.encode('utf-8')

    def __init__(self, *tasks, stdout=None, stderr=None, shell=False,
                 blocking=True, wait_on_exit=True, close_on_exit=True, python_call=None,
                 use_old_cmd: bool = False, **kwargs):
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
            use_cmd (bool)[False]: If True on windows use cmd otherwise use powershell. Old cmd may not work with $?.
        """
        if self.is_windows():
            self._run = self._run_windows
        else:
            self._run = self._run_linux

        # Public Variables
        self.stdout = None
        self.stderr = None
        self.shell = shell
        self.proc = None
        self._blocking = blocking
        self.wait_on_exit = wait_on_exit
        self.close_on_exit = close_on_exit
        self.python_call = python_call
        self.use_old_cmd = use_old_cmd

        self._parallel_shell = []  # Keep parallel shells to close when we close
        self.history = []
        self.finished_count = 0
        self._end_command = '=========== SHELL END COMMAND =========='
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

    def get_echo_results(self):
        if self.is_windows() and self.use_old_cmd:
            cmd = 'echo "{end_cmd} {report}"'.format(end_cmd=self.end_command, report='%errorlevel%')
        else:
            cmd = 'echo "{end_cmd} {report}"'.format(end_cmd=self.end_command, report='$?')
        return cmd.encode()

    def _run_linux(self, shell_cmd, pipe_text='', **kwargs):
        """Run the given text command."""
        # Write input to run command
        cmd = Command(shell_cmd, stdin=pipe_text, shell=self, **kwargs)
        self.history.append(cmd)

        # Check for pipe
        if pipe_text:
            if not isinstance(pipe_text, (bytes, bytearray)):
                pipe_text = quote(str(pipe_text)).encode('utf-8')  # Key is quote
            self.proc.stdin.write(b'echo ' + pipe_text + b' | ')

        # Run the command
        echo = self.get_echo_results()
        self.proc.stdin.write(bytes(cmd) + b" ; " + echo + self.NEWLINE_BYTES)
        self.proc.stdin.flush()

        return cmd

    def _run_windows(self, shell_cmd, pipe_text='', **kwargs):
        """Run the given text command."""
        # Write input to run command
        cmd = Command(shell_cmd, stdin=pipe_text, shell=self, **kwargs)
        self.history.append(cmd)

        # Run the command
        echo = self.get_echo_results()
        if not self.use_old_cmd:
            self.proc.stdin.write(bytes(cmd) + b" ; " + echo + self.NEWLINE_BYTES)
        else:
            # Old cmd prompt has problems and doesn't respect ";"
            # echo results is called below. This ruins prompts.
            self.proc.stdin.write(bytes(cmd) + self.NEWLINE_BYTES)
        self.proc.stdin.flush()
        time.sleep(0.00001)

        # Check for pipe ... Windows cannot multiline echo very well. Yes you can (echo \n echo...)
        if pipe_text:
            # Get PID
            pids = windows_get_pids(ppid=self.proc.pid, cmdline=cmd.cmdline())
            if not pids:
                raise RuntimeError('Could not find the process id to pipe data into!')

            # Send the pipe_text into stdin
            if not isinstance(pipe_text, (bytes, bytearray)):
                pipe_text = str(pipe_text).encode('utf-8')  # Key is quote
            self.proc.stdin.write(pipe_text + self.NEWLINE_BYTES)
            self.proc.stdin.flush()

            # Wait and give ctrl+C to the command
            time.sleep(0.1)  # No idea what happens if this timeout is not long enough
            if pids:
                os.kill(pids[0], signal.SIGINT)

            # Windows cannot multiline echo, so we have to call echo multiple times
            # pipe_split = pipe_text.split(self.NEWLINE_BYTES)
            # bs = b'@echo off' + self.NEWLINE_BYTES
            # bs += b'(' + self.NEWLINE_BYTES
            # for ptext in pipe_split:
            #     if ptext:
            #         bs += b'echo ' + ptext + self.NEWLINE_BYTES
            # bs += b') |'
            # self.proc.stdin.write(bs)
            # self.proc.stdin.flush()

        # Tell the shell to echo the last results this lets us know when the previous command finishes
        if self.use_old_cmd:
            # Old cmd prompt has problems and doesn't respect ";"
            # This will send the echo results to stdin which will ruin prompts
            try:
                self.proc.stdin.write(echo + self.NEWLINE_BYTES)
                self.proc.stdin.flush()
            except (OSError, Exception):
                pass  # Given command closed the shell

        return cmd

    def _run(self, shell_cmd, pipe_text='', **kwargs):
        """Run the given text command."""
        if self.is_windows():
            return self._run_windows(shell_cmd, pipe_text=pipe_text, **kwargs)
        else:
            return self._run_linux(shell_cmd, pipe_text=pipe_text, **kwargs)

    def run(self, *args, pipe_text='', block=None, **kwargs):
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
        # Check if running
        if not self.is_running():
            self.start()
        elif not self.is_proc_running():
            raise ShellExit('The internal shell process was closed and is no longer running!')

        # Format the arguments
        arg = self.shell_args(*args, **kwargs)

        # Run the command
        cmd = self._run(arg, pipe_text=pipe_text)

        # Check for completion
        if block is None:
            block = self.is_blocking()
        if block is True:
            self.wait()
        else:
            time.sleep(block or 0)

        return cmd

    def input(self, value, wait: bool = False):
        """Input text into the process' stdin. Do not expect this to be a command and do not wait to finish.

        Args:
            value (str/bytes): Value to pass into stdin.
            wait (bool)[False]: If True wait for all previous commands to finish.
        """
        if isinstance(value, str):
            value = value.encode()
        if not value.strip(b" ").endswith(b"\n"):
            value = value + self.NEWLINE_BYTES
        self.proc.stdin.write(value)
        self.proc.stdin.flush()

        if wait:
            self.wait()

    def pipe(self, pipe_text, *args, block=None, **kwargs):
        """Run the given task and pipe the given text to it.

        Args:
            pipe_text (str): Text to pipe into the task
            block (float/bool)[None]: If None use Shell setting else sleep the number of seconds given.
            *args (tuple/object): Arguments to combine into a runnable string.
            **kwargs (dict/object): Keyword arguments to combine into a runnable string with "--key value".

        Returns:
            success (bool)[True]: If True the call did not print any output to stderr.
                If False there was some output printed to stderr.
        """
        return self.run(*args, pipe_text=pipe_text, block=block, **kwargs)

    def python(self, *args, venv=None, windows=None, python_call=None, **kwargs):
        """Run the given lines as a python script.

        Args:
            *args (tuple/object): Series of python lines of code to run.
            venv (str)[None]: Venv path to activate before calling python.
            windows (bool)[None]: Manually give if the venv is in windows.
            python_call (str)[None]: Python command. By default this is "python"
            **kwargs (dict/object): Additional keyword arguments.

        Returns:
            python (str): Python command string.
        """
        # Check if running
        if not self.is_running():
            self.start()
        elif not self.is_proc_running():
            raise ShellExit('The internal shell process was closed and is no longer running!')

        # Format the arguments
        python_call = python_call or self.python_call
        arg = self.python_args(*args, venv=venv, windows=windows, python_call=python_call, **kwargs)

        # Run the command
        self._run(arg)

        # Check for completion
        if self.is_blocking():
            self.wait()

        return self.last_command

    @staticmethod
    def read_pipe(pipe, callback, timeout: float = 0.5):
        """Continuously read the given pipe.

        Args:
            pipe (io.TextIOOWrapper): File object/buffer from the subprocess to read from and redirect with.
            callback (function/callable): Function that handles the data read from the pipe.
            timeout (float)[2]: Select timeout
        """
        # Change pipe to non-blocking. Popen requires bufsize=0
        set_non_blocking(pipe)
        buffer = io.BufferedReader(pipe)

        last_read_data = 0
        while True:
            try:
                # Read all data from the buffer 1 time non-blocking
                try:
                    data = buffer.read1()
                except (BlockingIOError, OSError):  # Windows non-blocking can cause OSError
                    data = b''
                has_data = len(data) > 0
                if has_data:
                    last_read_data = time.time()
                    callback(data)
                elif (time.time() - last_read_data) > timeout:
                    # Timeout to try processing what is left in buffer
                    last_read_data = time.time()
                    callback(b'')
                else:
                    time.sleep(0.1)
            except BrokenPipeError:
                break

    def _parse_output(self, line):
        """Parse the end command echo results."""
        # Skip parsing the current command
        try:
            cmd = bytes(self.current_command)
            cmd_echo = cmd + b" ; " + self.get_echo_results()
            if line.strip().endswith(cmd) or line.strip().endswith(cmd_echo):
                return b'', None
        except (AttributeError, TypeError, Exception):
            pass

        # Check the finished flag
        exit_code = None
        end_cmd = self.end_command_bytes
        if end_cmd and end_cmd in line:
            try:
                idx = line.index(end_cmd)
                end_idx = line[idx+1:].index(self.NEWLINE_BYTES)

                output = line[idx+len(end_cmd): idx+1+end_idx]
                line = b''

                # If no exit code it is an echo of cmd
                status = output.strip().decode('utf-8')
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

        return line, exit_code

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
        last_line_parsed = False
        for line in lines:
            # Write all output to stdout, stderr
            try:
                self.write_buffer(stdfile, line)
            except(IndexError, KeyError, TypeError, ValueError, Exception):
                pass

            # ===== Parse data to add to command stdout, stderr =====
            # Skip blank lines from command echo
            if last_line_parsed and not line.strip():
                continue

            # Check the finished flag
            parsed, exit_code = self._parse_output(line)
            last_line_parsed = line != parsed
            if parsed:
                try:
                    self.history[self.finished_count].add_pipe_data(pipe_name, parsed)
                except (AttributeError, IndexError, TypeError, ValueError, Exception):
                    pass
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

    def start(self):
        """Start the continuous shell process."""
        if self.is_running():
            self.close()

        # Create the continuous terminal process
        if self.is_windows():
            if not self.use_old_cmd:
                self.proc = Popen('powershell.exe -NoLogo -NoExit', bufsize=0, stdin=PIPE, stdout=PIPE, stderr=PIPE,
                                  shell=self.shell)
            else:
                # /K run command and remain (disables the banner)
                self.proc = Popen('cmd.exe /K', bufsize=0, stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=self.shell)
        else:
            self.proc = Popen('/bin/bash', bufsize=0, stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=self.shell)

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

        if self.is_windows() and self.use_old_cmd:
            # Allow echo results and remove from the command history
            self.run('setlocal enabledelayedexpansion', block=True)
            self.finished_count -= 1
            self.history.pop()

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

    def parallel(self, *scripts, stdout=None, stderr=None, wait_on_exit=None, close_on_exit=None, python_call=None,
                 **kwargs):
        if stdout is None:
            stdout = self.stdout
        if stderr is None:
            stderr = self.stderr
        if wait_on_exit is None:
            wait_on_exit = self.wait_on_exit
        if close_on_exit is None:
            close_on_exit = self.close_on_exit
        if python_call is None:
            python_call = self.python_call

        sh = ParallelShell(*scripts, stdout=stdout, stderr=stderr, python_call=self.python_call,
                           wait_on_exit=wait_on_exit, close_on_exit=close_on_exit, **kwargs)
        self._parallel_shell.append(sh)
        return sh

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


class ParallelShell(list):
    is_windows = staticmethod(is_windows)
    is_linux = staticmethod(is_linux)
    shell_args = shell_args
    python_args = python_args
    write_buffer = staticmethod(write_buffer)

    NEWLINE = os.linesep
    NEWLINE_BYTES = NEWLINE.encode('utf-8')

    def __init__(self, *tasks, stdout=None, stderr=None, wait_on_exit=True, close_on_exit=True, python_call=None,
                 **kwargs):
        super().__init__()

        self.stdout = stdout
        self.stderr = stderr
        self.wait_on_exit = wait_on_exit
        self.close_on_exit = close_on_exit
        self.python_call = python_call

        for task in tasks:
            if isinstance(task, (list, tuple)):
                self.run(*task, **kwargs)
            else:
                self.run(task, **kwargs)

    def run(self, *args, stdout=None, stderr=None, wait_on_exit=None, close_on_exit=None, pipe_text='', block=None, **kwargs):
        if stdout is None:
            stdout = self.stdout
        if stderr is None:
            stderr = self.stderr
        if wait_on_exit is None:
            wait_on_exit = self.wait_on_exit
        if close_on_exit is None:
            close_on_exit = self.close_on_exit

        sh = Shell(blocking=False, stdout=stdout, stderr=stderr, wait_on_exit=wait_on_exit, close_on_exit=close_on_exit,
                   python_call=self.python_call)
        self.append(sh)
        sh.run(*args, pipe_text=pipe_text, block=block, **kwargs)

        return sh

    def python(self, *args, venv=None, windows=None, python=None, stdout=None, stderr=None,
               wait_on_exit=None, close_on_exit=None, pipe_text='', block=None, **kwargs):
        """Run the given lines as a python script.

        Args:
            *args (tuple/object): Series of python lines of code to run.
            venv (str)[None]: Venv path to activate before calling python.
            windows (bool)[None]: Manually give if the venv is in windows.
            python (str)[None]: Python command. By default this is "python"
            stdout (io.TextIOWrapper/object)[None]: Standard out to redirect the separate process standard out to.
            stderr (io.TextIOWrapper/object)[None]: Standard error to redirect the separate process standard out to.
            wait_on_exit (bool)[True]: If True on context manager exit wait for all commands to finish.
            close_on_exit (bool)[True]: If True close the process when the context manager exits. This may be useful
                to be false for running multiple processes. Method "wait" can always be called to wait for all commands.
            pipe_text (str)['']: Text to pipe into the task
            block (float/bool)[None]: If None use Shell setting else sleep the number of seconds given.
            **kwargs (dict/object): Additional keyword arguments.

        Returns:
            python (str): Python command string.
        """
        if stdout is None:
            stdout = self.stdout
        if stderr is None:
            stderr = self.stderr
        if wait_on_exit is None:
            wait_on_exit = self.wait_on_exit
        if close_on_exit is None:
            close_on_exit = self.close_on_exit

        sh = Shell(blocking=False, stdout=stdout, stderr=stderr, wait_on_exit=wait_on_exit, close_on_exit=close_on_exit,
                   python_call=self.python_call)
        self.append(sh)
        sh.python(*args, venv=venv, windows=windows, python=python, pipe_text=pipe_text, block=block, **kwargs)

        return sh

    def is_running(self, *additional, **kwargs):
        """Return if the continuous shell process is running."""
        return any((sh.is_running() for sh in list(additional) + self if hasattr(sh, 'is_running')))

    def is_proc_running(self, *additional, **kwargs):
        """Return if the process is running."""
        return any((sh.is_proc_running() for sh in list(additional) + self if hasattr(sh, 'is_proc_running')))

    def is_finished(self, *additional, **kwargs):
        """Return if all processes are running """
        return all((sh.is_finished() for sh in list(additional) + self if hasattr(sh, 'is_finished')))

    def wait(self, *additional, **kwargs):
        """Wait until all of the commands are finished or until the process exits."""
        procs = [sh for sh in list(additional) + self if hasattr(sh, 'is_proc_running') and hasattr(sh, 'is_finished')]
        while any((sh.is_proc_running() and not sh.is_finished()) for sh in procs):
            # and not self.is_finished('err')
            time.sleep(0.1)
        return self

    def stop(self, *additional):
        """Stop the continuous shell process. This method does not wait and closes everything immediately."""
        for sh in list(additional) + self:
            sh.stop()
        return self

    def close(self, *additional):
        """Close the continuous shell process. This method does not wait and closes everything immediately."""
        try:
            self.stop(*additional)
        except:
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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        no_error = exc_type is None

        if no_error and self.wait_on_exit:
            self.wait()
        if self.close_on_exit:
            self.close()
        return no_error
