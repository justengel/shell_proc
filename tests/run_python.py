
def run_python_file():
    import sys
    from shell_proc import Shell, python_args

    if Shell.is_linux():
        python_args.PYTHON = 'python3'

    with Shell(stdout=sys.stdout, stderr=sys.stderr) as sh:
        if sh.is_linux():
            sh('alias python=python3')

        sh.python('hello_world.py')


def run_module():
    import sys
    from shell_proc import Shell, python_args

    if Shell.is_linux():
        python_args.PYTHON = 'python3'

    with Shell(stdout=sys.stdout, stderr=sys.stderr) as sh:
        if sh.is_linux():
            sh('alias python=python3')

        sh.python('-m', 'pip', '-V')


def run_command():
    import sys
    from shell_proc import Shell, python_args

    if Shell.is_linux():
        python_args.PYTHON = 'python3'

    with Shell(stdout=sys.stdout, stderr=sys.stderr, show_all_output=True) as sh:
        if sh.is_linux():
            sh('alias python=python3')

        sh.python('-c',
                  'import os',
                  'print("My PID:", os.getpid())')

        # Try different quotes
        sh.python('-c',
                  'import os',
                  "print('My PID:', os.getpid())")


def run_interactive():
    """WIP: I dont know how to get this to work with a subshell."""
    import sys
    import time
    from shell_proc import Shell, python_args

    if Shell.is_linux():
        python_args.PYTHON = 'python3'

    with Shell(stdout=sys.stdout, stderr=sys.stderr, shell=True) as sh:
        if sh.is_linux():
            sh('alias python=python3')

        sh.end_command = ''  # Terminator to help determine when a task finished
        sh.set_blocking(False)  # Must have non blocking commands
        sh.python()
        time.sleep(0.5)
        while sh.is_proc_running():
            sh(input('>>> '))


if __name__ == '__main__':
    run_python_file()
    run_module()
    run_command()
    # run_interactive()
