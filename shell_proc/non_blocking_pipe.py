import os
import platform


__all__ = ["is_windows", "is_linux", "set_non_blocking"]


# Windows non blocking handler variables
LPDWORD = PIPE_NOWAIT = msvcrt = windll = byref = POINTER = HANDLE = DWORD = BOOL = None


def is_windows():
    """Return if this platform is windows."""
    return platform.system() == 'Windows'


def is_linux():
    """Return if this platform is linux."""
    return not is_windows()


def init_windows():
    global LPDWORD, PIPE_NOWAIT, msvcrt, windll, byref, POINTER, HANDLE, DWORD, BOOL

    if LPDWORD is None:
        import msvcrt
        from ctypes import windll, byref, POINTER
        from ctypes.wintypes import HANDLE, DWORD, BOOL

        LPDWORD = POINTER(DWORD)
        PIPE_NOWAIT = DWORD(0x00000001)


def set_non_blocking(pipe):
    global LPDWORD, PIPE_NOWAIT, msvcrt, windll, byref, POINTER, HANDLE, DWORD, BOOL

    try:
        return os.set_blocking(pipe.fileno(), False)
    except AttributeError:
        if is_windows():
            init_windows()

            # https://stackoverflow.com/a/34504971/11106801
            SetNamedPipeHandleState = windll.kernel32.SetNamedPipeHandleState
            SetNamedPipeHandleState.argtypes = [HANDLE, LPDWORD, LPDWORD, LPDWORD]
            SetNamedPipeHandleState.restype = BOOL

            handle = msvcrt.get_osfhandle(pipe.fileno())
            res = windll.kernel32.SetNamedPipeHandleState(handle, byref(PIPE_NOWAIT), None, None)
            return res != 0
        else:
            return False
