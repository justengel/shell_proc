import uuid
import atexit
import socket
import threading

from shell_proc.shell import Shell, Command, ShellExit

from .msgs import send_msg, recv_msg, AckNack, RegisterNode, \
    Authenticate, AuthenticationSuccess, AuthenticationFailed, AuthenticationRequired, \
    StartSession, EndSession, RemoteCommandRequest, RemoteCommandReply
from .hub import save_server_defaults, get_server_defaults


class RemoteCommand(Command):
    def __init__(self, cmd='', exit_code=None, stdout='', stderr='', ack=None, nack=None):
        if nack:
            ack = False
        elif ack:
            nack = False
        self.ack = ack
        self.nack = nack
        super().__init__(cmd=cmd, exit_code=exit_code, stdout=stdout, stderr=stderr)


class RemoteShell(Shell):
    def __init__(self, session, *tasks, stdout=None, stderr=None, node=None, close_session=True,
                 address=None, port=None):
        """Initialize the Shell object.

        Args:
            session (str): Name of the session you want to run.
            *tasks (tuple/str/object): List of string commands to run.
            stdout (io.TextIOWrapper/object)[None]: Standard out to redirect the separate process standard out to.
            stderr (io.TextIOWrapper/object)[None]: Standard error to redirect the separate process standard out to.
            node (str)[None]: Name of the node to run the commands on.
            close_session (bool)[True]: Close the session when this object closes.
            address (str)[None]: IP Address of the remote hub to connect to. May be set through an environment variable.
            port (int)[None]: Port of the remote hub to connect to. May be set through an environment variable.
        """
        self._uuid = uuid.uuid4().hex
        self.session = str(session)
        self.node = node
        self.new_shell = False
        self.close_session = close_session  # Close the session when the shell exits.

        self.address = '0.0.0.0'
        self.port = 54333
        self.socket = None

        # Remote hub address and port
        default_address, default_port = get_server_defaults()
        self.address = address or default_address
        self.port = port or default_port

        super().__init__(*tasks, stdout=stdout, stderr=stderr)

    def auth(self, pwd, node=None):
        """Authenticate with the set node."""
        if not self.is_running():
            self.start()
        if node is None:
            node = self.node
        send_msg(self, Authenticate(node, self._uuid, pwd))
        msg = recv_msg(self)
        if isinstance(msg, AuthenticationSuccess):
            return True
        else:
            return False

    def _run(self, text_cmd):
        """Run the given text command."""
        # Write input to run command
        cmd = Command(str(text_cmd))
        self.history.append(cmd)

        msg = RemoteCommandRequest(self.node, self.session, self._uuid, cmd.cmd, new_shell=self.new_shell)
        self.new_shell = False
        send_msg(self, msg)

        return cmd

    def run(self, *args, node=None, session=None, new_shell=False, **kwargs):
        """Run the given task.

        Args:
            *args (tuple/object): Arguments to combine into a runnable string.
            node (str)[None]: Change the node that you want the command to run on.
            session (str)[None]: Session to use to run the command.
            new_shell (bool)[False]: Make a new shell on the remote.
            **kwargs (dict/object): Keyword arguments to combine into a runnable string with "--key value".

        Returns:
            success (bool)[True]: If True the call did not print any output to stderr.
                If False there was some output printed to stderr.
        """
        self.new_shell = new_shell
        if node is not None:
            self.node = node
        if session is not None:
            self.session = session
        return super().run(*args, **kwargs)

    def read_socket(self, sock):
        """Continuously read the given socket.

        Args:
            sock (socket.socket): Socket to recveive messages and set the command history.
        """
        while True:
            stdout = ''
            stderr = ''
            exit_code = RemoteCommandReply.DEFAULT_EXIT_CODE
            try:
                msg = recv_msg(sock)
                if isinstance(msg, AuthenticationRequired):
                    stderr = 'AuthenticationError: The node "{}" requires this shell to authenticate!'.format(self.node)
                    exit_code = 403  # Forbidden

                elif isinstance(msg, AuthenticationFailed):
                    stderr = 'AuthenticationError: The node "{}" authentication failed!'.format(self.node)
                    exit_code = 401  # Unauthorized

                elif isinstance(msg, RemoteCommandReply):
                    cmd = self.history[self._finished_count]
                    assert cmd.cmd == msg.cmd
                    stdout = msg.stdout
                    stderr = msg.stderr
                    exit_code = msg.exit_code

                if exit_code != -1:
                    # Write the output
                    if self.stdout is not None and stdout:
                        self.write_buffer(self.stdout, stdout)
                    if self.stderr is not None and stderr:
                        self.write_buffer(self.stderr, stderr)

                    # Set the command history values.
                    cmd = self.history[self._finished_count]
                    cmd.stdout = stdout
                    cmd.stderr = stderr
                    cmd.exit_code = exit_code
                    self._finished_count += 1
            except:
                print('Commands do not match!')
                pass


    def start(self):
        """Start the continuous shell process."""
        if self.is_running():
            self.close()

        # Connect the socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.address, self.port))

        # Command count
        self.history = []
        self._finished_count = 0

        # Start the session
        msg = StartSession(self.session)
        send_msg(self, msg)

        # Receive Ack Nack
        msg = recv_msg(self)
        if isinstance(msg, AckNack) and not msg.ack:
            self.close()
            raise RuntimeError('Could not connect to the remote host properly.')

        # Start stderr and stdout threads
        self._th_out = threading.Thread(target=self.read_socket, args=(self.socket,))
        self._th_out.daemon = True
        self._th_out.start()

        # Register exit
        atexit.register(self.stop)

        return self

    def stop(self, close_session=None):
        """Stop the continuous shell process."""
        try:
            atexit.unregister(self.stop)
        except:
            pass
        try:
            if close_session is not None:
                self.close_session = close_session
            if self.close_session:
                send_msg(self, EndSession(self.session))
                recv_msg(self)
        except:
            pass
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except:
            pass
        try:
            self.socket.close()
        except:
            pass

        return self

    def close(self, close_session=None):
        """Close the continuous shell process."""
        try:
            self.stop(close_session=close_session)
        except:
            pass
