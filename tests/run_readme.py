

def run_context_manager():
    import sys
    from shell_proc import Shell

    with Shell(stdout=sys.stdout, stderr=sys.stderr) as sh:
        sh.run('mkdir storage')
        sh('cd storage')  # Same as sh.run()
        sh('python -m venv ./myvenv')
        sh('source ./myvenv/bin/activate')
        sh('pip install requests')
        sh('pip list')


def run_manual():
    import io
    import sys
    from shell_proc import Shell

    # Initialize and run tasks
    sh = Shell('mkdir storage',
               'cd storage',
               'python -m venv ./myvenv',
               stderr=io.StringIO())

    # Manually run tasks
    if sh.is_windows():
        sh.run('call .\\myvenv\\Scripts\\activate.bat')
    else:
        sh.run('source ./myvenv/bin/activate')

    # Not exactly success. If True no output was printed to stderr. Stderr could also be warning like need to update pip
    success = sh.run('pip install requests')
    print("***** Successful install: ", success)
    if not success:
        err = sh.get_stderr()  # All text collected into stderr from subprocess stderr
        print(err, file=sys.stderr)
        # sh.print_stderr()  # Also available

    sh.stdout = io.StringIO()  # Start saving output for new tasks
    sh('pip list')
    print('***** Output Printed', sh.has_print_out())
    sh.stdout.seek(0)  # Move to start of io.StringIO()
    print(sh.stdout.read())  # Print all read data

    # Should close when finished to stop threads from reading stdout and stderr subprocess.PIPE
    # (will close automatically eventually)
    sh.close()


if __name__ == '__main__':
    # run_context_manager()
    run_manual()
