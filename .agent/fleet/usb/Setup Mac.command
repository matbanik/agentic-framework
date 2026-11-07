#!/bin/bash
# Double-click in Finder to set up this Mac. Terminal opens, asks for this account's password, and runs
# setup-unix.sh from this drive.
cd "$(dirname "$0")" || exit 1
sudo bash ./setup-unix.sh
status=$?
echo
read -n 1 -s -r -p "Press any key to close this window."
exit $status
