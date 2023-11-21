SHOW_ALL = True
SHOW_CMDS = False


def run_parallel():
    print('Running run_parallel')
    import sys
    import time
    from shell_proc import Shell, python_args

    if Shell.is_linux():
        python_args.PYTHON = 'python3'
    else:
        python_args.PYTHON = r'..\venv\Scripts\python'

    with Shell(stdout=sys.stdout, stderr=sys.stderr, show_all_output=SHOW_ALL, show_commands=SHOW_CMDS) as sh:
        # This wont work with parallel due to a new shell being created.
        # See above python_args.PYTHON = ...
        # if sh.is_linux():
        #     sh('alias python=python3')

        sleep = "; sleep 2"
        if Shell.is_windows():
            if sh.is_powershell():
                sleep = "; Start-Sleep -Seconds 1"
            else:
                sleep = "& waitfor /t 1 shellproc 2>Nul"

        start = time.time()
        # sh.parallel(*(python_args('-c',
        #             'import os',
        #             'import time',
        #             'import random',
        #             'time.sleep(random.uniform(0.0, 2.9))',
        #             'print("My ID:", {id}, "My PID:", os.getpid(), time.time() - {s})'.format(s=start, id=i))
        #               for i in range(10)),
        #             extra=sleep)
        sh.parallel(*(python_args('-c',
                                  'print("My ID:", {id}, "My PID:", {s})'.format(s=start, id=i))
                      for i in range(10)),
                    extra=sleep)


def run_parallel_alt_quotes():
    print('Running run_parallel_context')
    import sys
    import time
    from shell_proc import Shell, WindowsPowerShell, python_args

    if Shell.is_linux():
        python_call = 'python3'
    else:
        python_call = r'..\venv\Scripts\python'

    with Shell(stdout=sys.stdout, stderr=sys.stderr, show_all_output=SHOW_ALL, show_commands=SHOW_CMDS, shell=True) as sh:
        background = {"end": "&"}
        if Shell.is_windows():
            if sh.is_powershell():
                background = {"extra": "; Start-Sleep -Seconds 1"}
            else:
                background = {"extra": "& waitfor /t 1 shellproc 2>Nul"}

        for i in range(10):
            if i == 3:
                sh.parallel(
                    sh.python_args(
                        '-c',
                        'import os',
                        'import time',
                        'time.sleep(1)',
                        "print('My ID:', {id}, 'My PID:', os.getpid(), time.time())".format(id=i),
                        python_call=python_call
                    ),
                    **background,
                    block=False,
                )
            else:
                sh.parallel(
                    sh.python_args(
                        '-c',
                        'import os',
                        'import time',
                        "print('My ID:', {id}, 'My PID:', os.getpid(), time.time())".format(id=i),
                        python_call=python_call
                    ),
                    **background,
                    block=False,
                )
        # p.wait() on exit context
    print('finished parallel')


if __name__ == '__main__':
    run_parallel()
    run_parallel_alt_quotes()
