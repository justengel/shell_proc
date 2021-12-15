

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
            sh('call ./winvenv/Scripts/activate.bat')
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
        p = sh.parallel(*(python_args('-c',
                                      'import os',
                                      'import time',
                                      "print('My ID:', {id}, 'My PID:', os.getpid(), time.time())".format(id=i),
                                      python_call='python3') for i in range(10)))
        sh.wait()  # or p.wait()
        print('finished parallel')
        time.sleep(1)

        tasks = []
        for i in range(10):
            if i == 3:
                t = python_args('-c',
                                'import os',
                                'import time',
                                'time.sleep(1)',
                                "print('My ID:', {id}, 'My PID:', os.getpid(), time.time())".format(id=i),
                                python_call='python3')
            else:
                t = python_args('-c',
                                'import os',
                                'import time',
                                "print('My ID:', {id}, 'My PID:', os.getpid(), time.time())".format(id=i),
                                python_call='python3')
            tasks.append(t)
        p = sh.parallel(*tasks)
        p.wait()
        print('finished parallel')
        time.sleep(1)

        with sh.parallel() as p:
            # python3 from shell
            for i in range(10):
                if i == 3:
                    p.python('-c',
                             'import os',
                             'import time',
                             'time.sleep(1)',
                             "print('My ID:', {id}, 'My PID:', os.getpid(), time.time())".format(id=i))
                else:
                    p.python('-c',
                             'import os',
                             'import time',
                             "print('My ID:', {id}, 'My PID:', os.getpid(), time.time())".format(id=i))
            # p.wait() on exit context
        print('finished parallel')


if __name__ == '__main__':
    run_simple_result()
    run_context_manager()
    run_non_blocking()
    run_manual()
    run_python()
    run_parallel()
