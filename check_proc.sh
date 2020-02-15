#!/bin/sh

# For a more "set-it-and-forget-it" solution, simply set the vars here:
# export PROC_NAME=""
# export INT_KEY=""

# First lets make sure PROC_NAME and INT_KEY are set
if [ -z $PROC_NAME ] || [ -z $INT_KEY  ]; then
	echo "Please set vars PROC_NAME and INT_KEY"
	exit 1
fi

# Check for virtual environment and set up if necessary
if [ -f ./env/bin/activate ]; then
	echo 'found ./env/bin/activate'
	source ./env/bin/activate
	python3 check_proc.py

else
	echo 'Could not find ./env/bin/activate'
	echo 'Setting up virtual venv...'
	python3 -m venv env
	source ./env/bin/activate
	pip install -r requirements.txt
	python3 check_proc.py
fi
