import io
import os
import sys
import platform
import time
import threading
import atexit
from subprocess import Popen, PIPE


__all__ = ['is_windows', 'is_linux', 'args_to_str', 'write_buffer', 'ShellExit', 'Command', 'Shell']


def is_windows():
    """Return if this platform is windows."""
    return platform.system() == 'Windows'


def is_linux():
    """Return if this platform is linux."""
    return not is_windows()


def args_to_str(*args, **kwargs):
    """Convert the given args to a string command."""
    text = ''
    if len(args) > 0:
        text += ' '.join((str(arg) for arg in args))
    if len(kwargs) > 0:
        if len(args) > 0:
            text += ' '
        text += ' '.join(('--{} {}'.format(k, v) for k, v in kwargs.items()))

    text = text.rstrip()
    return text


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


class ShellExit(Exception):
    """Exception to indicate the Shell exited through some shell command."""
    pass


class Command(object):
    """Command that was run with the results."""
    DEFAULT_EXIT_CODE = -1

    def __init__(self, cmd='', exit_code=None, stdout='', stderr=''):
        if exit_code is None:
            exit_code = self.DEFAULT_EXIT_CODE

        self.cmd = cmd
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    def add_pipe_data(self, pipe_name, data):
        """Add output data to the proper file/pipe handler."""
        if not pipe_name.startswith('std'):
            pipe_name = 'std' + pipe_name
        if isinstance(data, bytes):
            data = data.decode('utf-8', 'replace')
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
        return self.cmd

    def __bytes__(self):
        return self.cmd.encode('utf-8')

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


class Shell(object):
    """Continuous Shell process to run a series of commands."""
    is_windows = staticmethod(is_windows)
    is_linux = staticmethod(is_linux)
    args_to_str = staticmethod(args_to_str)
    write_buffer = staticmethod(write_buffer)

    NEWLINE = os.linesep

    def __init__(self, *tasks, stdout=None, stderr=None, blocking=True, wait_on_exit=True, close_on_exit=True,
                 **kwargs):
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
        self.proc = None
        self._blocking = blocking
        self.wait_on_exit = wait_on_exit
        self.close_on_exit = close_on_exit

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

    def get_echo_end_command(self):
        """Return the echo end command used to determine when the command finshed."""
        if self.is_windows():
            return b'echo ' + self.end_command_bytes + b' %errorlevel%'
        else:
            return b'echo "' + self.end_command_bytes + b' $?"'

    def _run(self, text_cmd):
        """Run the given text command."""
        # Write input to run command
        cmd = Command(str(text_cmd))
        self.history.append(cmd)

        # Run the command and the echo command to get the results
        self.proc.stdin.write(cmd.cmd.encode('utf-8') + self.NEWLINE.encode('utf-8'))
        self.proc.stdin.write(self.get_echo_end_command() + self.NEWLINE.encode('utf-8'))
        self.proc.stdin.flush()

        return cmd

    def run(self, *args, **kwargs):
        """Run the given task.

        Args:
            *args (tuple/object): Arguments to combine into a runnable string.
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

        # Convert the argument to text to run
        text = self.args_to_str(*args, **kwargs)

        # Run the command
        self._run(text)

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
        if end_cmd in msg:  # Ignore all "echo END_COMMAND"
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
        try:
            self.history[self._finished_count].add_pipe_data('err', msg)
        except:
            pass
        try:
            self.write_buffer(self.stderr, msg)
        except:
            pass

    def is_running(self):
        """Return if the continuous shell process is running."""
        return self.proc is not None

    def is_proc_running(self):
        """Return if the process is running."""
        return self.proc is not None and self.proc.poll() is None

    def is_finished(self):
        """Return if """
        return len(self.history) <= self._finished_count

    def wait(self):
        """Wait until all of the commands are finished or until the process exits."""
        while self.is_proc_running() and not self.is_finished():
            # and not self.is_finished('err')
            time.sleep(0.1)
        return self

    def start(self):
        """Start the continuous shell process."""
        if self.is_running():
            self.close()

        # Create the continuous terminal process
        if self.is_windows():
            # /K run command and remain (disables the banner)
            self.proc = Popen('cmd.exe /K', stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=False)
        else:
            self.proc = Popen('/bin/bash', stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=False)

        # Command count
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
        return self

    def close(self):
        """Close the continuous shell process. This method does not wait and closes everything immediately."""
        try:
            self.stop()
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
        # Check to wait on context manager exit even if non blocking
        if self.wait_on_exit:
            self.wait()
        if self.close_on_exit:
            self.close()
        return exc_type is None
