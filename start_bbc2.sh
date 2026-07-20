#!/bin/sh

sudo /home/museum/raspi-teletext/tvctl on
python3 t42restream.py ./t42/BBC2-19840529-sq.t42 --time-format "%H:%M/%S" --magazine-parallel --control magazine-serial=off --control interrupted-sequence=off --loop | /home/museum/raspi-teletext/teletext -m 0xff00 -l 66 -
