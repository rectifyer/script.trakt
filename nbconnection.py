# -*- coding: utf-8 -*-
#

import time
import thread
import threading

try:
	import http.client as httplib # Python 3.0 +
except ImportError:
	import httplib # Python 2.7 and earlier

# Allows non-blocking http requests
class NBConnection():
	def __init__(self, host, port=None, https=False, strict=None, timeout=None):
		if https:
			self.rawConnection = httplib.HTTPSConnection(host, port, strict, timeout)
		else:
			self.rawConnection = httplib.HTTPConnection(host, port, strict, timeout)
		self.response = None
		self.responseLock = threading.Lock()
		self.closing = False

	def request(self, method, url, body=None, headers={}):
		self.rawConnection.request(method, url, body, headers)

	def hasResult(self):
		if self.responseLock.acquire(False):
			self.responseLock.release()
			return True
		else:
			return False

	def getResult(self):
		while not self.hasResult() and not self.closing:
			time.sleep(1)
		return self.response

	def go(self):
		self.responseLock.acquire()
		thread.start_new_thread(NBConnection._run, (self,))

	def _run(self):
		self.response = self.rawConnection.getresponse()
		self.responseLock.release()

	def close(self):
		self.closing = True
		self.rawConnection.close()
