from subprocess import Popen, PIPE
from shell_proc import Shell, ShellExit


def run_subprocess():
    # Create the continuous terminal process
    if Shell.is_windows():
        proc = Popen('cmd.exe', stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=False)
    else:
        proc = Popen('/bin/bash', stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=False)

    # Cannot communicate multiple times
    # out, err = proc.communicate(input=b'cd ./storage\n')
    # print(out, err, proc.poll())
    # out, err = proc.communicate(input=b'dir\n')
    # print(out, err)

    proc.stdin.write(b'cd ./storage\n')
    proc.stdin.flush()
    print(proc.poll(), proc.returncode)
    proc.stdin.write(b'dir\n')
    proc.stdin.flush()
    print(proc.poll(), proc.returncode)


def run_shell():
    import sys
    with Shell(stdout=sys.stdout, stderr=sys.stderr) as sh:
        sh('cd ./storage')
        sh('exit()')
        try:
            sh('dir')
            raise AssertionError('Shell already closed!')
        except (ShellExit):
            pass  # Should hit here


if __name__ == '__main__':
    run_subprocess()
    run_shell()

