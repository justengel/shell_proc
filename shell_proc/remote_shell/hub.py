import os
import socket
import threading

from collections import namedtuple
from queue import Queue, Empty

from .msgs import decode, send_msg, recv_msg, AckNack, Authenticate, AuthenticationFailed, AuthenticationRequired,\
    RegisterNode, StartSession, EndSession, RemoteCommandRequest, RemoteCommandReply


__all__ = ['save_server_defaults', 'get_server_defaults', 'Node', 'Client', 'NodeCommand', 'RemoteHub']


# ===== Environment Variables =====
ENVIRON_ADDRESS_NAME = 'REMOTE_HUB_ADDRESS'
ENVIRON_PORT_NAME = 'REMOTE_HUB_PORT'


def save_server_defaults(address, port):
    """Return the server defaults for the given environment variables."""
    os.environ[ENVIRON_ADDRESS_NAME] = str(address)
    os.environ[ENVIRON_PORT_NAME] = str(port)


def get_server_defaults():
    """Return the server defaults for the given environment variables."""
    default_address = os.environ.get(ENVIRON_ADDRESS_NAME, socket.gethostbyname(socket.gethostname()))
    default_port = int(os.environ.get(ENVIRON_PORT_NAME, '54333'))
    return default_address, default_port
# ===== END Environment Variables =====


Node = namedtuple('Node', 'name queue socket address port')
Client = namedtuple('Client', 'name socket address port')
NodeCommand = namedtuple('NodeCommand', 'client msg')


def close_socket(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except:
        pass
    try:
        sock.close()
    except:
        pass


class RemoteHub(object):
    """Hub to direct tasks and traffic."""
    def __init__(self, address=None, port=None):
        self._node_lock = threading.RLock()
        self.nodes = {}
        self.address = '0.0.0.0'
        self.port = 54333
        self.socket = None

        super().__init__()

        default_address, default_port = get_server_defaults()
        self.address = address or default_address
        self.port = port or default_port

    def is_connected(self):
        """Return if is connected."""
        return self.socket is not None

    def connect(self, address=None, port=None):
        """Connect the socket to start accepting connections."""
        if address is not None:
            self.address = str(address)
        if port is not None:
            self.port = int(port)

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('0.0.0.0', self.port))
        self.socket.listen(5)  # Queue 5 connections. This is NOT the maximum number of connections.
        return self

    def disconnect(self):
        """Disconnect the socket and stop running."""
        close_socket(self.socket)

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

    def accept(self):
        """Accept a socket and return (socket, (addr, port))."""
        if not self.is_connected():
            self.connect()
        return self.socket.accept()

    def run_server(self):
        """Run the event loop."""
        if not self.is_connected():
            self.connect()
        while True:
            (sock, (addr, port)) = self.socket.accept()
            msg = recv_msg(sock)
            if isinstance(msg, RegisterNode):
                self.register_node(msg.name, sock, addr, port)
            elif isinstance(msg, StartSession):
                self.register_client(msg.name, sock, addr, port)

    run = run_server

    # ===== Node =====
    def get_node(self, name):
        """Return the node for the given name or None."""
        try:  # Try to get the name if message or other object is given.
            name = name.name
        except:
            pass

        with self._node_lock:
            try:
                return self.nodes[name]
            except:
                return None

    def set_node(self, node):
        """Set the node."""
        with self._node_lock:
            self.nodes[node.name] = node

    def del_node(self, name):
        """Delete the node."""
        try:  # Try to get the name if message or other object is given.
            name = name.name
        except:
            pass

        with self._node_lock:
            try:
                close_socket(self.nodes[name].socket)
            except:
                pass
            try:
                del self.nodes[name]
            except:
                pass

    def register_node(self, name, sock, address, port):
        """Register a node to communicate with."""
        node = Node(name, Queue(), sock, address, port)
        send_msg(node, AckNack(True))

        # Run a thread to handle the node.
        th = threading.Thread(target=self.node_redirect_handler, args=(node,))
        th.daemon = True
        th.start()

    def register_client(self, name, sock, address, port):
        """Register the Client and start the thread handler to work with the Client."""
        client = Client(name, sock, address, port)
        send_msg(client, AckNack(True))

        # Run a thread to handle the client.
        th = threading.Thread(target=self.client_handler, args=(client,))
        th.daemon = True
        th.start()

    def node_redirect_handler(self, node):
        """Run the node handler."""
        # Add the node!
        self.set_node(node)

        while True:
            try:
                client, msg = node.queue.get()
            except:
                client = msg = None
                break

            try:
                # Get command and send to node
                send_msg(node, msg)

                # Get response from node and
                msg = recv_msg(node)
                send_msg(client, msg)
            except:
                send_msg(client, AckNack(False))
                break

        # Remove the node!
        self.del_node(node)

    def client_handler(self, client):
        """Run the client handler."""
        while True:
            # Get command and send to node
            try:
                msg = recv_msg(client)
                if isinstance(msg, EndSession):
                    send_msg(client, AckNack(True))
                    break
                elif hasattr(msg, 'node'):
                    node = self.get_node(msg.node)
                    node.queue.put(NodeCommand(client, msg))
                else:
                    send_msg(client, AckNack(False))
            except:
                break

        try:
            close_socket(client.socket)
        except:
            pass
