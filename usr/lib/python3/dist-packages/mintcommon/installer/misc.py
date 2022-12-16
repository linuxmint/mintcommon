#!/usr/bin/python3

import os
import time
import inspect
import threading
import sys

DEBUG_MODE = os.getenv("DEBUG", False)

# Used as a decorator to time functions
def print_timing(func):
    if not DEBUG_MODE:
        return func
    else:
        def wrapper(*arg):
            t1 = time.time()
            res = func(*arg)
            t2 = time.time()
            print('mint-common (DEBUG): %s took %0.3f ms' % (func.__qualname__, (t2 - t1) * 1000.0), flush=True, file=sys.stderr)
            return res
        return wrapper

def check_ml():
    if not DEBUG_MODE:
        return

    if threading.current_thread().name is not None:
        tid = threading.current_thread().name
    else:
        tid = str(threading.get_ident())
    fid = inspect.stack()[1][3]
    on_ml = threading.current_thread() == threading.main_thread()
    print("%s in thread: %s" % (fid, tid), flush=True, file=sys.stdout)

def debug(*args):
    if not DEBUG_MODE:
        return
    sanitized = [arg for arg in args if arg is not None]
    argstr = " ".join(sanitized)
    print("mint-common (DEBUG): %s" % argstr, file=sys.stderr, flush=True)

def warn(*args):
    sanitized = [arg for arg in args if arg is not None]
    argstr = " ".join(sanitized)
    print("mint-common (WARN): %s" % argstr, file=sys.stderr, flush=True)