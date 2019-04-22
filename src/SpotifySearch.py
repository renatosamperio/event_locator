#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
import time
import math

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from unidecode import unidecode
from datetime import datetime

from hs_utils import ros_node
from hs_utils.mongo_handler import MongoAccess
from hs_utils import similarity
from hs_utils import message_converter as mc
from events_msgs.msg import Artist
from events_msgs.msg import SpotifyQuery

from optparse import OptionParser, OptionGroup
from pprint import pprint

class SpotifySearch:
    def __init__(self, **kwargs):
        try:
            self.db_handler     = None            
            self.database       = None            
            self.collection     = None       
            self.sp_client         = None 
            self.similarity_gap = 0.75
            
            self.comparator = similarity.Similarity()
            
            ## Generating instance of strategy
            for key, value in kwargs.iteritems():
                if "collection" == key:
                    self.collection = value
                elif "database" == key:
                    self.database = value

            rospy.logdebug("Initialising node")
            self.Init()
        except Exception as inst:
              ros_node.ParseException(inst)
              
    def Init(self):
        
        try:
            ## Checking if instance has been already created
            ## Does the class instance is already created?
            

            # create an instance of the API class
            ##    spotify client credentials should 
            ##    be defined as environment variables
            ##        export SPOTIPY_CLIENT_ID=xxxxx
            ##        export SPOTIPY_CLIENT_SECRET=yyyyy
            rospy.loginfo("Creating SpotifySearch API client")
            client_credentials_manager = SpotifyClientCredentials()
            self.sp_client = spotipy.Spotify(client_credentials_manager=client_credentials_manager)
                
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
        
    def search(self, q_artist):
        '''
            Searches along all artists pages
        '''
        artists_found = []
        artist_chosen = None
        try:
            ## Collecting all results
            results         = self.sp_client.search(q='artist:' + q_artist, type='artist')
            artists         = results['artists']
            artists_found   = artists['items']
            while artists['next']:
                results = self.sp_client.next(artists)
                artists = results['artists']
            artists_found.extend(artists['items'])
            rospy.loginfo('  Found [%d] items for [%s]'%(len(artists_found), q_artist))
            
            ## Searching for a perfect match and the most followers
            highest_followes= 0.0
            for artist in artists_found:
                artist_name = artist['name']
                
                ## Getting for similarity score
                score               = self.comparator.score(artist_name.lower(), 
                                                            q_artist.lower(),
                                                            debug=False)
                artist.update({'similarity_score':score})
                
                ## Keeping similar names with highest followers
                if score>=self.similarity_gap:
                    total_followers = artist['followers']['total']
                    if total_followers > highest_followes:
                        rospy.logdebug('  Looking into [%s] with [%d] followers'%
                                       (artist_name, total_followers))
                        highest_followes = total_followers
                        artist_chosen = artist

            ## Looking for top tracks and removing useless variables
            if artist_chosen is not None:
                
                ## Filtering followers
                artist_chosen['followers']  = artist_chosen['followers']['total']
                
                ## Getting image if it exists
                artist_image  = {}
                if len(artist_chosen['images'])>0:
                    artist_image  = artist_chosen['images'][0]
                artist_chosen['image']  = artist_image
                
                ## Removing variables
                del artist_chosen['external_urls']
                del artist_chosen['href']
                del artist_chosen['images']
                del artist_chosen['type']
                
                ## Collecting top tracks
                top_tracks  = []
                urn         = artist_chosen['uri']
                response    = self.sp_client.artist_top_tracks(urn)
                for track in response['tracks']:
                    top_track = {
                        'album_image'         : track['album']['images'][0],
                        'album_name'          : track['album']['name'],
                        'album_id'            : track['album']['id'],
                        'album_release_date'  : track['album']['release_date'],
#                         'artists_id'          : track['artists'][0]['id'],
                        'song_name'           : track['name'],
                        'preview_url'         : track['preview_url'],
                        'popularity'          : track['popularity'],
                        'duration_ms'         : track['duration_ms']
                    }
                    top_tracks.append(top_track)
                rospy.loginfo('    Got [%d] top tracks'%(len(top_tracks)))
                artist_chosen.update({'top_tracks':top_tracks})
        except Exception as inst:
              ros_node.ParseException(inst)
        finally:
            return artist_chosen

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
            
            ## inserting dictionary as DB record
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

    def parse_events(self, spotify_info):
        spotify_ros_msg = SpotifyQuery()
        try:
            if spotify_info is None:
                return spotify_ros_msg
            
            ## Manual conversions for top track
            tt_list = []
            
            for top_tracks in spotify_info['top_tracks']:
                ## Converting album image
                album_info = {
                    'album_id':             unidecode(top_tracks['album_id']),
                    'album_name':           unidecode(top_tracks['album_name']),
                    'album_release_date':   unidecode(top_tracks['album_release_date']),
                    'duration_ms':          top_tracks['duration_ms'],
                    'popularity':           top_tracks['popularity'],
                    'preview_url':          '' if top_tracks['preview_url'] is None else unidecode(top_tracks['preview_url']),
                    'song_name':            unidecode(top_tracks['song_name']),
                    'album_image':  {
                        'height':           top_tracks['album_image']['height'],
                        'width':            top_tracks['album_image']['width'],
                        'url':              unidecode(top_tracks['album_image']['url']),
                    },
                }
                
                ## Converting track info
                msg_type        = "events_msgs/SpotifyTracks"
                tt_msg          = mc.convert_dictionary_to_ros_message(msg_type, album_info)
                
                ## Adding tracks
                tt_list.append(tt_msg)
            
            ## album image conversion
            
            spotify_search = {
                'name':             unidecode(spotify_info['name']),
                'uri':              unidecode(spotify_info['uri']),
                'id':               unidecode(spotify_info['id']),
                'followers':        spotify_info['followers'],
                'genres':           spotify_info['genres'],
                'popularity':       spotify_info['popularity'],
                'similarity_score': spotify_info['similarity_score'],
                'image': {
                       'height':    spotify_info['image']['height'],
                       'width':     spotify_info['image']['width'],
                       'url':       unidecode(spotify_info['image']['url']),
                   },

            }
            ## Converting dictionary to ROS message
            msg_type        = "events_msgs/SpotifyQuery"
            spotify_ros_msg = mc.convert_dictionary_to_ros_message(msg_type, spotify_search)
            
            ## Adding track list manually
            spotify_ros_msg.top_tracks = tt_list

        except Exception as inst:
            ros_node.ParseException(inst)
        finally:
            return spotify_ros_msg

if __name__ == '__main__':
    usage       = "usage: %prog option1=string option2=bool"
    parser      = OptionParser(usage=usage)
    parser.add_option('--debug',
                action='store_true',
                default=False,
                help='Provide debug level')
    event_group = OptionGroup(parser, 'Event search parameters')
    io_group    = OptionGroup(parser, 'Event I/O parameters')
    
    event_group.add_option('--artist_query',
                type="string",
                action='store',
                default='Tool',
                help='A starting date in the form YYYY-MM-DD.')
    
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

    logLevel        = rospy.DEBUG if options.debug else rospy.INFO
    rospy.init_node('event_locator_sfl', anonymous=False, log_level=logLevel)
        
    try:
        args = {
            'database':     options.database,
            'collection':   options.collection,
        }
        
        rospy.logdebug("Crating event finder")
        spotify_finder       = SpotifySearch(**args)
        
        ## Searching for band
        artists = spotify_finder.search(options.artist_query)
        pprint(artists)
    except Exception as inst:
          ros_node.ParseException(inst)
