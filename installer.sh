#!/bin/bash
##setup command=wget -q "--no-check-certificate" https://raw.githubusercontent.com/ciefp/CiefpChannelHistory/main/installer.sh -O - | /bin/sh

######### Only This 2 lines to edit with new version ######
version='1.0'
changelog='\n- Initial release\n- Channel watch history tracking with SQLite\n- FHD EPG Info screen with TMDB/OMDb enrichment\n- Statistics: Top 20, By satellite, By encryption, By hour, By weekday\n- Settings with retention, API keys, parental filter\n- Parental lock (blacklist) filter for adult channels\n- Periodic session update (no data loss on restart)\n- FHD 1920x1080 skin\n- Python 3 compatible'
##############################################################

# Check if we should skip restart (for batch installations)
SKIP_REBOOT="${SKIP_REBOOT:-0}"

TMPPATH=/tmp/CiefpChannelHistory

if [ ! -d /usr/lib64 ]; then
	PLUGINPATH=/usr/lib/enigma2/python/Plugins/Extensions/CiefpChannelHistory
else
	PLUGINPATH=/usr/lib64/enigma2/python/Plugins/Extensions/CiefpChannelHistory
fi

# check depends packages
if [ -f /var/lib/dpkg/status ]; then
   STATUS=/var/lib/dpkg/status
   OSTYPE=DreamOs
else
   STATUS=/var/lib/opkg/status
   OSTYPE=Dream
fi
echo ""
if python --version 2>&1 | grep -q '^Python 3\.'; then
	echo "You have Python3 image"
	PYTHON=PY3
	Packagesix=python3-six
	Packagerequests=python3-requests
	Packagesqlite=python3-sqlite3
else
	echo "You have Python2 image"
	PYTHON=PY2
	Packagerequests=python-requests
	Packagesqlite=python-sqlite3
fi

# Install python3-six (only for PY3)
if [ $PYTHON = "PY3" ]; then
	if grep -qs "Package: $Packagesix" cat $STATUS ; then
		echo ""
	else
		echo "Installing $Packagesix"
		opkg update && opkg install python3-six
	fi
fi

# Install python3-requests
echo ""
if grep -qs "Package: $Packagerequests" cat $STATUS ; then
	echo ""
else
	echo "Need to install $Packagerequests"
	echo ""
	if [ $OSTYPE = "DreamOs" ]; then
		apt-get update && apt-get install python-requests -y
	elif [ $PYTHON = "PY3" ]; then
		opkg update && opkg install python3-requests
	elif [ $PYTHON = "PY2" ]; then
		opkg update && opkg install python-requests
	fi
fi

# Install SQLite (python module — obavezno za plugin)
echo ""
if grep -qs "Package: $Packagesqlite" cat $STATUS ; then
	echo "SQLite Python module already installed"
else
	echo "Need to install $Packagesqlite"
	echo ""
	if [ $OSTYPE = "DreamOs" ]; then
		apt-get update && apt-get install python3-sqlite3 -y
	elif [ $PYTHON = "PY3" ]; then
		opkg update && opkg install python3-sqlite3
	elif [ $PYTHON = "PY2" ]; then
		opkg update && opkg install python-sqlite3
	fi
fi

# Install sqlite3 CLI (optional, for debug)
echo ""
if grep -qs "Package: sqlite3-cli" cat $STATUS ; then
	echo "sqlite3-cli already installed"
else
	echo "Installing sqlite3-cli (optional, for debug)"
	if [ $OSTYPE = "DreamOs" ]; then
		apt-get update && apt-get install sqlite3 -y
	else
		opkg update && opkg install sqlite3-cli 2>/dev/null
	fi
fi

# Install unzip (for extracting archive)
echo ""
if command -v unzip > /dev/null 2>&1; then
	echo "unzip already installed"
else
	echo "Installing unzip"
	if [ $OSTYPE = "DreamOs" ]; then
		apt-get update && apt-get install unzip -y
	else
		opkg update && opkg install unzip
	fi
fi

echo ""

## Remove tmp directory
[ -r $TMPPATH ] && rm -rf $TMPPATH > /dev/null 2>&1

## Remove old plugin directory
[ -r $PLUGINPATH ] && rm -rf $PLUGINPATH

# Download and install plugin
mkdir -p $TMPPATH
cd $TMPPATH
set -e
if [ -f /var/lib/dpkg/status ]; then
   echo "# Your image is OE2.5/2.6 #"
   echo ""
   echo ""
else
   echo "# Your image is OE2.0 #"
   echo ""
   echo ""
fi

# Download from GitHub
wget https://github.com/ciefp/CiefpChannelHistory/archive/refs/heads/main.tar.gz
tar -xzf main.tar.gz

# Detect structure — može biti "usr/..." ili direktno folder
if [ -d "CiefpChannelHistory-main/usr" ]; then
	cp -r 'CiefpChannelHistory-main/usr' '/'
elif [ -d "CiefpChannelHistory-main" ]; then
	mkdir -p "$(dirname $PLUGINPATH)"
	cp -r "CiefpChannelHistory-main" "$PLUGINPATH"
fi

set +e
cd
sleep 2

### Check if plugin installed correctly
if [ ! -d $PLUGINPATH ]; then
	echo "Something wrong .. Plugin not installed"
	exit 1
fi

# Verify SQLite Python module works
echo ""
echo "Verifying SQLite Python module..."
if python3 -c "import sqlite3" 2>/dev/null; then
	echo "SQLite Python module OK"
else
	echo "WARNING: SQLite Python module not available!"
	echo "Plugin may not work correctly."
fi

rm -rf $TMPPATH > /dev/null 2>&1
sync
echo ""
echo ""
echo "#########################################################"
echo "#    CiefpChannelHistory v${version} INSTALLED          #"
echo "#                  developed by ciefp                   #"
echo "#                  .::CiefpSettings::.                  #"
echo "#               https://github.com/ciefp                #"
echo "#########################################################"
echo "#                    Changelog:                         #"
echo -e "$changelog"
echo "#########################################################"

# Only restart if SKIP_REBOOT is not set to 1
if [ "$SKIP_REBOOT" = "0" ]; then
    echo "#           your Device will RESTART Now                #"
    echo "#########################################################"
    sleep 5
    killall -9 enigma2
else
    echo "#        Restart skipped (batch installation)           #"
    echo "#########################################################"
fi

exit 0