# -*- coding: utf-8 -*-
"""For naoqi-sim's live tests only: a service as a robot package writes one (Python 2.7).

Started by ALServiceManager with /usr/bin/python2, it connects to tcp://127.0.0.1:9559, the address
robot software uses for NAOqi, and registers NaoqiSimTestService. `where()` tells the test which
interpreter runs it; `echo(text)` proves a call from outside the robot reaches it.
"""
import sys
import time

import qi


class NaoqiSimTestService(object):
    def where(self):
        return sys.executable

    def echo(self, text):
        return text


def main():
    session = qi.Session()
    session.connect("tcp://127.0.0.1:9559")
    session.registerService("NaoqiSimTestService", NaoqiSimTestService())
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
