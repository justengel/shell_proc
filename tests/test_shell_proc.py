
def test_simple():
    import sys
    from shell_proc import Shell

    with Shell(stdout=sys.stdout, stderr=sys.stderr) as sh:
        print('\n========== Begin Shell ==========')
        # Create a directory storage and make a virtual environment in storage with the requests library installed
        sh('mkdir storage')
        sh('cd storage')
        sh('echo Hello World! > hello.txt')

        if sh.is_windows():
            sh('python -m venv ./winvenv')
            sh('call ./winvenv/Scripts/activate.bat')
        else:
            pwd = sh('pwd')
            sh('cd ~')
            sh('python3 -m venv ./lxvenv')
            sh('source ./lxvenv/bin/activate')
            sh('cd {}'.format(pwd.stdout))
        sh('pip -V')
        sh('pip install requests')
        sh('pip list')
    print('========== End Shell ==========')


def test_has_err():
    from shell_proc import Shell

    with Shell() as sh:
        print('\n========== Begin Shell has_err ==========')
        # Create a directory storage and make a virtual environment in storage with the requests library installed
        sh('mkdir storage')
        print('mkdir storage', '>>', sh.last_command.stderr)  # Directory may exist
        sh('cd storage')
        print('cd storage', '>>', sh.last_command.stderr)
        sh('echo Hello World! > hello.txt')
        print('echo Hello World! > hello.txt', '>>', sh.last_command.stderr)

        if sh.is_windows():
            sh('python -m venv ./winvenv')
            print('python -m venv ./winvenv', '>>', sh.last_command.stderr)
            sh('call ./winvenv/Scripts/activate.bat')
        else:
            pwd = sh('pwd')
            sh('cd ~')
            sh('python3 -m venv ./lxvenv')
            print('python3 -m venv ./lxvenv', '>>', sh.last_command.stderr)
            sh('source ./lxvenv/bin/activate')
            sh('cd {}'.format(pwd.stdout))
        sh('pip -V')
        print('pip -V', '>>', sh.last_command.stderr)
        sh('pip install requests')
        print('pip install requests', '>>', sh.last_command.stderr)  # Possible stderr message to update pip
        sh('pip list')
        print('pip list', '>>', sh.last_command.stderr)  # Possible stderr message to update pip
    print('========== End Shell ==========')


def test_has_out():
    import io
    from shell_proc import Shell

    with Shell(stdout=io.StringIO()) as sh:
        print('\n========== Begin Shell has_out ==========')
        # Create a directory storage and make a virtual environment in storage with the requests library installed
        sh('mkdir storage')
        print('mkdir storage', '>>', sh.last_command.stdout)
        sh('cd storage')
        print('cd storage', '>>', sh.last_command.stdout)
        sh('echo Hello World! > hello.txt')
        print('echo Hello World! > hello.txt', '>>', sh.last_command.stdout)

        if sh.is_windows():
            sh('python -m venv ./winvenv')
            print('python -m venv ./winvenv', '>>', sh.last_command.stdout)
            sh('call ./winvenv/Scripts/activate.bat')
        else:
            pwd = sh('pwd')
            sh('cd ~')
            sh('python3 -m venv ./lxvenv')
            print('python3 -m venv ./lxvenv', '>>', sh.last_command.stdout)
            sh('source ./lxvenv/bin/activate')
            sh('cd {}'.format(pwd.stdout))
        sh('pip -V')
        print('pip -V', '>>', sh.last_command.stdout)
        sh('pip install requests')
        print('pip install requests', '>>', sh.last_command.stdout)
        sh('pip list')
        print('pip list', '>>', sh.last_command.stdout)

        sh.stdout.seek(0)
        out = sh.stdout.read()  # All text saved to stdout from the subprocess terminal commands
        assert out != ''
    print('========== End Shell ==========')


if __name__ == '__main__':
    test_simple()
    test_has_err()
    test_has_out()
