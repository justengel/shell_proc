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


def run_command_pipe():
    import sys
    from shell_proc import Shell, ShellExit, shell_args

    with Shell(stdout=sys.stdout, stderr=sys.stderr) as sh:
        # One step
        results = sh('dir') | 'find "run"'  # Hard to tell where find output starts
        assert 'run_subprocess.py' in results.stdout

        # Two Steps
        cmd = sh('dir')
        print('\nRUN PIPE')
        results = cmd | 'find "run"'
        assert 'run_subprocess.py' in results.stdout


if __name__ == '__main__':
    run_subprocess()
    run_shell()
    run_command_pipe()

