
def test_simple():
    import sys
    from shell_proc import Shell

    with Shell(stdout=sys.stdout, stderr=sys.stderr) as sh:
        print('\n========== Begin Shell ==========')
        # Create a directory storage and make a virtual environment in storage with the requests library installed
        sh('mkdir storage')
        sh('cd storage')
        sh('python -m venv ./myvenv')
        if sh.is_windows():
            sh('call .\\myvenv\\Scripts\\activate.bat')
        else:
            sh('source ./myvenv/bin/activate')
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
        print('mkdir storage', '>>', sh.has_print_err())  # Directory may exist
        sh('cd storage')
        print('cd storage', '>>', sh.has_print_err())
        sh('python -m venv ./myvenv')
        print('python -m venv ./myvenv', '>>', sh.has_print_err())
        if sh.is_windows():
            sh('call .\\myvenv\\Scripts\\activate.bat')
        else:
            sh('source ./myvenv/bin/activate')
        sh('pip -V')
        print('pip -V', '>>', sh.has_print_err())
        sh('pip install requests')
        print('pip install requests', '>>', sh.has_print_err())  # Possible stderr message to update pip
        sh('pip list')
        print('pip list', '>>', sh.has_print_err())  # Possible stderr message to update pip
    print('========== End Shell ==========')


def test_has_out():
    import io
    from shell_proc import Shell

    with Shell(stdout=io.StringIO()) as sh:
        print('\n========== Begin Shell has_out ==========')
        # Create a directory storage and make a virtual environment in storage with the requests library installed
        sh('mkdir storage')
        print('mkdir storage', '>>', sh.has_print_out())
        sh('cd storage')
        print('cd storage', '>>', sh.has_print_out())
        sh('python -m venv ./myvenv')
        print('python -m venv ./myvenv', '>>', sh.has_print_out())
        if sh.is_windows():
            sh('call .\\myvenv\\Scripts\\activate.bat')
        else:
            sh('source ./myvenv/bin/activate')
        sh('pip -V')
        print('pip -V', '>>', sh.has_print_out())
        sh('pip install requests')
        print('pip install requests', '>>', sh.has_print_out())
        sh('pip list')
        print('pip list', '>>', sh.has_print_out())

        out = sh.get_stdout()  # All text saved to stdout from the subprocess terminal commands
        assert out != ''
    print('========== End Shell ==========')


if __name__ == '__main__':
    test_simple()
    # test_has_err()
    # test_has_out()
