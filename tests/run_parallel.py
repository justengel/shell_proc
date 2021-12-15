
def run_parallel():
    print('Running run_parallel')
    import sys
    import time
    from shell_proc import Shell, python_args

    if Shell.is_linux():
        python_args.PYTHON = 'python3'

    with Shell(stdout=sys.stdout, stderr=sys.stderr) as sh:
        # if sh.is_linux():  # This wont work with parallel due to a new shell being created.
        #     sh('alias python=python3')

        start = time.time()
        sh.parallel(*(python_args('-c',
                    'import os',
                    'import time',
                    'print("My ID:", {id}, "My PID:", os.getpid(), time.time() - {s})'.format(s=start, id=i))
                      for i in range(10)))


def run_parallel_context():
    print('Running run_parallel_context')
    import sys
    import time
    from shell_proc import Shell, python_args

    if Shell.is_linux():
        python_args.PYTHON = 'python3'

    with Shell(stdout=sys.stdout, stderr=sys.stderr, shell=True) as sh:
        # if sh.is_linux():  # This wont work with parallel due to a new shell being created.
        #     sh('alias python=python3')

        with sh.parallel() as p:
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
    run_parallel()
    run_parallel_context()
