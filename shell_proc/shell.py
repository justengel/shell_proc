import io
import sys
import platform
import time
import threading
import atexit
from subprocess import Popen, PIPE


__all__ = ['is_windows', 'is_linux', 'args_to_str', 'write_buffer', 'Shell']


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

    if not text.endswith('\n'):
        text += '\n'
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
    pass


class Shell(object):
    """Continuous Shell process to run a series of commands."""
    is_windows = staticmethod(is_windows)
    is_linux = staticmethod(is_linux)
    args_to_str = staticmethod(args_to_str)
    write_buffer = staticmethod(write_buffer)

    def __init__(self, *tasks, stdout=None, stderr=None):
        """Initialize the Shell object.

        Args:
            *tasks (tuple/str/object): List of string commands to run.
            stdout (io.TextIOWrapper/object)[None]: Standard out to redirect the separate process standard out to.
            stderr (io.TextIOWrapper/object)[None]: Standard error to redirect the separate process standard out to.
        """
        # Public Variables
        self.stdout = None
        self.stderr = None
        self.proc = None

        # Private Variables
        self._last_task = b''
        self._finished_out = False
        self._finished_err = False
        self._has_out = False
        self._has_err = False
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

    def is_finished(self, pipe_name):
        """Return if the finished flag was set for the given pipe_name (self._finished_out or self._finished_err)."""
        var_name = '_finished_{}'.format(pipe_name)
        return getattr(self, var_name, False)

    def has_print(self, pipe_name):
        """Return if the given pipe name had printable output from the previous command."""
        var_name = '_has_{}'.format(pipe_name)
        return getattr(self, var_name, False)

    def has_print_out(self):
        """Return if the previous command had any printable output. This is always True, because the end terminal line
        is always sent to be printed after the command runs.
        """
        return self._has_out

    def has_print_err(self):
        """Return if the previous command had any error output.

        Warning:
            This may not mean an error occurred. It just means that printable output was sent to stderr. A warning
            could have been printed instead of an error.
        """
        return self._has_err

    def get_stdout(self):
        """Return the read text from stdout."""
        try:
            if self.stdout.seekable():
                self.stdout.seek(0)
            out = self.stdout.read()
            if not isinstance(out, str):
                out = out.decode('utf-8')
            return out
        except:
            return ''

    def print_stdout(self, file=None):
        """Print the collected stdout."""
        if file is None:
            file = sys.stdout
        print(self.get_stdout(), file=file)

    def get_stderr(self):
        """Return the read text from stderr."""
        try:
            if self.stderr.seekable():
                self.stderr.seek(0)
            out = self.stderr.read()
            if not isinstance(out, str):
                out = out.decode('utf-8')
            return out
        except:
            return ''

    def print_stderr(self, file=None):
        """Print the collected stderr."""
        if file is None:
            file = sys.stderr
        print(self.get_stderr(), file=file)

    def set_flags(self, pipe_name, msg):
        """Set if the given pipe has any printable output."""
        has_name = '_has_{}'.format(pipe_name)
        finish_name = '_finished_{}'.format(pipe_name)

        # ===== Check the finished flag =====
        if not getattr(self, finish_name, False) and msg.endswith(b'>\n'):
            setattr(self, finish_name, True)

        # ===== Check the has_print flag =====
        has_msg = msg.strip()
        is_first = has_msg.endswith(self._last_task.strip())

        # Check if can set. Do not count the last line sent to stdout.
        if (not self.is_finished(pipe_name) and not getattr(self, has_name, False)) and not is_first and has_msg:
            setattr(self, has_name, True)

    def reset_flags(self):
        """Reset the task flags."""
        self._finished_out = False
        self._finished_err = False
        self._has_out = False
        self._has_err = False

    def _run(self, text_cmd):
        """Run the given text command."""
        # Write input to run command
        self._last_task = str(text_cmd).encode('utf-8') + b'\n'
        self.proc.stdin.write(self._last_task)
        self.proc.stdin.flush()

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

        # Set flags
        self.reset_flags()

        # Run the command
        self._run(text)

        # Check for completion
        self.wait_for_finshed()

        return not self.has_print_err()

    def _read_pipe(self, pipe_name, pipe):
        """Continuously read the given pipe.

        Args:
            pipe_name (str): Name of the pipe for variables ('out' or 'err' for self.stdout and self._finished_out).
            pipe (io.TextIOOWrapper): File object/buffer from the subprocess to read from and redirect.
        """
        while True:
            try:
                # Read the incoming lines from the PIPE
                for msg in pipe:
                    try:
                        self.set_flags(pipe_name, msg)

                        # print(msg.decode('utf-8', 'ignore'), end='', flush=True, file=self.get_file(pipe_name))
                        self.write_buffer(self.get_file(pipe_name), msg)
                    except (ValueError, Exception):
                        pass
            except (BrokenPipeError, Exception):
                break

    def is_running(self):
        """Return if the continuous shell process is running."""
        return self.proc is not None

    def is_proc_running(self):
        """Return if the process is running."""
        return self.proc is not None and self.proc.poll() is None

    def wait_for_finshed(self):
        """Wait until the task is finished running."""
        while self.is_proc_running() and not self.is_finished('out'):  # and not self.is_finished('err')
            time.sleep(0.1)

    def start(self):
        """Start the continuous shell process."""
        if self.is_running():
            self.close()

        # Create the continuous terminal process
        if self.is_windows():
            self.proc = Popen('cmd.exe', stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=False)
        else:
            self.proc = Popen('/bin/bash', stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=False)

        self._th_out = threading.Thread(target=self._read_pipe, args=('out', self.proc.stdout))
        self._th_out.daemon = True
        self._th_out.start()

        self._th_err = threading.Thread(target=self._read_pipe, args=('err', self.proc.stderr))
        self._th_err.daemon = True
        self._th_err.start()
        atexit.register(self.stop)

        # Reset the task flags and remove the initial output message
        time.sleep(0.1)
        self.reset_flags()

    def stop(self):
        """Stop the continuous shell process."""
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

    def close(self):
        """Close the continuous shell process."""
        try:
            self.stop()
        except:
            pass

    def __del__(self):
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
        self.close()
        return exc_type is None
