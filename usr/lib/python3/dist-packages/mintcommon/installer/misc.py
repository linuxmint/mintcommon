#!/usr/bin/python3

import os
import time
import inspect
import threading
import sys
import html2text
import html2text.config

DEBUG_MODE = os.getenv("DEBUG", False)
DEBUG_QUERIES = os.getenv("DEBUG_QUERIES", False)

class dash_match_dummy():
    def sub(self, a, b):
        return b

# html2text wants to escape content (not markdown) dashes.
html2text.config.RE_MD_DASH_MATCHER = dash_match_dummy()
html_converter = html2text.HTML2Text()
# Asterisks are lame - appstream's converter used bullets.
html_converter.ul_item_mark = "•"
html_converter.wrap_list_items = True
html_converter.ignore_emphasis = True
html_converter.pad_tables = True

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
    print("%s in thread: %s" % (fid, tid), flush=True, file=sys.stderr)

def debug(*args):
    if not DEBUG_MODE:
        return
    sanitized = [str(arg) for arg in args if arg is not None]
    argstr = " ".join(sanitized)
    print("mint-common (DEBUG): %s" % argstr, file=sys.stderr, flush=True)

def debug_query(*args):
    if not DEBUG_QUERIES:
        return
    sanitized = [str(arg) for arg in args if arg is not None]
    argstr = " ".join(sanitized)
    print("mint-common (DEBUG): %s" % argstr, file=sys.stderr, flush=True)

def warn(*args):
    sanitized = [str(arg) for arg in args if arg is not None]
    argstr = " ".join(sanitized)
    print("mint-common (WARN): %s" % argstr, file=sys.stderr, flush=True)

def xml_markup_convert_to_text(markup):
    if markup is None:
        return ""
    try:
        return html_converter.handle(markup)
    except Exception as e:
        warn("Could not convert description to text: %s" % str(e))
        return markup
