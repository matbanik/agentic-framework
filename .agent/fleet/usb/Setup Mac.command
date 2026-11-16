#!/bin/bash
# Double-click in Finder to set up this Mac. Terminal opens and runs setup-unix.sh from this drive, which asks for
# this account's password itself when it needs administrator rights.
cd "$(dirname "$0")" || exit 1
bash ./setup-unix.sh
status=$?
echo
read -n 1 -s -r -p "Press any key to close this window."
exit $status
