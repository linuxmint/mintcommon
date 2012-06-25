#!/bin/bash

if [ -n "$KDE_FULL_SESSION" ]; then
	desktop_environnment=KDE
	else
		if [  -n "$XDG_CURRENT_DESKTOP" ]; then
			# Works for cinnamon as well
			desktop_environnment=GNOME
			else
			if [ -n "$MATE_DESKTOP_SESSION_ID" ]; then
				desktop_environnment=MATE
				fi
			fi			

	fi


case $desktop_environnment in
KDE)
	echo KDE
	;;
GNOME|MATE)
	echo GNOME
	;;
*)
	echo GNOME
	;;

esac
