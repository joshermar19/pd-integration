# Still not sure what all this will do exactly. For now, it should
# define process name and integration key used by the script

export PROC_NAME=""
export INT_KEY=""

source ./env/bin/activate
python3 check_for_proc.py
