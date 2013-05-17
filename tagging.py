# -*- coding: utf-8 -*-

import xbmc
import xbmcaddon
import xbmcgui
import utilities as utils
import copy
import time
from traktapi import traktAPI

__addon__ = xbmcaddon.Addon("script.trakt")

TAG_PREFIX = "trakt.tv - "
PRIVACY_LIST = ['public', 'friends', 'private']

def tagToList(tag):
	return tag.replace(TAG_PREFIX, "", 1)
def listToTag(list):
	return "%s%s" % (TAG_PREFIX, list)
def isTraktList(tag):
	return True if tag.startswith(TAG_PREFIX) else False

class Tagger():

	traktSlugs = None
	traktSlugsLast = 0

	def __init__(self, show_progress=False, api=None):
		if api is None:
			api = traktAPI(loadSettings=False)
		self.traktapi = api
		self.updateSettings()

	def updateSettings(self):
		self._watchlists = utils.getSettingAsBool('tagging_watchlists')
		self._ratings = utils.getSettingAsBool('tagging_ratings')
		self._ratingMin = utils.getSettingAsInt('tagging_ratings_min')
		self.simulate = utils.getSettingAsBool('simulate_tagging')
		if self.simulate:
			utils.Debug("[Tagger] Tagging is configured to be simulated.")
	
	def xbmcLoadMovies(self):
		utils.Debug("[Tagger] Getting movie data from XBMC.")
		data = utils.xbmcJsonRequest({'jsonrpc': '2.0', 'id': 0, 'method': 'VideoLibrary.GetMovies', 'params': {'properties': ['tag', 'title', 'imdbnumber', 'year']}})
		if not data:
			utils.Debug("[Tagger] XBMC JSON request was empty.")
			return
		
		if not 'movies' in data:
			utils.Debug('[Tagger] Key "movies" not found')
			return

		movies = data['movies']
		utils.Debug("[Tagger] XBMC JSON Result: '%s'" % str(movies))

		for movie in movies:
			movie['imdb_id'] = ""
			movie['tmdb_id'] = ""
			id = movie['imdbnumber']
			if id.startswith("tt"):
				movie['imdb_id'] = id
			if id.isdigit():
				movie['tmdb_id'] = id
			del(movie['imdbnumber'])
			del(movie['label'])

		return movies

	def xbmcLoadTVShows(self):
		utils.Debug("[Tagger] Getting tv show data from XBMC.")
		data = utils.xbmcJsonRequest({'jsonrpc': '2.0', 'method': 'VideoLibrary.GetTVShows', 'params': {'properties': ['tag', 'title', 'imdbnumber', 'year']}, 'id': 0})
		if not data:
			utils.Debug("[Tagger] xbmc json request was empty.")
			return None
		
		if not 'tvshows' in data:
			utils.Debug('[Tagger] Key "tvshows" not found')
			return None

		shows = data['tvshows']
		utils.Debug("[Tagger] XBMC JSON Result: '%s'" % str(shows))

		for show in shows:
			show['tvdb_id'] = ""
			show['imdb_id'] = ""
			id = show['imdbnumber']
			if id.startswith("tt"):
				show['imdb_id'] = id
			if id.isdigit():
				show['tvdb_id'] = id
			del(show['imdbnumber'])
			del(show['label'])

		return shows

	def xbmcTagsToListData(self):
		lists = {}

		for movie in self.movies:
			if len(movie['tag']) > 0:
				for tag in movie['tag']:
					if not isTraktList(tag):
						continue
					if not tagToList(tag) in lists:
						lists[tagToList(tag)] = []
					movie['type'] = "movie"
					lists[tagToList(tag)].append(movie)

		for show in self.shows:
			if len(show['tag']) > 0:
				for tag in show['tag']:
					if not isTraktList(tag):
						continue
					if not tagToList(tag) in lists:
						lists[tagToList(tag)] = []
					show['type'] = "show"
					lists[tagToList(tag)].append(show)

		return lists

	def traktGetLists(self):
		utils.Debug("[Tagger] Getting lists from trakt.tv")
		data = self.traktapi.getUserLists()
		
		if not isinstance(data, list):
			utils.Debug("[Tagger] Invalid trakt.tv lists, possible error getting data from trakt, aborting trakt.tv collection update.")
			return False

		lists = {}
		for item in data:
			lists[item['name']] = item['slug']

		return lists

	def traktGetListData(self): #, lists, movies, shows):
		if not self.traktSlugs:
			utils.Debug("[Tagger] No lists at trakt.tv, nothing to retrieve.")
			return {}
		traktLists = {}
		utils.Debug("[Tagger] Getting list data from trakt.tv")
		for listName in self.traktSlugs:
			slug = self.traktSlugs[listName]
			traktLists[listName] = []
			
			utils.Debug("[Tagger] Getting list data for list slug '%s'." % slug)
			tList = self.traktapi.getUserList(slug)
			
			if not isinstance(tList, dict):
				utils.Debug("[Tagger] Invalid trakt.tv list data, possible error getting data from trakt, aborting tagging sync.")
				return False

			for item in tList['items']:
				data = {}
				data['type'] = item['type']
				if data['type'] == 'movie':
					data['title'] = item['movie']['title']
					data['year'] = item['movie']['year']
					data['imdb_id'] = item['movie']['imdb_id']
					data['tmdb_id'] = item['movie']['tmdb_id']
					m = utils.findMovie(data, self.movies)
					if m:
						data['xbmc_id'] = m['movieid']
				elif data['type'] == 'show':
					data['title'] = item['show']['title']
					data['year'] = item['show']['year']
					data['imdb_id'] = item['show']['imdb_id']
					data['tvdb_id'] = item['show']['tvdb_id']
					s = utils.findShow(data, self.shows)
					if s:
						data['xbmc_id'] = s['tvshowid']
				if data['type'] in ['movie', 'show']:
					traktLists[listName].append(data)

		return traktLists

	def traktGetWatchistData(self, traktData):
		watchlist_movies = self.traktapi.getWatchlistMovies()
		watchlist_shows = self.traktapi.getWatchlistShows()
		
		if isinstance(watchlist_movies, list) and isinstance(watchlist_shows, list):
			traktData['Watchlist'] = []
			for item in watchlist_movies:
				data = {}
				data['type'] = 'movie'
				data['title'] = item['title']
				data['year'] = item['year']
				data['imdb_id'] = "" if item['imdb_id'] is None else item['imdb_id']
				data['tmdb_id'] = "" if item['tmdb_id'] is None else item['tmdb_id']
				m = utils.findMovie(data, self.movies)
				if m:
					data['xbmc_id'] = m['movieid']
				traktData['Watchlist'].append(data)
			for item in watchlist_shows:
				data = {}
				data['type'] = 'show'
				data['title'] = item['title']
				data['year'] = item['year']
				data['imdb_id'] = "" if item['imdb_id'] is None else item['imdb_id']
				data['tvdb_id'] = "" if item['tvdb_id'] is None else item['tvdb_id']
				s = utils.findShow(data, self.shows)
				if s:
					data['xbmc_id'] = s['tvshowid']
				traktData['Watchlist'].append(data)
		else:
			utils.Debug("[Tagger] There was a problem getting your watchlists.")
			return False
	
		return traktData

	def traktGetRatingData(self, traktData):
		if not self._ratings:
			return traktData
			
		rated_movies = self.traktapi.getRatedMovies()
		rated_shows = self.traktapi.getRatedShows()
		
		if isinstance(rated_movies, list) and isinstance(rated_shows, list):
			for item in rated_movies:
				data = {}
				data['type'] = 'movie'
				data['title'] = item['title']
				data['year'] = item['year']
				data['imdb_id'] = "" if item['imdb_id'] is None else item['imdb_id']
				data['tmdb_id'] = "" if item['tmdb_id'] is None else item['tmdb_id']
				m = utils.findMovie(data, self.movies)
				if m:
					data['xbmc_id'] = m['movieid']
				if item['rating_advanced'] >= self._ratingMin:
					tag = "Rating: %s" % item['rating_advanced']
					if not tag in traktData:
						traktData[tag] = []
					traktData[tag].append(data)
			for item in rated_shows:
				data = {}
				data['type'] = 'show'
				data['title'] = item['title']
				data['year'] = item['year']
				data['imdb_id'] = "" if item['imdb_id'] is None else item['imdb_id']
				data['tvdb_id'] = "" if item['tvdb_id'] is None else unicode(item['tvdb_id'])
				s = utils.findShow(data, self.shows)
				if s:
					data['xbmc_id'] = s['tvshowid']
				if item['rating_advanced'] >= self._ratingMin:
					tag = "Rating: %s" % item['rating_advanced']
					if not tag in traktData:
						traktData[tag] = []
					traktData[tag].append(data)
		else:
			utils.Debug("[Tagger] There was a problem getting your rated movies or shows.")
			return False
		
		return traktData

	def proccessXBMCTags(self, trakt, xbmc, remove=True):
		data = {'movie': {}, 'show': {}}
		for tag in trakt:
			for item in trakt[tag]:
				type = item['type']
				d = None
				id = None
				if type == 'movie':
					d = utils.findMovie(item, self.movies)
					if d:
						id = d['movieid']
				elif type == 'show':
					d = utils.findShow(item, self.shows)
					if d:
						id = d['tvshowid']
				if d:
					formattedTag = listToTag(tag)
					if not formattedTag in d['tag']:
						if not id in data[type]:
							data[type][id] = d['tag']
						if not formattedTag in data[type][id]:
							data[type][id].append(formattedTag)

		if remove:
			for tag in xbmc:
				for item in xbmc[tag]:
					type = item['type']
					id = None
					if type == 'movie':
						id = item['movieid']
					elif type == 'show':
						id = item['tvshowid']
					d = None
					if tag in trakt:
						d = utils.findInList(trakt[tag], xbmc_id=id)
					if not d:
						if not id in data[type]:
							data[type][id] = item['tag']
						try:
							data[type][id].remove(listToTag(tag))
						except ValueError:
							pass

		return data

	def sanitizeTraktParams(self, data):
		newData = copy.deepcopy(data)
		for item in newData:
			if 'imdb_id' in item and not item['imdb_id']:
				del(item['imdb_id'])
			if 'tmdb_id' in item and not item['tmdb_id']:
				del(item['tmdb_id'])
			if 'tvdb_id' in item and not item['tvdb_id']:
				del(item['tvdb_id'])
			if 'tvshowid' in item:
				del(item['tvshowid'])
			if 'movieid' in item:
				del(item['movieid'])
			if 'tag' in item:
				del(item['tag'])
		return newData

	def isListOnTrakt(self, list):
		if self.traktSlugs is None or (time.time() - self.traktSlugsLast) > (60 * 10):
			self.traktSlugs = self.traktGetLists()
			self.traktSlugsLast = time.time()
		else:
			utils.Debug("[Tagger] Using cached lists.")

		return list in self.traktSlugs

	def getSlug(self, list):
		if self.isListOnTrakt(list):
			return self.traktSlugs[list]
		
		return None

	def xbmcUpdateTags(self, data):
		# update xbmc tags for movies from trakt lists
		chunked = utils.chunks([{"jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.SetMovieDetails", "params": {"movieid" : movie, "tag": data['movie'][movie]}} for movie in data['movie']], 50)
		for chunk in chunked:
			if self.simulate:
				utils.Debug("[Tagger] %s" % str(chunk))
			else:
				utils.xbmcJsonRequest(chunk)

		# update xbmc tags for shows from trakt lists
		chunked = utils.chunks([{"jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.SetTVShowDetails", "params": {"tvshowid" : show, "tag": data['show'][show]}} for show in data['show']], 50)
		for chunk in chunked:
			if self.simulate:
				utils.Debug("[Tagger] %s" % str(chunk))
			else:
				utils.xbmcJsonRequest(chunk)

	
	def traktListAddItem(self, list, data):
		if not list:
			utils.Debug("[Tagger] No list provided.")
			return

		if not data:
			utils.Debug("[Tagger] Nothing to add to trakt lists")
			return
		
		params = {}
		params['items'] = self.sanitizeTraktParams(data)

		if self.simulate:
			utils.Debug("[Tagger] '%s' adding '%s'" % (list, str(params)))
		else:
			if self.isListOnTrakt(list):
				slug = self.traktSlugs[list]
				params['slug'] = slug
			else:
				p = utils.getSettingAsInt('tagging_list_privacy')
				allow_shouts = utils.getSettingAsBool('tagging_list_allowshouts')
				
				utils.Debug("[Tagger] Creating new list '%s'" % list)
				result = self.traktapi.userListAdd(list, PRIVACY_LIST[p], allow_shouts=allow_shouts)
				
				if result and 'status' in result and result['status'] == 'success':
					slug = result['slug']
					params['slug'] = slug
					self.traktSlugs[list] = slug
				else:
					utils.Debug("[Tagger] There was a problem create the list '%s' on trakt.tv" % list)
					return
			
			self.traktapi.userListItemAdd(params)
				
				
						
	def traktListRemoveItem(self, list, data):
		if not list:
			utils.Debug("[Tagger] No list provided.")
			return

		if not data:
			utils.Debug("[Tagger] Nothing to remove from trakt list.")
			return
		
		if not self.isListOnTrakt(list):
			utils.Debug("[Tagger] Trying to remove items from non-existant list '%s'." % list)
			
		slug = self.traktSlugs[list]
		params = {'slug': slug}
		params['items'] = self.sanitizeTraktParams(data)
		
		if self.simulate:
			utils.Debug("[Tagger] '%s' removing '%s'" % (list, str(params)))
		else:
			self.traktapi.userListItemDelete(params)

	def updateWatchlist(self, data, remove=False):
		if utils.isMovie(data['type']):
			movie = {}
			movie['title'] = data['title']
			if 'imdb_id' in data:
				movie['imdb_id'] = data['imdb_id']
			if 'tmdb_id' in data:
				movie['tmdb_id'] = data['tmdb_id']
			movie['year'] = data['year']
			params = {'movies': [movie]}
			if not remove:
				self.traktapi.watchlistAddMovies(params)
			else:
				self.traktapi.watchlistRemoveMovies(params)

		elif utils.isShow(data['type']):
			params = {'shows': []}
			show = {}
			show['title'] = data['title']
			if 'imdb_id' in data:
				show['imdb_id'] = data['imdb_id']
			if 'tvdb_id' in data:
				show['tvdb_id'] = data['tvdb_id']
			params = {'shows': [show]}
			if not remove:
				self.traktapi.watchlistAddShows(params)
			else:
				self.traktapi.watchlistRemoveShows(params)
	
	def isAborted(self):
		if xbmc.abortRequested:
			utils.Debug("[Tagger] XBMC abort requested, stopping.")
			return true

	def updateTagsFromTrakt(self):
		if not utils.getSettingAsBool('tagging_enable'):
			utils.Debug("[Tagger] Tagging is not enabled, aborting.")
			return
	
		utils.Debug("[Tagger] Starting List/Tag synchronization.")

		self.movies = self.xbmcLoadMovies()
		
		if self.isAborted():
			return
			
		self.shows = self.xbmcLoadTVShows()

		if self.isAborted():
			return

		# abort if either of the XBMC values are not lists
		if not isinstance(self.movies, list) or not isinstance(self.shows, list):
			utils.Debug("[Tagger] Aborting tagging sync, problem getting show or movie data from XBMC.")
			return

		# get all list slugs from trakt
		self.traktSlugs = self.traktGetLists()
		if not isinstance(self.traktSlugs, dict):
			utils.Debug("[Tagger] Error getting lists from trakt.tv.")
			return
		utils.Debug("[Tagger] Lists at trakt.tv: %s" % str(self.traktSlugs))

		if self.isAborted():
			return

		# build a list collection from XBMC tags
		xbmcLists = self.xbmcTagsToListData()
		utils.Debug("[Tagger] XBMC Tags: %s" % str(xbmcLists))

		if self.isAborted():
			return

		# build list collection from trakt lists
		traktLists = self.traktGetListData()
		
		if self.isAborted():
			return

		# get watchlists if enabled
		if self._watchlists:
			traktLists = self.traktGetWatchistData(traktLists)
		
		if self.isAborted():
			return

		# get ratings if enabled
		if self._ratings:
			traktLists = self.traktGetRatingData(traktLists)
	
		utils.Debug("[Tagger] trakt.tv Lists: %s" % str(traktLists))

		if self.isAborted():
			return

		# update xbmc tags from trakt lists
		utils.Debug("[Tagger] Updating XBMC tags from trakt.tv list(s).")
		xbmcData = self.proccessXBMCTags(traktLists, xbmcLists)
		utils.Debug("[Tagger] %s" % str(xbmcData))
		self.xbmcUpdateTags(xbmcData)

		utils.Debug("[Tagger] Tags have been updated.")

	def manageList(self, data):

		# only get slugs from trakt every ten minutes, instead of every call
		if self.traktSlugs is None or (time.time() - self.traktSlugsLast) > (60 * 10):
			self.traktSlugs = self.traktGetLists()
			self.traktSlugsLast = time.time()
		else:
			utils.Debug("[Tagger] Using cached lists.")

		if not isinstance(self.traktSlugs, dict):
			utils.Debug("[Tagger] Error getting lists from trakt.tv.")
			return

		d = traktListDialog(lists=self.traktSlugs, data=data)
		d.doModal()
		if not d.selectedLists is None:
			oldTags = [tagToList(tag) for tag in data['tag']]
			newTags = d.selectedLists
			
			if set(oldTags) == set(newTags):
				utils.Debug("[Tagger] '%s' had no changes made to the lists it belongs to." % data['title'])

			else:
				w = []
				
				for tag in newTags:
					l = listToTag(tag)
					w.append(l)
					if tag.lower() == "watchlist":
						if not l in data['tag']:
							utils.Debug("[Tagger] Adding '%s' to Watchlist." % data['title'])
							self.updateWatchlist(data)
					elif tag.lower().startswith("rating:"):
						pass
					else:
						if not l in data['tag']:
							utils.Debug("[Tagger] Adding '%s' to '%s'." % (data['title'], tag))
							self.traktListAddItem(tag, [data])

				# use set comparison to find what was removed
				s1 = set(data['tag'])
				s2 = set(w)
				toRemove = list(s1.difference(s2))
				for tag in toRemove:
					l = tagToList(tag)
					if l.lower() == "watchlist":
						utils.Debug("[Tagger] Removing: '%s' from Watchlist." % data['title'])
						self.updateWatchlist(data, remove=True)
					elif l.lower().startswith("rating:"):
						utils.Debug("[Tagger] Error, rating tag removed somehow. %s" % l)
					else:
						utils.Debug("[Tagger] Removing: '%s' from '%s'." % (data['title'], str(l)))
						self.traktListRemoveItem(l, [data])

				# use set comparison to find out if xbmc tags need updating
				if len(list(s2.difference(s1))) > 0 or len(toRemove) > 0:
					result = None
					if data['type'] == 'movie':
						result = utils.xbmcJsonRequest({"jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.SetMovieDetails", "params": {"movieid" : data['movieid'], "tag": w}})
					elif data['type'] == 'show':
						result = utils.xbmcJsonRequest({"jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.SetTVShowDetails", "params": {"tvshowid" : data['tvshowid'], "tag": w}})

					if result == "OK":
						s = utils.getFormattedItemName(data['type'], data)
						utils.Debug("[Tagger] XBMC tags for '%s' were updated with '%s'." % (s, str(w)))
						utils.notification(utils.getString(1201), utils.getString(1657) % s)

		else:
			utils.Debug("[Tagger] Dialog was cancelled.")

		del d

	def manualAddToList(self, list, data):
		if list.lower().startswith("rating:"):
			utils.Debug("[Tagger] '%s' is a reserved list name." % list)
			return

		tag = listToTag(list)
		if tag in data['tag']:
			utils.Debug("[Tagger] '%d' is already in the list '%s'." % (data['title'], list))
			return
		
		if tag.lower() == "watchlist":
			utils.Debug("[Tagger] Adding '%s' to Watchlist." % data['title'])
			self.updateWatchlist(data)
		else:
			utils.Debug("[Tagger] Adding '%s' to '%s'." % (data['title'], list))
			self.traktListAddItem(list, [data])
		
		data['tag'].append(tag)
		result = None
		if data['type'] == 'movie':
			result = utils.xbmcJsonRequest({"jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.SetMovieDetails", "params": {"movieid" : data['movieid'], "tag": data['tag']}})
		elif data['type'] == 'show':
			result = utils.xbmcJsonRequest({"jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.SetTVShowDetails", "params": {"tvshowid" : data['tvshowid'], "tag": data['tag']}})
		
		if result == "OK":
			s = utils.getFormattedItemName(data['type'], data)
			utils.Debug("[Tagger] XBMC tags for '%s' were updated with '%s'." % (s, str(data['tag'])))
			utils.notification(utils.getString(1201), utils.getString(1657) % s)

	def manualRemoveFromList(self, list, data):
		if list.lower().startswith("rating:"):
			utils.Debug("[Tagger] '%s' is a reserved list name." % list)
			return

		tag = listToTag(list)
		if not tag in data['tag']:
			utils.Debug("[Tagger] '%d' is not in the list '%s'." % (data['title'], list))
			return
		
		if tag.lower() == "watchlist":
			utils.Debug("[Tagger] Removing: '%s' from Watchlist." % data['title'])
			self.updateWatchlist(data, remove=True)
		else:
			utils.Debug("[Tagger] Removing: '%s' from '%s'." % (data['title'], list))
			self.traktListRemoveItem(list, [data])
		
		data['tag'].remove(tag)
		result = None
		if data['type'] == 'movie':
			result = utils.xbmcJsonRequest({"jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.SetMovieDetails", "params": {"movieid" : data['movieid'], "tag": data['tag']}})
		elif data['type'] == 'show':
			result = utils.xbmcJsonRequest({"jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.SetTVShowDetails", "params": {"tvshowid" : data['tvshowid'], "tag": data['tag']}})
		
		if result == "OK":
			s = utils.getFormattedItemName(data['type'], data)
			utils.Debug("[Tagger] XBMC tags for '%s' were updated with '%s'." % (s, str(data['tag'])))
			utils.notification(utils.getString(1201), utils.getString(1657) % s)


TRAKT_LISTS				= 4
BUTTON_ADD_LIST			= 15
BUTTON_OK				= 16
BUTTON_CANCEL			= 17
MEDIA_LABEL				= 25
ACTION_PREVIOUS_MENU2	= 92
ACTION_PARENT_DIR		= 9
ACTION_PREVIOUS_MENU	= 10 
ACTION_SELECT_ITEM		= 7
ACTION_MOUSE_LEFT_CLICK	= 100
ACTION_CLOSE_LIST		= [ACTION_PREVIOUS_MENU2, ACTION_PARENT_DIR, ACTION_PREVIOUS_MENU]
ACTION_ITEM_SELECT		= [ACTION_SELECT_ITEM, ACTION_MOUSE_LEFT_CLICK]

class traktListDialog(xbmcgui.WindowXMLDialog):

	selectedLists = None
	
	def __new__(cls, lists, data):
		return super(traktListDialog, cls).__new__(cls, "traktListDialog.xml", __addon__.getAddonInfo('path'), lists=lists, data=data) 

	def __init__(self, *args, **kwargs):
		data = kwargs['data']
		lists = kwargs['lists']
		self.data = data
		self.lists = lists
		self.hasRating = False
		self.tags = {}
		for tag in data['tag']:
			if isTraktList(tag):
				t = tagToList(tag)
				if t.startswith("Rating:"):
					self.hasRating = True
					self.ratingTag = t
					continue
				if not t in self.tags:
					self.tags[t] = True

		for tag in lists:
			if not tag in self.tags:
				self.tags[tag] = False

		if (not 'Watchlist' in self.tags) and utils.getSettingAsBool('tagging_watchlists'):
			self.tags['Watchlist'] = False

		super(traktListDialog, self).__init__()

	def onInit(self):
		pl = self.getControl(MEDIA_LABEL)
		pl.setLabel(utils.getFormattedItemName(self.data['type'], self.data))
		
		self.list = self.getControl(TRAKT_LISTS)
		self.populateList()
		self.setFocus(self.list)

	def onAction(self, action):
		if not action.getId() in ACTION_ITEM_SELECT:
			if action in ACTION_CLOSE_LIST:
				self.close()
		if action in ACTION_ITEM_SELECT:
			cID = self.getFocusId() 
			if cID == TRAKT_LISTS:
				item = self.list.getSelectedItem()
				selected = not item.isSelected()
				item.select(selected)
				self.tags[item.getLabel()] = selected

	def onClick(self, control):
		if control == BUTTON_ADD_LIST:
			keyboard = xbmc.Keyboard("", utils.getString(1654))
			keyboard.doModal()
			if keyboard.isConfirmed() and keyboard.getText():
				list = keyboard.getText().strip()
				if list:
					if list.lower() == "watchlist" or list.lower().startswith("rating:"):
						utils.Debug("[Tagger] Dialog: Tried to add a reserved list name '%s'." % list)
						utils.notification(utils.getString(1650), utils.getString(1655) % list)
						return
					if list not in self.tags:
						utils.Debug("[Tagger] Dialog: Adding list '%s', and selecting it." % list)
						self.tags[list] = True
						self.populateList(reset=True)
					else:
						utils.Debug("[Tagger] Dialog: '%s' already in list, selecting it." % list)
						self.tags[list] = True
						self.populateList(reset=True)
						utils.notification(utils.getString(1650), utils.getString(1656) % list)

		elif control == BUTTON_OK:
			data = []
			for i in range(0, self.list.size()):
				item = self.list.getListItem(i)
				if item.isSelected():
					data.append(item.getLabel())
			if self.hasRating:
				data.append(self.ratingTag)
			self.selectedLists = data
			self.close()

		elif control == BUTTON_CANCEL:
			self.close()
	
	def populateList(self, reset=False):
		if reset:
			self.list.reset()
		if 'Watchlist' in self.tags:
			item = xbmcgui.ListItem('Watchlist')
			item.select(self.tags['Watchlist'])
			self.list.addItem(item)
			
		for tag in sorted(self.tags.iterkeys()):
			if tag.lower() == "watchlist":
				continue
			item = xbmcgui.ListItem(tag)
			item.select(self.tags[tag])
			self.list.addItem(item)
