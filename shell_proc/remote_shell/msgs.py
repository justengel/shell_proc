import serial_json


__all__ = ['decode', 'encode', 'send_msg', 'recv_msg', 'AckNack',
           'RegisterNode', 'StartSession', 'EndSession',
           'Authenticate', 'AuthenticationSuccess', 'AuthenticationRequired', 'AuthenticationFailed',
           'RemoteCommandRequest', 'RemoteCommandReply']


def decode(msg):
    """Decode a message from bytes."""
    if isinstance(msg, bytes):
        msg = msg.decode('latin1')
    return serial_json.loads(msg)


def encode(msg):
    """Encode a message into bytes."""
    if not isinstance(msg, bytes):
        msg = serial_json.dumps(msg).encode('latin1')
    return msg


def send_msg(obj, msg):
    """Send a message to an object that has a socket, address, and port."""
    obj.socket.sendto(encode(msg), (obj.address, obj.port))


def recv_msg(obj):
    """Receive a message from an object that has a socket."""
    try:
        obj = obj.socket
    except AttributeError:
        pass
    msg, sender = obj.recvfrom(8192)
    return decode(msg)


class Message(object):
    def __init__(self, **kwargs):
        self.msg_attrs = list(kwargs.keys())
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __getstate__(self):
        return {name: getattr(self, name, None) for name in self.msg_attrs}

    def __setstate__(self, state):
        for k, v in state.items():
            setattr(self, k, v)


@serial_json.register
class AckNack(Message):
    def __init__(self, ack=False):
        super().__init__(ack=ack)


@serial_json.register
class RegisterNode(Message):
    def __init__(self, name=''):
        super().__init__(name=name)


@serial_json.register
class StartSession(Message):
    def __init__(self, name=''):
        super().__init__(name=name)


@serial_json.register
class EndSession(Message):
    def __init__(self, name=''):
        super().__init__(name=name)


@serial_json.register
class Authenticate(Message):
    def __init__(self, node='', uuid='', pwd=''):
        super().__init__(node=str(node), uuid=uuid, pwd=pwd)


@serial_json.register
class AuthenticationSuccess(Message):
    pass


@serial_json.register
class AuthenticationRequired(Message):
    pass


@serial_json.register
class AuthenticationFailed(Message):
    pass


@serial_json.register
class RemoteCommandRequest(Message):
    """Run the remote command.

    Args:
        node (str): Name of the node
        session (str)['']: Session name to keep track of
        uuid (str)['']: Special unique process id indicating who is communicating.
        cmd (str): Command to run
        new_shell (bool)[False]: If True a new shell should be created for this session.
    """
    def __init__(self, node='', session='', uuid='', cmd='', new_shell=False):
        super().__init__(node=str(node), session=session, uuid=uuid, cmd=str(cmd), new_shell=bool(new_shell))


@serial_json.register
class RemoteCommandReply(Message):
    """Run the remote command.

    Args:
        node (str): Name of the node
        stdout (str): Text from stdout.
        stderr (str): Text from stderr.
    """
    DEFAULT_EXIT_CODE = -1

    def __init__(self, node='', session='', cmd='', exit_code=None, stdout='', stderr='', **kwargs):
        if exit_code is None:
            exit_code = self.DEFAULT_EXIT_CODE
        super().__init__(node=str(node), session=session,
                         cmd=cmd, stdout=str(stdout), stderr=str(stderr), exit_code=exit_code, **kwargs)

    # ===== shell_proc.shell.Command methods =====
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
