# -*- coding: utf-8 -*-
#

import xbmc
import xbmcaddon
import xbmcgui
import time, socket
import math
import urllib2
import base64

from utilities import Debug, notification, getSetting, getSettingAsBool, getSettingAsInt, getString, setSetting
from urllib2 import Request, urlopen, HTTPError, URLError
from httplib import HTTPException

try:
	import simplejson as json
except ImportError:
	import json

try:
	from hashlib import sha1
except ImportError:
	from sha import new as sha1

# read settings
__addon__ = xbmcaddon.Addon('script.trakt')
__addonversion__ = __addon__.getAddonInfo('version')

class traktError(Exception):
	def __init__(self, value, code=None):
		self.value = value
		if code:
			self.code = code
	def __str__(self):
		return repr(self.value)

class traktAuthProblem(traktError): pass
class traktServerBusy(traktError): pass
class traktUnknownError(traktError): pass
class traktNetworkError(traktError):
	def __init__(self, value, timeout):
		super(traktNetworkError, self).__init__(value)
		self.timeout = timeout

class traktAPI(object):

	__apikey = "b6135e0f7510a44021fac8c03c36c81a17be35d9"
	__baseURL = "https://api.trakt.tv"
	__username = ""
	__password = ""

	def __init__(self):
		Debug("[traktAPI] Initializing.")

		self.__username = getSetting('username')
		self.__password = sha1(getSetting('password')).hexdigest()

		self.settings = None
		if self.testAccount():
			Debug("[traktAPI] Getting account settings for '%s'." % self.__username)
			self.getAccountSettings()

	def __getData(self, url, args, timeout=60):
		data = None
		try:
			Debug("[traktAPI] __getData(): urllib2.Request(%s)" % url)

			if args == None:
				req = Request(url)
			else:
				req = Request(url, args)

			Debug("[traktAPI] __getData(): urllib2.urlopen()")
			t1 = time.time()
			response = urlopen(req, timeout=timeout)
			t2 = time.time()

			Debug("[traktAPI] __getData(): response.read()")
			data = response.read()

			Debug("[traktAPI] __getData(): Response Code: %i" % response.getcode())
			Debug("[traktAPI] __getData(): Response Time: %0.2f ms" % ((t2 - t1) * 1000))
			Debug("[traktAPI] __getData(): Response Headers: %s" % str(response.info().dict))

		except IOError, e:
			if hasattr(e, 'code'): # error 401 or 503, possibly others
				# read the error document, strip newlines, this will make an html page 1 line
				error_data = e.read().replace("\n", "").replace("\r", "")

				if e.code == 401: # authentication problem
					raise traktAuthProblem(error_data)
				elif e.code == 503: # server busy problem
					raise traktServerBusy(error_data)
				else:
					raise traktUnknownError(error_data, e.code)

			elif hasattr(e, 'reason'): # usually a read timeout, or unable to reach host
				raise traktNetworkError(str(e.reason), isinstance(e.reason, socket.timeout))

			else:
				raise traktUnknownError(e.message)

		return data
	
	# make a JSON api request to trakt
	# method: http method (GET or POST)
	# req: REST request (ie '/user/library/movies/all.json/%%API_KEY%%/%%USERNAME%%')
	# args: arguments to be passed by POST JSON (only applicable to POST requests), default:{}
	# returnStatus: when unset or set to false the function returns None upon error and shows a notification,
	#	when set to true the function returns the status and errors in ['error'] as given to it and doesn't show the notification,
	#	use to customise error notifications
	# silent: default is True, when true it disable any error notifications (but not debug messages)
	# passVersions: default is False, when true it passes extra version information to trakt to help debug problems
	# hideResponse: used to not output the json response to the log
	def traktRequest(self, method, url, args=None, returnStatus=False, returnOnFailure=False, silent=True, passVersions=False, hideResponse=False):
		raw = None
		data = None
		jdata = {}
		retries = getSettingAsInt('retries')

		if args is None:
			args = {}

		if not (method == 'POST' or method == 'GET'):
			Debug("[traktAPI] traktRequest(): Unknown method '%s'." % method)
			return None
		
		if method == 'POST':
			# debug log before username and sha1hash are injected
			Debug("[traktAPI] traktRequest(): Request data: '%s'." % str(json.dumps(args)))
			
			# inject username/pass into json data
			args['username'] = self.__username
			args['password'] = self.__password
			
			# check if plugin version needs to be passed
			if passVersions:
				args['plugin_version'] = __addonversion__
				args['media_center_version'] = xbmc.getInfoLabel('system.buildversion')
				args['media_center_date'] = xbmc.getInfoLabel('system.builddate')
			
			# convert to json data
			jdata = json.dumps(args)

		Debug("[traktAPI] traktRequest(): Starting retry loop, maximum %i retries." % retries)
		
		# start retry loop
		for i in range(retries):	
			Debug("[traktAPI] traktRequest(): (%i) Request URL '%s'" % (i, url))

			# check if we are closing
			if xbmc.abortRequested:
				Debug("[traktAPI] traktRequest(): (%i) xbmc.abortRequested" % i)
				break

			try:
				# get data from trakt.tv
				raw = self.__getData(url, jdata)
			except traktError, e:
				if isinstance(e, traktServerBusy):
					Debug("[traktAPI] traktRequest(): (%i) Server Busy (%s)" % (i, e.value))
				elif isinstance(e, traktAuthProblem):
					Debug("[traktAPI] traktRequest(): (%i) Authentication Failure (%s)" % (i, e.value))
					setSetting('account_valid', False)
					notification('trakt', getString(1110))
					return
				elif isinstance(e, traktNetworkError):
					Debug("[traktAPI] traktRequest(): (%i) Network error: %s" % (i, e.value))
					if e.timeout:
						notification('trakt', getString(1108) + " (timeout)") # can't connect to trakt
					xbmc.sleep(5000)
				elif isinstance(e, traktUnknownError):
					Debug("[traktAPI] traktRequest(): (%i) Other problem (%s)" % (i, e.value))
				else:
					pass

				xbmc.sleep(1000)
				continue

			# check if we are closing
			if xbmc.abortRequested:
				Debug("[traktAPI] traktRequest(): (%i) xbmc.abortRequested" % i)
				break

			# check that returned data is not empty
			if not raw:
				Debug("[traktAPI] traktRequest(): (%i) JSON Response empty" % i)
				xbmc.sleep(1000)
				continue

			try:
				# get json formatted data	
				data = json.loads(raw)
				if hideResponse:
					Debug("[traktAPI] traktRequest(): (%i) JSON response recieved, response not logged" % i)
				else:
					Debug("[traktAPI] traktRequest(): (%i) JSON response: '%s'" % (i, str(data)))
			except ValueError:
				# malformed json response
				Debug("[traktAPI] traktRequest(): (%i) Bad JSON response: '%s'", (i, raw))
				if not silent:
					notification('trakt', getString(1109) + ": Bad response from trakt") # Error
				
			# check for the status variable in JSON data
			if 'status' in data:
				if data['status'] == 'success':
					break
				elif returnOnFailure and data['status'] == 'failure':
					Debug("[traktAPI] traktRequest(): Return on error set, breaking retry.")
					break
				else:
					Debug("[traktAPI] traktRequest(): (%i) JSON Error '%s' -> '%s'" % (i, data['status'], data['error']))
					xbmc.sleep(1000)
					continue

			# check to see if we have data, an empty array is still valid data, so check for None only
			if not data is None:
				Debug("[traktAPI] traktRequest(): Have JSON data, breaking retry.")
				break

			xbmc.sleep(500)
		
		# handle scenario where all retries fail
		if data is None:
			Debug("[traktAPI] traktRequest(): JSON Request failed, data is still empty after retries.")
			return None
		
		if 'status' in data:
			if data['status'] == 'failure':
				Debug("[traktAPI] traktRequest(): Error: %s" % str(data['error']))
				if returnStatus or returnOnFailure:
					return data
				if not silent:
					notification('trakt', getString(1109) + ": " + str(data['error'])) # Error
				return None
			elif data['status'] == 'success':
				Debug("[traktAPI] traktRequest(): JSON request was successful.")

		return data

	# helper for onSettingsChanged
	def updateSettings(self):
	
		_username = getSetting('username')
		_password = sha1(getSetting('password')).hexdigest()
		
		if not ((self.__username == _username) and (self.__password == _password)):
			self.__username = _username
			self.__password = _password
			self.testAccount(force=True)

	# http://api.trakt.tv/account/test/<apikey>
	# returns: {"status": "success","message": "all good!"}
	def testAccount(self, force=False):
		
		if self.__username == "":
			notification('trakt', getString(1106)) # please enter your Username and Password in settings
			setSetting('account_valid', False)
			return False
		elif self.__password == "":
			notification("trakt", getString(1107)) # please enter your Password in settings
			setSetting('account_valid', False)
			return False

		if not getSettingAsBool('account_valid') or force:
			Debug("[traktAPI] Testing account '%s'." % self.__username)

			url = "%s/account/test/%s" % (self.__baseURL, self.__apikey)
			Debug("[traktAPI] testAccount(url: %s)" % url)
			
			args = json.dumps({'username': self.__username, 'password': self.__password})
			response = None
			
			try:
				# get data from trakt.tv
				response = self.__getData(url, args)
			except traktError, e:
				if isinstance(e, traktAuthProblem):
					Debug("[traktAPI] testAccount(): Account '%s' failed authentication. (%s)" % (self.__username, e.value))
				elif isinstance(e, traktServerBusy):
					Debug("[traktAPI] testAccount(): Server Busy (%s)" % e.value)
				elif isinstance(e, traktNetworkError):
					Debug("[traktAPI] testAccount(): Network error: %s" % e.value)
				elif isinstance(e, traktUnknownError):
					Debug("[traktAPI] testAccount(): Other problem (%s)" % e.value)
				else:
					pass
			
			if response:
				data = None
				try:
					data = json.loads(response)
				except ValueError:
					pass

				if 'status' in data:
					if data['status'] == 'success':
						setSetting('account_valid', True)
						Debug("[traktAPI] testAccount(): Account '%s' is valid." % self.__username)
						return True

		else:
			return True

		notification('trakt', getString(1110)) # please enter your Password in settings
		setSetting('account_valid', False)
		return False

	# url: http://api.trakt.tv/account/settings/<apikey>
	# returns: all settings for authenticated user
	def getAccountSettings(self):
		if self.testAccount():
			url = "%s/account/settings/%s" % (self.__baseURL, self.__apikey)
			Debug("[traktAPI] getAccountSettings(url: %s)" % url)
			response = self.traktRequest('POST', url, hideResponse=True)
			if response:
				if 'status' in response:
					if response['status'] == 'success':
						self.settings = response

	# url: http://api.trakt.tv/<show|movie>/watching/<apikey>
	# returns: {"status":"success","message":"watching The Walking Dead 1x01","show":{"title":"The Walking Dead","year":"2010","imdb_id":"tt123456","tvdb_id":"153021","tvrage_id":"1234"},"season":"1","episode":{"number":"1","title":"Days Gone Bye"},"facebook":false,"twitter":false,"tumblr":false}
	def watching(self, type, data):
		if self.testAccount():
			url = "%s/%s/watching/%s" % (self.__baseURL, type, self.__apikey)
			Debug("[traktAPI] watching(url: %s, data: %s)" % (url, str(data)))
			if getSettingAsBool('simulate_scrobbling'):
				return {'status': 'success'}
			else:
				return self.traktRequest('POST', url, data, passVersions=True)
	
	def watchingEpisode(self, info, duration, percent):
		data = {'tvdb_id': info['tvdb_id'], 'title': info['showtitle'], 'year': info['year'], 'season': info['season'], 'episode': info['episode'], 'duration': math.ceil(duration), 'progress': math.ceil(percent)}
		if 'uniqueid' in info:
			data['episode_tvdb_id'] = info['uniqueid']['unknown']
		return self.watching('show', data)
	def watchingMovie(self, info, duration, percent):
		data = {'imdb_id': info['imdbnumber'], 'title': info['title'], 'year': info['year'], 'duration': math.ceil(duration), 'progress': math.ceil(percent)}
		return self.watching('movie', data)

	# url: http://api.trakt.tv/<show|movie>/scrobble/<apikey>
	# returns: {"status": "success","message": "scrobbled The Walking Dead 1x01"}
	def scrobble(self, type, data):
		if self.testAccount():
			url = "%s/%s/scrobble/%s" % (self.__baseURL, type, self.__apikey)
			Debug("[traktAPI] scrobble(url: %s, data: %s)" % (url, str(data)))
			if getSettingAsBool('simulate_scrobbling'):
				return {'status': 'success'}
			else:
				return self.traktRequest('POST', url, data, returnOnFailure=True, passVersions=True)

	def scrobbleEpisode(self, info, duration, percent):
		data = {'tvdb_id': info['tvdb_id'], 'title': info['showtitle'], 'year': info['year'], 'season': info['season'], 'episode': info['episode'], 'duration': math.ceil(duration), 'progress': math.ceil(percent)}
		if 'uniqueid' in info:
			data['episode_tvdb_id'] = info['uniqueid']['unknown']
		return self.scrobble('show', data)
	def scrobbleMovie(self, info, duration, percent):
		data = {'imdb_id': info['imdbnumber'], 'title': info['title'], 'year': info['year'], 'duration': math.ceil(duration), 'progress': math.ceil(percent)}
		return self.scrobble('movie', data)

	# url: http://api.trakt.tv/<show|movie>/cancelwatching/<apikey>
	# returns: {"status":"success","message":"cancelled watching"}
	def cancelWatching(self, type):
		if self.testAccount():
			url = "%s/%s/cancelwatching/%s" % (self.__baseURL, type, self.__apikey)
			Debug("[traktAPI] cancelWatching(url: %s)" % url)
			if getSettingAsBool('simulate_scrobbling'):
				return {'status': 'success'}
			else:
				return self.traktRequest('POST', url)
		
	def cancelWatchingEpisode(self):
		return self.cancelWatching('show')
	def cancelWatchingMovie(self):
		return self.cancelWatching('movie')

	# url: http://api.trakt.tv/user/library/<shows|movies>/collection.json/<apikey>/<username>/min
	# response: [{"title":"Archer (2009)","year":2009,"imdb_id":"tt1486217","tvdb_id":110381,"seasons":[{"season":2,"episodes":[1,2,3,4,5]},{"season":1,"episodes":[1,2,3,4,5,6,7,8,9,10]}]}]
	# note: if user has nothing in collection, response is then []
	def getLibrary(self, type):
		if self.testAccount():
			url = "%s/user/library/%s/collection.json/%s/%s/min" % (self.__baseURL, type, self.__apikey, self.__username)
			Debug("[traktAPI] getLibrary(url: %s)" % url)
			return self.traktRequest('POST', url)

	def getShowLibrary(self):
		return self.getLibrary('shows')
	def getMovieLibrary(self):
		return self.getLibrary('movies')

	# url: http://api.trakt.tv/user/library/<shows|movies>/watched.json/<apikey>/<username>/min
	# returns: [{"title":"Archer (2009)","year":2009,"imdb_id":"tt1486217","tvdb_id":110381,"seasons":[{"season":2,"episodes":[1,2,3,4,5]},{"season":1,"episodes":[1,2,3,4,5,6,7,8,9,10]}]}]
	# note: if nothing watched in collection, returns []
	def getWatchedLibrary(self, type):
		if self.testAccount():
			url = "%s/user/library/%s/watched.json/%s/%s/min" % (self.__baseURL, type, self.__apikey, self.__username)
			Debug("[traktAPI] getWatchedLibrary(url: %s)" % url)
			return self.traktRequest('POST', url)

	def getWatchedEpisodeLibrary(self,):
		return self.getWatchedLibrary('shows')
	def getWatchedMovieLibrary(self):
		return self.getWatchedLibrary('movies')

	# url: http://api.trakt.tv/<show|show/episode|movie>/library/<apikey>
	# returns: {u'status': u'success', u'message': u'27 episodes added to your library'}
	def addToLibrary(self, type, data):
		if self.testAccount():
			url = "%s/%s/library/%s" % (self.__baseURL, type, self.__apikey)
			Debug("[traktAPI] addToLibrary(url: %s, data: %s)" % (url, str(data)))
			return self.traktRequest('POST', url, data)

	def addEpisode(self, data):
		return self.addToLibrary('show/episode', data)
	def addShow(self, data):
		return self.addToLibrary('show', data)
	def addMovie(self, data):
		return self.addToLibrary('movie', data)

	# url: http://api.trakt.tv/<show|show/episode|movie>/unlibrary/<apikey>
	# returns:
	def removeFromLibrary(self, type, data):
		if self.testAccount():
			url = "%s/%s/unlibrary/%s" % (self.__baseURL, type, self.__apikey)
			Debug("[traktAPI] removeFromLibrary(url: %s, data: %s)" % (url, str(data)))
			return self.traktRequest('POST', url, data)

	def removeEpisode(self, data):
		return self.removeFromLibrary('show/episode', data)
	def removeShow(self, data):
		return self.removeFromLibrary('show', data)
	def removeMovie(self, data):
		return self.removeFromLibrary('movie', data)

	# url: http://api.trakt.tv/<show|show/episode|movie>/seen/<apikey>
	# returns: {u'status': u'success', u'message': u'2 episodes marked as seen'}
	def updateSeenInLibrary(self, type, data):
		if self.testAccount():
			url = "%s/%s/seen/%s" % (self.__baseURL, type, self.__apikey)
			Debug("[traktAPI] updateSeenInLibrary(url: %s, data: %s)" % (url, str(data)))
			return self.traktRequest('POST', url, data)

	def updateSeenEpisode(self, data):
		return self.updateSeenInLibrary('show/episode', data)
	def updateSeenShow(self, data):
		return self.updateSeenInLibrary('show', data)
	def updateSeenMovie(self, data):
		return self.updateSeenInLibrary('movie', data)

	# url: http://api.trakt.tv/<show/episode|movie>/summary.format/apikey/title[/season/episode]
	# returns: returns information for a movie or episode
	def getSummary(self, type, data):
		if self.testAccount():
			url = "%s/%s/summary.json/%s/%s" % (self.__baseURL, type, self.__apikey, data)
			Debug("[traktAPI] getSummary(url: %s)" % url)
			return self.traktRequest('POST', url)

	def getShowSummary(self, id, season, episode):
		data = "%s/%s/%s" % (id, season, episode)
		return self.getSummary('show/episode', data)
	def getMovieSummary(self, id):
		data = str(id)
		return self.getSummary('movie', data)

	# url: http://api.trakt.tv/rate/<episode|movie>/apikey
	# returns: {"status":"success","message":"rated Portlandia 1x01","type":"episode","rating":"love","ratings":{"percentage":100,"votes":2,"loved":2,"hated":0},"facebook":true,"twitter":true,"tumblr":false}
	def rate(self, type, data):
		if self.testAccount():
			url = "%s/rate/%s/%s" % (self.__baseURL, type, self.__apikey)
			Debug("[traktAPI] rate(url: %s, data: %s)" % (url, str(data)))
			return self.traktRequest('POST', url, data, passVersions=True)

	def rateEpisode(self, data):
		return self.rate('episode', data)
	def rateMovie(self, data):
		return self.rate('movie', data)
