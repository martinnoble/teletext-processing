#!/bin/sh

sudo /home/museum/raspi-teletext/tvctl on
python3 channel_monitor.py | /home/museum/raspi-teletext/teletext -m 0xff00 -l 66 -
