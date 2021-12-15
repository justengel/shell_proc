import sys
import os
import argparse
from shell_proc import Shell


P = argparse.ArgumentParser('Run shell commands')
P.add_argument('tasks', nargs='*', type=str, help='Shell tasks to run.')
P.add_argument('--stdout', type=str, default=sys.stdout, help='Filename to write stdout to')
P.add_argument('--stderr', type=str, default=sys.stderr, help='Filename to write stderr to')
P.add_argument('--blocking', type=bool, default=True)

ARGS, REMAIN = P.parse_known_args(sys.argv[1:])

OUT = ARGS.stdout
if isinstance(OUT, str):
    OUT = open(OUT, 'w')
ERR = ARGS.stderr
if isinstance(ERR, str):
    ERR = open(ERR, 'w')

with Shell(*ARGS.tasks, stdout=OUT, stderr=ERR, blocking=ARGS.blocking) as sh:
    while sh.is_proc_running():
        sh(input('> '))
