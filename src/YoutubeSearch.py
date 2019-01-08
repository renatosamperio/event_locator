#!/usr/bin/env python
# -*- coding: utf-8 -*-

## Usage:
##    rosrun event_locator YoutubeSearch.py --debug --api_key xxx --query_search Tool --max_results 3

import eventful
import rospy
import datetime
import time
import math

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from unidecode import unidecode
from hs_utils import ros_node
from hs_utils import message_converter as mc
from hs_utils.mongo_handler import MongoAccess
from events_msgs.msg import WeeklyEvents

from optparse import OptionParser, OptionGroup
from pprint import pprint

class YoutubeSearch:
    def __init__(self, **kwargs):
        try:

            self.api_key            = None
            self.api_service_name   = 'youtube'
            self.api_version        = 'v3'
            self.client             = None
            self.database           = None
            self.collection         = None
            
            ## Generating instance of strategy
            for key, value in kwargs.iteritems():
                if "api_key" == key:
                    self.api_key = value
                elif "database" == key:
                    self.database = value
                elif "collection" == key:
                    self.collection = value

            rospy.loginfo("Initialising node")
            self.Init()
        except Exception as inst:
            ros_node.ParseException(inst)
              
    def Init(self):
        
        try:
            if self.api_key is not None:
                rospy.loginfo("Creating YoutubeSearch API client")
                self.client = build(self.api_service_name, self.api_version,
                    developerKey=self.api_key)
            else:
                rospy.logwarn("YoutubeSearch API client has not been started")

            ## Check if database and collection are different to current one
            if self.database is not None and self.collection is not None :
                rospy.logdebug("  + Connecting to [%s] with [%s] collections"% 
                                (self.database, self.collection))
                self.db_handler = MongoAccess()
                isConnected = self.db_handler.connect(self.database, self.collection)
                
                ## If Db not reached, does remove accessibility
                if not isConnected:
                    rospy.logwarn("DB client failed to connect") 
                    self.database   = None            
                    self.collection = None
            else:
                rospy.logwarn("Database has not been defined")

        except Exception as inst:
            ros_node.ParseException(inst)

    def search(self, query_search, maxResults=50):
        '''
            Gets a list of events from Eventful
        '''
        if self.api_key is None:
            rospy.logwarn("Search event stopped, YoutubeSearch API client has not been started")
            return

        videos = []
        try:

            # Call the search.list method to retrieve results matching the specified
            # query term.
            search_response = self.client.search().list(
                q               = query_search,
                part            = 'id',
                maxResults      = maxResults,
                type            = 'video',
                order           = 'relevance',
                videoDuration   = 'medium'  ## Only include videos that are between 
                                            ## four and 20 minutes long (inclusive).'
            ).execute()
            
            # Add each result to the appropriate list, and then display the lists of
            # matching videos, channels, and playlists.
            for search_result in search_response.get('items', []):
                if search_result['id']['kind'] == 'youtube#video':
                    video_id   = search_result['id']['videoId']
                    video_info = self.get_video_data(video_id)
                    videos.append(video_info)
                else:
                    print "===> type:", search_result['snippet']['title']

        except Exception as inst:
            ros_node.ParseException(inst)
        finally:
            return videos

    def get_video_data(self, video_id):
        '''
            Gets a list of events from Eventful
        '''
        if self.api_key is None:
            rospy.logwarn("Search event stopped, YoutubeSearch API client has not been started")
            return

        video_info = {}
        try:

            # Call the video list to retrieve information
            search_response = self.client.videos().list(
                part='snippet,contentDetails,statistics',
                id=video_id
            ).execute()

            ## Get video statistics and more details
            for search_result in search_response.get('items', []):
                video_info.update({
                    'duration':   search_result['contentDetails']['duration'],
                    'publishedAt':search_result['snippet']['publishedAt'],
                    'title':      unidecode(search_result['snippet']['title']),
                    'thumbnails': search_result['snippet']['thumbnails'],
                    'description':search_result['snippet']['description'],
                    'statistics': search_result['statistics'],
                    'id':         search_result['id'],
                })
                
                if 'tags' in search_result['snippet'].keys():
                    video_info.update({
                        'tags':   search_result['snippet']['tags'],
                    })

        except Exception as inst:
            ros_node.ParseException(inst)
        finally:
            return video_info

    def search_all(self):
        
        if self.api_key is None:
            rospy.logwarn("Weekly search event stopped, YoutubeSearch API client has not been started")
            return
        
        try:
            ## Getting first one to calculate all
            page = 1
            rospy.loginfo('Finished search')
        except Exception as inst:
            ros_node.ParseException(inst)
        return events

    def parse_events(self, results):
        parsed_result = {}
        cparsed_message = Concert()
        try:
            
            ## Collecting event relevant information
            event           = results['event']
            
            ## Parsing event response
            parsed_result = {
                'event':        event,
            }
            ## Manual conversions
            message_type    = "events_msgs/Concert"
            cparsed_message = mc.convert_dictionary_to_ros_message(message_type, parsed_result)

        except Exception as inst:
            ros_node.ParseException(inst)
        finally:
            return cparsed_message

    def store_events(self, band_msg):
        ## Check if database has been defined
        if self.database is None or self.collection is None :
            rospy.logwarn("Event storing stopped, database has not been defined")
            return

        post_id = ''
        try:
            if band_msg is None:
                rospy.logwarn('Could not store Youtube band info, invalid record')
                return
            
            ## Converting ROS message into dictionary
            band_info = mc.convert_ros_message_to_dictionary(band_msg)
            
            ## inserting dictionary as DB record
            post_id = self.db_handler.Insert(band_info)
            if post_id is not None:
               rospy.logdebug('  Inserted record [%s]'%str(post_id))
            else:
               rospy.logwarn('  Record not inserted in DB')

        except Exception as inst:
            ros_node.ParseException(inst)
        finally:
            return post_id

    def set_search(self, weekly_search):
        result = True
        try:
            rospy.loginfo("Setting search options")
            self.start_date = weekly_search.start_date
            
            ## Reinitialising connection
            self.Init()
        except Exception as inst:
            result = True
            ros_node.ParseException(inst)
        finally:
            return result

if __name__ == '__main__':
    ## Getting today's date
    start_date  = datetime.datetime.now()
    end_date    = start_date + datetime.timedelta(days=7)
    
    usage       = "usage: %prog option1=string option2=bool"
    parser      = OptionParser(usage=usage)
    parser.add_option('--debug',
                action='store_true',
                default=False,
                help='Provide debug level')

    search_group = OptionGroup(parser, 'Event search parameters')
    io_group    = OptionGroup(parser, 'Event I/O parameters')
    
    search_group.add_option('--query_search',
                type="string",
                action='store',
                default=None,
                help='Youtube search query')
    search_group.add_option('--max_results',
                type="int",
                action='store',
                default=50,
                help='Valid range 1 to 50')
    search_group.add_option('--api_key',
                type="string",
                action='store',
                default=None,
                help='Youtube API key')
    
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
    
    parser.add_option_group(search_group) 
    parser.add_option_group(io_group) 
    (options, args) = parser.parse_args()
    
    if options.api_key is None:
        parser.error("Missing required option: --api_key='ASDASDASD'")
        
    if options.query_search is None:
        parser.error("Missing required option: --query_search='Super Band'")
        
    logLevel        = rospy.DEBUG if options.debug else rospy.INFO
    rospy.init_node('youtube_search', anonymous=False, log_level=logLevel)
        
    try:
        args = {
            'api_key':      options.api_key,
            'database':     options.database,
            'collection':   options.collection,
        }
        
        rospy.logdebug("Calling Youtube Search Client")
        youtube_search = YoutubeSearch(**args)
        
        videos = youtube_search.search(options.query_search, maxResults=options.max_results)

        for video in videos:
            pprint(video)
            print "~"*100
    except Exception as inst:
          ros_node.ParseException(inst)
