==========
Shell Proc
==========

Install
=======

.. code-block:: bash

    pip install shell_proc


3.0.0 Changes
-------------
Major changes! Too many differences between linux, windows cmd, and windows powershell.

* I separated everything into separate classes.
    * Shell is the default for the OS.
    * Can specify BashShell (LinuxShell), WindowsPowerShell, and WindowsCmdShell.
* Changed parallel function in an attempt to use background processes.
    * Removed ParallelShell class
* Added Command.raw_stdout and Command.raw_stderr.
* Added Shell.is_windows_cmd and Shell.is_powershell.
* Each shell has specific quote escape functions.
    * This can be a giant pain and could be improved with regex
* Added show_all_output and show_commands for how the output is displayed.
* Added extra and end arguments to the run function to add more control to the commands.

2.0.0 Changes
-------------

This library has recently been updated to support commands with stdin prompts.
I noticed `git` and `ssh` would occasionally request pompt input from the user for authorization.
The old approach would get the exit code by sending an echo to stdin.
This would give the echo command as a user prompt.
To support this a lot of things had to change.
Windows users will notice some changes.

* I changed how the echo results works and am using `";"` instead of a second command passed into stdin.
* I also changed the pipes to non-blocking allowing input prompts to be read.
    * Before the pipe reading waited on a newline.
* Unfortunately, ";" did not really work with windows cmd.
    * Windows operations were changed to use powershell.
    * Powershell `$?` gives `"True"` or `"False"`, so it does not give a proper exit_code.
    * Old cmd is still supported if you pass `use_old_cmd=True` into the Shell. Not guaranteed to work.
* Added `input` which will only pass values into stdin without expecting a command to finish.

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
            sh('./winvenv/Scripts/activate.bat')
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

Run Python
==========

Added support to call python in a subprocess

.. code-block:: python

    from shell_proc import Shell

    with Shell(python_call='python3') as sh:
        sh.python('-c',
                  'import os',
                  'print("My PID:", os.getpid())')


Run Parallel
============

Added support to run parallel subprocesses

.. code-block:: python

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


Use Pipe
========

The pipe operator can be used with Command objects to take a completed command stdout and submit the text into a
new commands stdin.

.. code-block:: python

    import sys
    from shell_proc import Shell, ShellExit, shell_args

    with Shell(stdout=sys.stdout, stderr=sys.stderr) as sh:
        # One step
        results = sh('dir') | 'find "run"'  # Hard to tell where find output starts

        # Two Steps
        cmd = sh('dir')
        results = sh('find "run"', pipe_text=cmd.stdout)


Input Prompts
=============

As of version 2.0.0, Shell can work with input prompts.
I noticed `git` and `ssh` would occasionally request pompt input from the user for authorization.
I wanted to support this use case.

Input prompt code

.. code-block:: python

    # prompt_me.py
    print("Greetings!")
    name = input("Hello, who am I talking to? ")
    print(f"It\'s nice to meet you {name!r}")


Shell code

.. code-block:: python

    # run shell
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


Output. Note, "Jane Doe" was entered in as input.

.. code-block:: text

    Give user input when prompted
    Greetings!
    Hello, who am I talking to? Jane Doe
    It's nice to meet you 'Jane Doe'
    Greetings!
    Hello, who am I talking to? It's nice to meet you 'John Doe'
    Exited successfully!
