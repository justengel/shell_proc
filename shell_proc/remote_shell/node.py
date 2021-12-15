import io
import time
import socket
import threading

from shell_proc.shell import Shell
from .msgs import send_msg, recv_msg, AckNack, \
    Authenticate, AuthenticationSuccess, AuthenticationRequired, AuthenticationFailed, \
    RegisterNode, RemoteCommandRequest, RemoteCommandReply
from .hub import save_server_defaults, get_server_defaults, Node, Client, NodeCommand
from .auth import get_hashed_password, check_password


__all__ = ['RemoteNode']


class RemoteNode(object):
    def __init__(self, name, address=None, port=None, authkey=None, auth_timeout=86400):
        self._session_lock = threading.RLock()
        self.sessions = {}
        self.address = '0.0.0.0'
        self.port = 54333
        self.socket = None
        self.name = str(name)
        self._auth = None
        self.auth_timeout = auth_timeout

        super().__init__()

        default_address, default_port = get_server_defaults()
        self.address = address or default_address
        self.port = port or default_port

        if authkey is not None:
            self.set_password(authkey)

    def has_auth(self):
        return self._auth is not None

    def set_password(self, auth):
        if auth is not None:
            auth = get_hashed_password(auth)
        self._auth = auth

    def is_connected(self):
        """Return if is connected."""
        return self.socket is not None

    def connect(self, address=None, port=None):
        """Connect the socket to start accepting connections."""
        if address is not None:
            self.address = str(address)
        if port is not None:
            self.port = int(port)

        # Connect the socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.address, self.port))

        # Register this node
        send_msg(self, RegisterNode(self.name))
        ack = recv_msg(self)
        if not isinstance(ack, AckNack) or not ack.ack:
            raise RuntimeError('Could not connect to the hub properly!')

        return self

    def disconnect(self):
        """Disconnect the socket and stop running."""
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except:
            pass
        try:
            self.socket.close()
        except:
            pass

    def __enter__(self):
        """Enter statement for use of "with" connects the connection."""
        if not self.is_connected():
            self.connect()
        return self

    def __exit__(self, ttype, value, traceback):
        """Exit statement for use of the "with" statement. Properly closes the connection."""
        self.disconnect()

        if ttype is not None:
            return False
        return True

    def run_node(self):
        if not self.is_connected():
            self.connect()

        auth = {}

        while True:
            msg = recv_msg(self)
            if isinstance(msg, Authenticate) and self.has_auth():
                if check_password(msg.pwd, self._auth):
                    auth[msg.uuid] = time.time()
                    send_msg(self, AuthenticationSuccess())
                else:
                    send_msg(self, AuthenticationFailed())

            elif isinstance(msg, RemoteCommandRequest):
                # Check authentication
                if self.has_auth():
                    # Check timeout
                    if time.time() - auth.get(msg.uuid, 0) > self.auth_timeout:
                        send_msg(self, AuthenticationRequired())
                        continue

                # Run the shell command
                session = self.get_shell_session(msg.session, msg.new_shell)
                results = session.run(msg.cmd)

                # Reply to the command
                reply = RemoteCommandReply(self.name, msg.session, **results.as_dict())
                send_msg(self, reply)
            else:
                send_msg(self, AckNack(False))

    run = run_node

    def get_shell_session(self, session_name, new_shell=False):
        """Return the session."""
        with self._session_lock:
            try:
                sh = self.sessions[session_name]
            except:
                sh = None
                new_shell = True

            if new_shell:
                try:
                    sh.close()
                except:
                    pass
                sh = Shell(stdout=io.StringIO(), stderr=io.StringIO())
                sh.start()
                self.sessions[session_name] = sh
        return sh
