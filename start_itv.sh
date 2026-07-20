#!/bin/sh

sudo /home/museum/raspi-teletext/tvctl on
python3 t42restream.py ./t42/ITV-19890114-sq.t42 --time-format "%H:%M/%S" --magazine-parallel --control interrupted-sequence=off --loop | /home/museum/raspi-teletext/teletext -m 0xff00 -l 66 -