#!/bin/sh

CURDIR=`pwd`

# to emulate USB serial port
sudo apt-get -y install socat

# Python requirements
sudo apt-get install -y \
    python-pil \
    python-twisted \
    python-dateutil \
    python-autobahn \
    python-influxdb \
    python-zeroconf \
    python-serial

# Install gstreamer
sudo apt-get install -y \
    gstreamer1.0-good \
    gstreamer1.0-tools 

# Build and install Janus

# Install pre-requisite for Janus
sudo apt-get install -y libmicrohttpd-dev libjansson-dev \
		libssl-dev libsrtp-dev libsofia-sip-ua-dev libglib2.0-dev \
		libopus-dev libogg-dev libcurl4-openssl-dev liblua5.3-dev \
		libconfig-dev pkg-config gengetopt libtool automake \
		libnice-dev libsrtp2-dev

mkdir -p ~/3p
cd ~/3p
mkdir -p janus && cd janus

if [ -d "janus-gateway" ]
then
	cd janus-gateway
	git pull
else
	git clone https://github.com/meetecho/janus-gateway.git
	cd janus-gateway
fi

sh autogen.sh
./configure --disable-websockets --disable-data-channels \
	--disable-rabbitmq --disable-docs --disable-mqtt --prefix=/opt/janus
make
sudo make install
sudo make configs

cd ${CURDIR}

sudo cp janus.plugin.streaming.cfg /opt/janus/etc/janus/janus.plugin.streaming.cfg

sudo sed -i "/^exit 0$/ i modprobe bcm2835-v4l2" /etc/rc.local

sudo cp open_door_bell.service /lib/systemd/system/
sudo systemctl start open_door_bell.service
sudo systemctl enable open_door_bell.service