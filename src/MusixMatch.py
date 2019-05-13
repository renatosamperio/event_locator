#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
import time
import math

import swagger_client
from unidecode import unidecode
from swagger_client.rest import ApiException
from datetime import datetime

from Finder import Finder
from hs_utils import ros_node
from hs_utils.mongo_handler import MongoAccess
from hs_utils import similarity
#from events_msgs.msg import Artist
#from events_msgs.msg import MusixMatch

from optparse import OptionParser, OptionGroup
from pprint import pprint

# # 200     The request was successful.
# # 400     The request had bad syntax or was inherently impossible to be satisfied.
# # 401     Authentication failed, probably because of a bad API key.
# # 402     A limit was reached, either you exceeded per hour requests limits or your balance is insufficient.
# # 403     You are not authorized to perform this operation or the api version you’re trying to use has been shut down.
# # 404     Requested resource was not found.
# # 405     Requested method was not found.

## TODO: Check for a recent updated_time
class MusixMatch(Finder):
    def __init__(self, **kwargs):
        try:
            ## Initialising parent class
            super(MusixMatch, self).__init__(**kwargs)
            
            self.db_handler     = None            
            self.database       = None            
            self.collection     = None       
            self.api_key        = None    
            self.api_instance   = None 
            self.page_size      = 100    
            self.similarity_gap = 0.90
            
            self.comparator = similarity.Similarity()
            self.base_url   = 'https://api.musixmatch.com/ws/1.1/'
            
            ## Generating instance of strategy
            for key, value in kwargs.iteritems():
                if "collection" == key:
                    self.collection = value
                elif "database" == key:
                    self.database = value
                elif "api_key" == key:
                    self.api_key = value

            rospy.logdebug("Initialising node")
            self.Init()
        except Exception as inst:
              ros_node.ParseException(inst)
              
    def Init(self):
        
        try:
            ## Checking if instance has been already created
            ## Does the class instance is already created?
            

            # create an instance of the API class
            rospy.loginfo("Creating MusixMatch API client")
            swagger_client.configuration.api_key['apikey'] = self.api_key
            self.api_instance = swagger_client.ArtistApi()
                
            ## Check if database and collection are different to current one
            if self.database is not None and self.collection is not None :
                rospy.logdebug("  + Connecting to [%s] with [%s] collections"% 
                                (self.database, self.collection))
                self.db_handler = MongoAccess()
                isConnected = self.db_handler.Connect(self.database, self.collection)
                
                if isConnected:
                    ## Check for indexes
                    add_index = True
                    rospy.logdebug("  + Collecting indexes from [%s] with [%s] collections"% 
                                    (self.database, self.collection))
                    indexes = self.db_handler.collection.index_information()
                    if 'name_text' in indexes.keys():
                            add_index = False
                            rospy.logdebug("  +   Index [name_text] already exists")
    
                    # Creating text index
                    if add_index:
                        rospy.logdebug('  + Creating text index in "name"')
                        indexCreated = self.db_handler.CreateIndex('name', 'text')
                        
                        if indexCreated:
                            rospy.logdebug('"  +   Index [name_text] was created')
                
                ## If Db not reached, does remove accessibility
                else:
                    rospy.logwarn("DB client failed to connect") 
                    self.database   = None            
                    self.collection = None
            else:
                rospy.logwarn("Database has not been defined")

        except Exception as inst:
              ros_node.ParseException(inst)
        
    def search(self, q_artist, result, accum=0):
        '''
            Gets a list of events from Eventful
        '''
        #result      = []
        score       = 0
        
        if self.api_instance is None:
            rospy.logwarn("API client has not initialised") 
            return
        try:
            
            ## Available formats: str | output format: json, jsonp, xml. 
            ##    (optional) (default to json)
            format                  = 'json' 
            current_page            = (accum / self.page_size) + 1
            
            rospy.logdebug('  Searching in page [%d]...'%current_page)
            api_response= self.api_instance.artist_search_get(format=format, 
#                                                   callback=callback, 
                                                    q_artist=q_artist, 
#                                                   f_artist_id=f_artist_id, 
                                                    page=current_page, 
                                                    page_size=self.page_size
                                                  )
            
            ## Interrupting search if things go wrong
            if api_response._message.header.status_code != 200:
                rospy.logwarn("Error [%s] in musix match request for [%s]"%(
                              str(int(api_response._message.header.status_code)),  q_artist ))
                pprint(api_response)
                accum = None
                return
            
            ## Collecting initial information
            body                    = api_response._message.body
            execute_time            = api_response._message.header.execute_time
            available               = int(api_response._message.header.available)
            artist_list             = body.artist_list
            counter                 = 0
            rospy.logdebug('  Got [%d] records'% available)
            
            ## Looping in found artists
            for artist_element in artist_list:
                counter             += 1
                artist              = artist_element.artist
                
                ## Filtering artist information
                artist_name         = unidecode(artist.artist_name)
                artist_id           = str(artist.artist_id)
                artist_rating       = artist.artist_rating
                artist_mbid         = '' if artist.artist_mbid is None else str(artist.artist_mbid)
                primary_genres      = artist.primary_genres
                artist_country      = unidecode(artist.artist_country)
                artist_twitter_url  = artist.artist_twitter_url
                updated_time        = unidecode(artist.updated_time)
                
                ## Looking for similarity score
                score               = self.comparator.score(artist_name, q_artist)

                ## Looking for aliases
                artist_alias_list   = []
                if artist.artist_alias_list is not None:
                    for artist_alias_element in artist.artist_alias_list:
                        artist_alias= unidecode(artist_alias_element.artist_alias)
                        ## If there is already something in the list of 
                        ##     found results, do an average weight
                        if len(result)>0: 
                            alias_score = self.comparator.score(artist_alias, q_artist)
                            score       = (score+alias_score )/2
                        artist_alias_list.append(artist_alias)
                
                ## Getting available genre music
                artist_music_genre_list  = []
                if primary_genres is not None:
                    music_genre_list    = primary_genres.music_genre_list
                    for music_genre_element in music_genre_list:
                        music_genre     = music_genre_element.music_genre
                        
                        music_genre_id  = music_genre.music_genre_id
                        music_genre_name= music_genre.music_genre_name
                        artist_music_genre = {
                            'music_genre_id':   music_genre_id,
                            'music_genre_name': music_genre_name,
                        }
                        artist_music_genre_list.append(artist_music_genre)
                
                ## Keeping all artist for a while?
                if score>=self.similarity_gap:
#                     print "="*100
#                     print "=== updated_time:", artist.updated_time
#                     print "=== score:", score
                    current_result = {
                        'id':            artist_id,
                        'mbid':          artist_mbid,
                        'artist_alias':  artist_alias_list,
                        'music_genre':   artist_music_genre_list,
                        'country':       unidecode(artist_country),
                        'name':          artist_name,
                        'query_score':   score,
                        'rating':        artist_rating,
                        'twitter_url':   artist_twitter_url,
                        'updated_time':  updated_time
                    }
                    
                    ## If names are exactly the same, check for latest
                    ##    updated item
                    if score == 1.00:
                        ## Store item if list is empty, otherwise check for 
                        ##    scores in existing items
                        if len(result)>0:
                            currDate = datetime.strptime(updated_time, '%Y-%m-%dT%H:%M:%SZ')
#                             print "RESPONSE_ORIGINAL_ARTIST ---", len(result)
#                             pprint(artist)
                            for i in range(len(result)):
                                item = result[i]
#                                 print "~"*80
#                                 print "STORED_ITEM"
#                                 pprint(item)
                                ## Decide which is the latest item that was 
                                ##    added but only for perfect matches
                                if item['query_score'] == 1.0:
                                    try:
                                        storeDate = datetime.strptime(item['updated_time'], '%Y-%m-%dT%H:%M:%SZ')
#                                         print "===> currDate:",currDate
#                                         print "===> (",currDate," < ",storeDate,") == ", (currDate<storeDate)
                                        if currDate<=storeDate:
                                            rospy.logdebug('  Keeping stored instead of stored with [%s]'%item['updated_time'])
                                        else:
                                            rospy.logdebug('  Replacing current instead of stored with [%s]'%updated_time)
                                            result[i] = current_result
#                                             print "RESULT"
#                                             pprint(result)
                                            break
                                            
                                    except Exception as inst:
                                        ros_node.ParseException(inst)
#                                     print "-"*100
                        else:
                            rospy.logdebug('  Appending current to list with [%s]'%updated_time)
                            result.append(current_result)
                    rospy.loginfo("  [%d of %d] Found: %s: %f"
                               %(counter+accum, available, artist_name, score))

                else:
                    rospy.logdebug("  [%d of %d] Found: %s: %f"
                               %(counter+accum, available, artist_name, score))
                
                
            ## Counting items and defining next page command
            accum += counter            
            rospy.loginfo('  Processed [%d of %d] items'%(accum, available))
            if accum>= available:
                accum = None

        except Exception as inst:
              ros_node.ParseException(inst)
        finally:
            return result, accum

    def search_all(self, q_artist):
        '''
            Search in all pages for an artist
        '''
        if self.api_instance is None:
            rospy.logwarn("API client has not initialised") 
            return
        found_artist    = []
        try:
            ## Search if artist already exists in DB
            if self.db_handler is not None:
                ## Look artists with lower case
                lower_case_artist = q_artist    
                
                ## db.articles.find( { $text: { $search: "coffee",$caseSensitive :false } } ) //FOR INSENSITIVITY
                cursor      = self.db_handler.Find({ '$text': { '$search': q_artist, "$caseSensitive" :False } })
                #cursor      = self.db_handler.Find({"name" : "/"+q_artist+"/i"})
                record_num  = cursor.count(with_limit_and_skip=False)
    
                if record_num > 0:
                    for item in cursor:
                        ## Removing database ID
                        if '_id' in item.keys():
                            del item['_id']
                            
                        ## Making manual conversions
                        item['id']              = str(item['id'])
                        item['mbid']            = '' if item['mbid'] is None else str(item['mbid'])
                        item['country']         = str(item['country'])
                        item['name']            = str(item['name'])
                        item['artist_alias']    = [unidecode(a) for a in item['artist_alias']]
                        item['updated_time']    = str(item['updated_time'])
                        ## Getting element data
                        found_artist.append(item)
                    rospy.loginfo('      Total [%d] band records retrieved from DB'%record_num)
                    return
                else:
                    rospy.loginfo('      No DB record found for [%s]'%q_artist)

            ## Getting initial search item
            _accum          = None
            rospy.logdebug('  Online search has started for [%s]'%q_artist)
            artists, _accum = self.search(q_artist, found_artist)
            while _accum is not None:
                # rospy.loginfo_once("Processing artist search...")
                artists, _accum = self.search(q_artist, found_artist, accum=_accum)
            
            rospy.loginfo('      Found [%d] items like [%s] in MusixMatch'
                          %(len(found_artist), q_artist))
        except Exception as inst:
              ros_node.ParseException(inst)
        finally:
            return found_artist

    def store_events(self, artists):
        ## Check if database has been defined
        if self.database is None or self.collection is None :
            rospy.logwarn("Band storing stopped, database has not been defined")
            return

        try:
            posts_id = []
            if artists is None:
                rospy.logwarn('Could not bands, invalid record')
                return
            
            ## Inserting dictionary as DB record
            for band_info in artists:
                
                ## Looking if band already exists in DB
                cursor      = self.db_handler.Find({"name" : band_info['name']})
                if cursor.count(with_limit_and_skip=False) > 0:
                    rospy.logdebug('  Band [%s] already exists in DB'%band_info['name'])
                    continue
                
                ## Insert band in database
                post_id = self.db_handler.Insert(band_info)
                if post_id is not None:
                   rospy.logdebug('  Inserted record [%s]'%str(post_id))
                   posts_id.append(post_id)
                else:
                   rospy.logwarn('  Record not inserted in DB')

        except Exception as inst:
            ros_node.ParseException(inst)
        finally:
            return posts_id

    def parse_events(self, artists):
        artists_msgs = []
        try:
            for band_info in artists:
                artists_msgs.append(band_info )
        except Exception as inst:
            ros_node.ParseException(inst)
        finally:
            return artists_msgs

if __name__ == '__main__':
    usage       = "usage: %prog option1=string option2=bool"
    parser      = OptionParser(usage=usage)
    parser.add_option('--debug',
                action='store_true',
                default=False,
                help='Provide debug level')
    parser.add_option('--search',
                action='store_true',
                default=False,
                help='Search for events')
    parser.add_option('--search_all',
                action='store_true',
                default=True,
                help='Search for events')

    event_group = OptionGroup(parser, 'Event search parameters')
    io_group    = OptionGroup(parser, 'Event I/O parameters')
    
    event_group.add_option('--artist_query',
                type="string",
                action='store',
                default='Tool',
                help='A starting date in the form YYYY-MM-DD.')
    event_group.add_option('--api_key',
                type="string",
                action='store',
                default=None,
                help='Eventful API key')
    
    
    io_group.add_option('--database',
                type="string",
                action='store',
                default='events',
                help='Provide a valid database name')
    io_group.add_option('--collection',
                type="string",
                action='store',
                default='bands',
                help='Provide a valid collection name')

    parser.add_option_group(event_group) 
    parser.add_option_group(io_group) 
    (options, args) = parser.parse_args()
    
    if options.api_key is None:
        parser.error("Missing required option: --api_key='ASDASDASD'")

    logLevel        = rospy.DEBUG if options.debug else rospy.INFO
    rospy.init_node('event_locator_sfl', anonymous=False, log_level=logLevel)
        
    try:
        args = {
            'api_key':      options.api_key,
            'database':     options.database,
            'collection':   options.collection,
        }
        
        rospy.logdebug("Crating event finder")
        artist_finder       = MusixMatch(**args)
        
        if options.search_all:
            ## Searching for band
            artists = artist_finder.search_all(options.artist_query)
            
            ## Storing band information
            posts_id = artist_finder.store_events(artists)
            pprint(artists)
            pprint(posts_id)
        elif options.search:
            artists, next_page  = artist_finder.search(options.artist_query)
        else:
            parser.error("Missing required option: --search_all or --search")
    except Exception as inst:
          ros_node.ParseException(inst)
