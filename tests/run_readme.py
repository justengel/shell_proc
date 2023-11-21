

def run_simple_result():
    from shell_proc import Shell

    with Shell() as sh:
        sh('cd ..')
        if sh.is_windows():
            cmd = sh('dir')
        else:
            cmd = sh('ls')

        # cmd (Command) Attributes: cmd, exit_code, stdout, stderr
        print(cmd.stdout)


def run_context_manager():
    import sys
    from shell_proc import Shell

    with Shell(stdout=sys.stdout, stderr=sys.stderr) as sh:
        sh.run('mkdir storage')
        sh('cd storage')  # Same as sh.run()
        sh('echo Hello World! > hello.txt')

        if sh.is_windows():
            sh('python -m venv ./winvenv')
            sh('./winvenv/Scripts/activate.bat')
        else:
            pwd = sh('pwd')
            sh('cd ~')
            sh('python3 -m venv ./lxvenv')
            sh('source ./lxvenv/bin/activate')
            sh('cd {}'.format(pwd.stdout.strip()))
        sh('pip install requests')
        sh('pip list')

    table = '|{:_<20}|{:_<20}|{:_<20}|{:_<50}|'
    print(table.format('', '', '', '').replace('|', '_'))
    print(table.format("Exit Code", "Has Error", "Has Ouput", "Command").replace('_', ' '))
    print(table.format('', '', '', ''))
    for cmd in sh.history:
        print(table.format(cmd.exit_code, cmd.has_error(), cmd.has_output(), cmd.cmd).replace('_', ' '))
        x = 1
    print(table.format('', '', '', '').replace('|', '_'))


def run_non_blocking():
    import sys
    import time
    from shell_proc import Shell

    with Shell(stdout=sys.stdout, stderr=sys.stderr, blocking=False, wait_on_exit=True) as sh:
        sh.run('mkdir storage')
        sh('cd storage')  # Same as sh.run()
        sh('echo Hello World! > hello.txt')

        if sh.is_windows():
            sh('python -m venv ./winvenv')
            sh('./winvenv/Scripts/activate.bat')
        else:
            pwd = sh('pwd')
            sh('cd ~')
            sh('python3 -m venv ./lxvenv')
            sh('source ./lxvenv/bin/activate')
            sh('cd {}'.format(pwd.stdout))
        sh('pip install requests')
        sh('pip list')
        print('---------- At exit (shows non-blocking until exit) ----------')

    table = '|{:_<20}|{:_<20}|{:_<20}|{:_<50}|'
    print(table.format('', '', '', '').replace('|', '_'))
    print(table.format("Exit Code", "Has Error", "Has Ouput", "Command").replace('_', ' '))
    print(table.format('', '', '', ''))
    for cmd in sh.history:
        print(table.format(cmd.exit_code, cmd.has_error(), cmd.has_output(), cmd.cmd).replace('_', ' '))
    print(table.format('', '', '', '').replace('|', '_'))


def run_manual():
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
        sh('./winvenv/Scripts/activate.bat')
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
    print('pip -V =>', sh.last_command.stdout)  # ... for some odd reason PyCharm terminal does not print this "\r\r\n"

    print('All collected stdout')
    sh.stdout.seek(0)  # Move to start of io.StringIO()
    print(sh.stdout.read(), end='', flush=True)  # Print all read data

    # Should close when finished to stop threads from reading stdout and stderr subprocess.PIPE
    # (will close automatically eventually)
    sh.close()


def run_python():
    import sys
    from shell_proc import Shell

    with Shell(stdout=sys.stdout, stderr=sys.stderr, python_call='python3') as sh:
        sh.python('-c',
                  'import os',
                  'print("My PID:", os.getpid())')


def run_parallel():
    import sys
    import time
    from shell_proc import Shell, python_args

    with Shell(stdout=sys.stdout, stderr=sys.stderr, python_call='python3') as sh:
        python_call = "python3"
        if sh.is_windows():
            python_call = "../venv/Scripts/python"
        cmd = sh.parallel(*(python_args('-c',
                                      'import os',
                                      'import time',
                                      "print('My ID:', {id}, 'My PID:', os.getpid(), time.time())".format(id=i),
                                      python_call=python_call) for i in range(10)))
        # Note: this will finish immediately and you should probably add an extra sleep like below
        sh.wait()
        print('finished parallel')
        time.sleep(1)

        background = {"end": "&", "extra": "; sleep 2"}
        python_call = "python3"
        if Shell.is_windows():
            python_call = "../venv/Scripts/python"
            if sh.is_powershell():
                background = {"extra": "; Start-Sleep -Seconds 2"}
            else:
                background = {"extra": "& waitfor /t 2 shellproc 2>Nul"}

        tasks = []
        for i in range(10):
            if i == 3:
                t = python_args('-c',
                                'import os',
                                'import time',
                                'time.sleep(1)',
                                "print('My ID:', {id}, 'My PID:', os.getpid(), time.time())".format(id=i),
                                python_call=python_call)
            else:
                t = python_args('-c',
                                'import os',
                                'import time',
                                "print('My ID:', {id}, 'My PID:', os.getpid(), time.time())".format(id=i),
                                python_call=python_call)
            tasks.append(t)
        cmd = sh.parallel(*tasks, **background)
        sh.wait()
        print('finished parallel')


def run_input():
    """Test reading prompts.

    I noticed that prompts do not show up in the output and freeze the shell. This is due to how python
    reads pipes. Python typically reads pipes by lines. Prompting the user for input usually does not end
    in a new line.

    I've updated the reading code to be non-blocking to solve this issue.
    """
    import sys
    from shell_proc import Shell

    with Shell(stdout=sys.stdout, stderr=sys.stderr) as sh:
        print("Give user input when prompted")
        # Need block=False or will wait forever for input it cannot receive
        sh("python prompt_me.py", block=False)

        # Get actual input from user
        value = input()

        # Send input to stdin (without expecting this to run as a command)
        # This will finish the first command sh(python prompt_me.py)
        sh.input(value)
        sh.wait()  # Manually wait for sh(python prompt_me.py) to finish

        # Test again
        sh("python prompt_me.py", block=False)
        sh.input("John Doe", wait=True)

    # Shell.__exit__ will wait for final exit_code from sh(python prompt_me.py)
    print("Exited successfully!")


if __name__ == '__main__':
    # run_simple_result()
    # run_context_manager()
    # run_non_blocking()
    # run_manual()
    # run_python()
    run_parallel()
    # run_input()
