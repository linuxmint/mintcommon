#!/usr/bin/python3
# This takes optional command-line parameters:  
#   -p, --prompt   A line of text to use for a prompt.  
#   -i, --icon     Path & filename of an icon.  (Or just an icon name 
#                  recognized by the OS.)  
# Generic defaults are used for any missing command-line parameters.  

import os
import gettext
import argparse

gettext.install('mint-common', '/usr/share/linuxmint/locale')

parser = argparse.ArgumentParser()
parser.add_argument('-p', '--prompt', default=_('Please enter your password'))
parser.add_argument('-i', '--icon', default='/usr/share/linuxmint/logo.png')
args = parser.parse_args()

if os.path.exists('/usr/bin/pkexec'):
    launcher = 'pkexec'
elif os.path.exists('/usr/bin/gksu'):
    launcher = 'gksu --message "<b>{0}</b>"'.format(args.prompt)
elif os.path.exists('/usr/bin/kdesudo'):
    launcher = 'kdesudo -i {0} -d --comment "<b>{1}</b>"'.format(
                 args.icon, args.prompt)

print (launcher)
