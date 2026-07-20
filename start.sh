#!/bin/sh

sudo /home/museum/raspi-teletext/tvctl on
python3 t42restream.py ./t42/BBC1-19940218-sq.t42 --time-format "%H:%M/%S" --magazine-parallel --control interrupted-sequence=off --loop | /home/museum/raspi-teletext/teletext -m 0xff00 -l 66 -
#python1 t42restream.py ./t42/BBC1-19940218-sq.t42 --time-format "%H:%M/%S" --magazine-parallel --control interrupted-sequence=off --control erase=on --control update=off --loop | /home/museum/raspi-teletext/teletext -m 0xff00 -l 66 -
