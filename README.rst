==========
Shell Proc
==========

Install
=======

.. code-block:: bash

    pip install shell_proc


Run
===

Run a series of commands with results.

.. code-block:: python

    from shell_proc import Shell

    with Shell() as sh:
        sh('cd ..')
        if sh.is_windows():
            cmd = sh('dir')
        else:
            cmd = sh('ls')

        # cmd (Command) Attributes: cmd, exit_code, stdout, stderr
        print(cmd.stdout)


Run a series of terminal commands.

.. code-block:: python

    import sys
    from shell_proc import Shell

    with Shell(stdout=sys.stdout, stderr=sys.stderr) as sh:
        sh.run('mkdir storage')
        sh('cd storage')  # Same as sh.run()
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
        sh('pip install requests')
        sh('pip list')

    table = '|{:_<20}|{:_<20}|{:_<20}|{:_<50}|'
    print(table.format('', '', '', '').replace('|', '_'))
    print(table.format("Exit Code", "Has Error", "Has Ouput", "Command").replace('_', ' '))
    print(table.format('', '', '', ''))
    for cmd in sh.history:
        print(table.format(cmd.exit_code, cmd.has_error(), cmd.has_output(), cmd.cmd).replace('_', ' '))
    print(table.format('', '', '', '').replace('|', '_'))


Run without blocking every command

.. code-block:: python

    import sys
    import time
    from shell_proc import Shell

    with Shell(stdout=sys.stdout, stderr=sys.stderr, blocking=False, wait_on_exit=True) as sh:
        sh.run('mkdir storage')
        sh('cd storage')  # Same as sh.run()
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
        sh('pip install requests')
        sh('pip list')
        print('---------- At exit (shows non-blocking until exit) ----------')

    time.sleep(1)
    print('1 Second has passed', 'Running:', sh.current_command)
    time.sleep(1)
    print('2 Seconds have passed', 'Running:', sh.current_command)
    time.sleep(1)
    print('3 Seconds have passed', 'Running:', sh.current_command)

    sh.wait()  # Wait for all commands to finish


Manually call commands and check results.

.. code-block:: python

    import io
    import sys
    from shell_proc import Shell

    # Initialize and run tasks
    sh = Shell('mkdir storage',
               'cd storage',
               'echo Hello World! > hello.txt',
               stderr=io.StringIO())

    # Manually run tasks
    if sh.is_windows():
        sh('python -m venv ./winvenv')
        sh('call ./winvenv/Scripts/activate.bat')
    else:
        pwd = sh('pwd')
        sh('cd ~')
        sh('python3 -m venv ./lxvenv')
        sh('source ./lxvenv/bin/activate')
        sh('cd {}'.format(pwd.stdout))

    # Not exactly success. If True no output was printed to stderr. Stderr could also be warning like need to update pip
    results = sh.run('pip install requests')
    print("***** Successful install: ", results.exit_code == 0)
    if results.exit_code != 0:
        sh.stderr.seek(0)  # Move to start of io.StringIO()
        err = sh.stderr.read()  # All text collected into stderr from subprocess stderr
        print(err, file=sys.stderr)
        # sh.print_stderr()  # Also available

    sh.stdout = io.StringIO()  # Start saving output for new tasks
    results = sh('pip list')
    print('***** Output Printed\n', results.stdout)

    sh('pip -V')
    print('pip -V =>', sh.last_command.stdout)

    print('All collected stdout')
    sh.stdout.seek(0)  # Move to start of io.StringIO()
    print(sh.stdout.read(), end='', flush=True)  # Print all read data

    # Should close when finished to stop threads from reading stdout and stderr subprocess.PIPE
    # (will close automatically eventually)
    sh.close()

io.StringIO() Help
==================

Below are several functions to read data from stdout and io.StringIO()

.. code-block:: python

    def read_io(fp):
        """Return all of the human readable text from the io object."""
        try:
            if fp.seekable():
                fp.seek(0)
            out = fp.read()
            if not isinstance(out, str):
                out = out.decode('utf-8')
            return out
        except:
            return ''

    def clear_io(fp):
        """Try to clear the stdout"""
        text = read_io(fp)
        try:
            fp.truncate(0)
        except:
            pass
        return text

    def print_io(fp, end='\n', file=None, flush=True):
        """Print and clear the collected io."""
        if file is None:
            file = sys.stdout
        print(clear_io(fp), file=file, flush=True)
