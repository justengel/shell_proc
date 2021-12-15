import io
import os
import sys
import platform
import time
import threading
import atexit
import shlex
import signal
import psutil
from subprocess import Popen, PIPE


__all__ = ['is_windows', 'is_linux', 'write_buffer', 'quote', 'shell_args', 'python_args',
           'ShellExit', 'Command', 'Shell', 'ParallelShell']


def is_windows():
    """Return if this platform is windows."""
    return platform.system() == 'Windows'


def is_linux():
    """Return if this platform is linux."""
    return not is_windows()


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
    fp.flush()


def quote(text):
    if ' ' in text:
        return '"{}"'.format(text.replace('"', '\\"'))
    return text


class shell_args(object):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = [str(a) for a in args]
        self.kwargs = kwargs

    def cmdline(self):
        return shlex.split(str(self))

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
    def __init__(self, *args, venv=None, windows=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.venv = venv
        self.windows = windows

    def __str__(self):
        cmd = ['python']
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

    def __init__(self, cmd='', exit_code=None, stdout='', stderr='', stdin='',
                 shell=None, pid=None, pipe_timeout=None, **kwargs):
        super().__init__()
        if exit_code is None:
            exit_code = self.DEFAULT_EXIT_CODE
        if pipe_timeout is None:
            pipe_timeout = 1

        self.cmd = cmd
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.stdin = stdin  # Not really used. Maybe used with pipe?
        self.shell = shell
        self.pid = pid

        self.pipe_timeout = pipe_timeout
        self._last_pipe_data_time = 0
        self._pipe_thread = None
        self._end_pipe_thread = False

    def cmdline(self):
        try:
            return self.cmd.cmdline()
        except (AttributeError, Exception):
            return shlex.split(str(self.cmd))

    def pipe(self, pipe_text):
        self.stdin = pipe_text
        if not isinstance(pipe_text, bytes):
            pipe_text = quote(str(pipe_text)).encode('utf-8')
        self.shell.stdin.write(pipe_text)
        self.shell.stdin.flush()
        time.sleep(0.01)
        self._last_pipe_data_time = time.time()

        self._pipe_thread = threading.Thread(target=self.wait_for_pipe, daemon=True)
        self._pipe_thread.start()

    def wait_for_pipe(self):
        time_dif = self.pipe_timeout - (time.time() - self._last_pipe_data_time)
        while time_dif > 0 and not self._end_pipe_thread:
            try:
                time.sleep(time_dif)
            except (TypeError, ValueError, Exception):
                time.sleep(0.01)
            time_dif = self.pipe_timeout - (time.time() - self._last_pipe_data_time)

        self.kill()

    def check_end_pipe_thread(self):
        if self._end_pipe_thread:
            try:
                self._pipe_thread.join(0)
            except (AttributeError, TypeError, Exception):
                pass
            self._pipe_thread = None
            self._end_pipe_thread = False

    def kill(self):
        """Kill so the process stops waiting for stdin or pipe data."""
        self._end_pipe_thread = True
        os.kill(self.pid, signal.SIGINT)  # Stop the input

        if self.shell is not None:
            self.shell.echo_last_results()

    def add_pipe_data(self, pipe_name, data):
        """Add output data to the proper file/pipe handler."""
        if not pipe_name.startswith('std'):
            pipe_name = 'std' + pipe_name
        if isinstance(data, bytes):
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
        self.check_end_pipe_thread()
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

    def __or__(self, other):
        if not isinstance(other, (str, shell_args)):
            raise TypeError('Cannot PIPE type of {}'.format(type(other)))
        elif not self.has_output():
            raise RuntimeError('Command has no output to PIPE!')

        return self.shell.pipe(self.stdout, other)


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
                 blocking=True, wait_on_exit=True, close_on_exit=True, **kwargs):
        """Initialize the Shell object.

        Args:
            *tasks (tuple/str/object): List of string commands to run.
            stdout (io.TextIOWrapper/object)[None]: Standard out to redirect the separate process standard out to.
            stderr (io.TextIOWrapper/object)[None]: Standard error to redirect the separate process standard out to.
            blocking (bool)[True]: If False write to stdin without waiting for the previous command to finish.
            wait_on_exit (bool)[True]: If True on context manager exit wait for all commands to finish.
            close_on_exit (bool)[True]: If True close the process when the context manager exits. This may be useful
                to be false for running multiple processes. Method "wait" can always be called to wait for all commands.
        """
        # Public Variables
        self.stdout = None
        self.stderr = None
        self.shell = shell
        self.proc = None
        self.process = None
        self._blocking = blocking
        self.wait_on_exit = wait_on_exit
        self.close_on_exit = close_on_exit
        self.pipe_timeout = 1  # seconds

        self._parallel_shell = []  # Keep parallel shells to close when we close
        self.history = []
        self._finished_count = 0
        self._end_command = '=========== SHELL END COMMAND =========='
        self._end_command_bytes = self._end_command.encode('utf-8')

        # Private Variabless
        self._th_out = None
        self._th_err = None

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

    @property
    def current_command(self):
        """Return the current command that is still running or was last_completed."""
        try:
            idx = -1
            if not self.is_finished():
                idx = self._finished_count
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
        if isinstance(value, bytes):
            self._end_command_bytes = value
            self._end_command = self._end_command_bytes.decode('utf-8', 'replace')
        else:
            self._end_command = str(value)
            self._end_command_bytes = self._end_command.encode('utf-8')

    end_command = property(get_end_command, set_end_command)
    end_command_bytes = property(get_end_command_bytes, set_end_command)

    def echo_last_results(self):
        """Send a command to echo the results of the last command."""
        if self.is_windows():
            cmd = 'echo {end_cmd} {report}{nl}'.format(end_cmd=self.end_command, report='%errorlevel%', nl=self.NEWLINE)
        else:
            cmd = 'echo "{end_cmd} {report}"{nl}'.format(end_cmd=self.end_command, report='$?', nl=self.NEWLINE)
        self.proc.stdin.write(cmd.encode('utf-8'))
        self.proc.stdin.flush()

    def _run(self, shell_cmd, pipe_text='', pipe_timeout=None, **kwargs):
        """Run the given text command."""
        # Write input to run command
        cmd = Command(shell_cmd, stdin=pipe_text, shell=self, pipe_timeout=pipe_timeout, **kwargs)
        self.history.append(cmd)

        # Get the child to see if there are new children
        cmdline = cmd.cmdline()
        ppid = self.proc.pid
        pids = psutil.pids()  # children = [c.pid for c in self.process.children()]

        # Run the command
        self.proc.stdin.write(bytes(cmd) + self.NEWLINE_BYTES)
        self.proc.stdin.flush()

        # Find the pid
        for pid in psutil.pids():
            if pid not in pids:
                p = psutil.Process(pid)
                if p.ppid() == ppid and p.cmdline() == cmdline:
                    cmd.pid = p.pid
                    break

        # Pipe text into the previous command
        if pipe_text:
            # Pipe will continuously wait for input.
            # Command.pipe will run a thread to wait for stdout/stderr timeout and
            # echo_last_results to signal that it is finished
            cmd.pipe(pipe_text)
        else:
            # Tell the shell to echo the last results this lets us know when the previous command finishes
            try:
                self.echo_last_results()
            except (OSError, Exception):
                pass  # Given command closed the shell

        return cmd

    def run(self, *args, pipe_text='', **kwargs):
        """Run the given task.

        Args:
            *args (tuple/object): Arguments to combine into a runnable string.
            pipe_text (str)['']: Text to pipe into the task
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
        self._run(arg, pipe_text=pipe_text)

        # Check for completion
        if self.is_blocking():
            self.wait()

        return self.last_command

    def pipe(self, pipe_text, *args, **kwargs):
        """Run the given task and pipe the given text to it.

        Args:
            pipe_text (str): Text to pipe into the task
            *args (tuple/object): Arguments to combine into a runnable string.
            **kwargs (dict/object): Keyword arguments to combine into a runnable string with "--key value".

        Returns:
            success (bool)[True]: If True the call did not print any output to stderr.
                If False there was some output printed to stderr.
        """
        return self.run(*args, pipe_text=pipe_text, **kwargs)

    def python(self, *args, venv=None, windows=None, **kwargs):
        """Run the given lines as a python script.

        Args:
            *args (tuple/object): Series of python lines of code to run.
            venv (str)[None]: Venv path to activate before calling python.
            windows (bool)[None]: Manually give if the venv is in windows.
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
        arg = self.python_args(*args, venv=venv, windows=windows, **kwargs)

        # Run the command
        self._run(arg)

        # Check for completion
        if self.is_blocking():
            self.wait()

        return self.last_command

    @staticmethod
    def read_pipe(pipe, callback=None):
        """Continuously read the given pipe.

        Args:
            pipe (io.TextIOOWrapper): File object/buffer from the subprocess to read from and redirect.
            callback (function/callable)[None]: Function that handles the data read from the pipe.
        """
        if not callable(callback):
            callback = lambda msg: None

        while True:
            try:
                # Read the incoming lines from the PIPE
                for msg in pipe:
                    try:
                        callback(msg)
                    except (ValueError, TypeError, Exception):
                        pass
            except (BrokenPipeError, Exception):
                break

    def check_output(self, msg):
        """Check the output message.

        Returns:
            msg (bytes): Output message to parse.
        """
        # ===== Check the finished flag =====
        end_cmd = self.end_command_bytes
        if end_cmd and end_cmd in msg:  # Ignore all "echo END_COMMAND"
            try:
                idx = msg.index(end_cmd)
                exit_code = int(msg[idx+len(end_cmd):].strip().decode('utf-8'))  # If no exit code it is an echo of cmd
                self.history[self._finished_count].exit_code = exit_code
                self._finished_count += 1
            except:
                pass
            return False

        # ===== Check the has_print flag =====
        has_msg = msg.strip()
        try:
            is_not_cmd = not has_msg.endswith(bytes(self.current_command))
        except (AttributeError, TypeError, ValueError, Exception):
            is_not_cmd = False

        # Check if there is output and that the output is not from the stdin running the command (Windows).
        if not self.is_finished() and has_msg and is_not_cmd:
            try:
                self.history[self._finished_count].add_pipe_data('out', msg)
            except:
                pass
            try:
                self.write_buffer(self.stdout, msg)
            except:
                pass

    def check_error(self, msg):
        """Check the error message.

        Returns:
            msg (bytes): Error message to parse.
        """
        # ===== Check the finished flag ERROR =====
        end_cmd = self.end_command_bytes
        if end_cmd and end_cmd in msg:
            # Error Occurred during the "echo END_COMMAND" (like interactive python tries echo as python code)
            try:
                self.history[self._finished_count].exit_code = 1
                self._finished_count += 1
            except:
                pass
            # return False

        try:
            self.history[self._finished_count].add_pipe_data('err', msg)
        except:
            pass
        try:
            self.write_buffer(self.stderr, msg)
        except:
            pass

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
        if len(self.history) > self._finished_count:
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
            # /K run command and remain (disables the banner)
            self.proc = Popen('cmd.exe /K', stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=self.shell)
            # self.proc= Popen('powershell.exe -NoLogo -NoExit', stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=self.shell)
        else:
            self.proc = Popen('/bin/bash', stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=self.shell)

        # Command count
        self.process = psutil.Process(self.proc.pid)
        self.history = []
        self._finished_count = 0

        # Start stderr and stdout threads
        self._th_out = threading.Thread(target=self.read_pipe, args=(self.proc.stdout, self.check_output))
        self._th_out.daemon = True
        self._th_out.start()

        self._th_err = threading.Thread(target=self.read_pipe, args=(self.proc.stderr, self.check_error))
        self._th_err.daemon = True
        self._th_err.start()
        atexit.register(self.stop)

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
        try:
            self._th_err.join(0)
        except:
            pass
        try:
            self.proc.stdin.close()
        except:
            pass
        try:
            self.proc.terminate()
        except:
            pass
        self._th_out = None
        self._th_err = None
        self.proc = None
        self.process = None
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

    def parallel(self, *scripts, stdout=None, stderr=None, wait_on_exit=None, close_on_exit=None, **kwargs):
        if stdout is None:
            stdout = self.stdout
        if stderr is None:
            stderr = self.stderr
        if wait_on_exit is None:
            wait_on_exit = self.wait_on_exit
        if close_on_exit is None:
            close_on_exit = self.close_on_exit

        sh = ParallelShell(*scripts, stdout=stdout, stderr=stderr,
                           wait_on_exit=wait_on_exit, close_on_exit=close_on_exit, **kwargs)
        self._parallel_shell.append(sh)
        return sh

    def __del__(self):
        """Close the continuous shell process. This method does not wait and closes everything immediately."""
        try:
            self.close()
        except:
            pass

    def __call__(self, *args, **kwargs):
        """Run the given task.

        Args:
            *args (tuple/object): Arguments to combine into a runnable string.
            **kwargs (dict/object): Keyword arguments to combine into a runnable string with "--key value".

        Returns:
            success (bool)[True]: If True the call did not print any output to stderr.
                If False there was some output printed to stderr.
        """
        try:
            return self.run(*args, **kwargs)
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

    def __init__(self, *tasks, stdout=None, stderr=None, wait_on_exit=True, close_on_exit=True, **kwargs):
        super().__init__()

        self.stdout = stdout
        self.stderr = stderr
        self.wait_on_exit = wait_on_exit
        self.close_on_exit = close_on_exit

        for task in tasks:
            if isinstance(task, (list, tuple)):
                self.run(*task, **kwargs)
            else:
                self.run(task, **kwargs)

    def run(self, *args, stdout=None, stderr=None, wait_on_exit=None, close_on_exit=None, **kwargs):
        if stdout is None:
            stdout = self.stdout
        if stderr is None:
            stderr = self.stderr
        if wait_on_exit is None:
            wait_on_exit = self.wait_on_exit
        if close_on_exit is None:
            close_on_exit = self.close_on_exit

        sh = Shell(blocking=False, stdout=stdout, stderr=stderr, wait_on_exit=wait_on_exit, close_on_exit=close_on_exit)
        self.append(sh)
        sh.run(*args, **kwargs)

        return sh

    def python(self, *args, venv=None, windows=None, stdout=None, stderr=None,
               wait_on_exit=None, close_on_exit=None, **kwargs):
        """Run the given lines as a python script.

        Args:
            *args (tuple/object): Series of python lines of code to run.
            venv (str)[None]: Venv path to activate before calling python.
            windows (bool)[None]: Manually give if the venv is in windows.
            stdout (io.TextIOWrapper/object)[None]: Standard out to redirect the separate process standard out to.
            stderr (io.TextIOWrapper/object)[None]: Standard error to redirect the separate process standard out to.
            wait_on_exit (bool)[True]: If True on context manager exit wait for all commands to finish.
            close_on_exit (bool)[True]: If True close the process when the context manager exits. This may be useful
                to be false for running multiple processes. Method "wait" can always be called to wait for all commands.
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

        sh = Shell(blocking=False, stdout=stdout, stderr=stderr, wait_on_exit=wait_on_exit, close_on_exit=close_on_exit)
        self.append(sh)
        sh.python(*args, **kwargs)

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

    def __call__(self, *args, **kwargs):
        """Run the given task.

        Args:
            *args (tuple/object): Arguments to combine into a runnable string.
            **kwargs (dict/object): Keyword arguments to combine into a runnable string with "--key value".

        Returns:
            success (bool)[True]: If True the call did not print any output to stderr.
                If False there was some output printed to stderr.
        """
        try:
            return self.run(*args, **kwargs)
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
