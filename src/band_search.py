#!/usr/bin/env python

import sys, os
import pprint
import threading
import rospy
import datetime
import time
import json

from optparse import OptionParser, OptionGroup
from bson.objectid import ObjectId
from pprint import pprint

from hs_utils import ros_node, logging_utils
from hs_utils import message_converter as mc
from hs_utils import json_message_converter as rj
from hs_utils.mongo_handler import MongoAccess
from MusixMatch import MusixMatch
from SpotifySearch import SpotifySearch
from events_msgs.msg import WeeklyEvents
from events_msgs.msg import WeeklySearch

class BandSearch(ros_node.RosNode):
    def __init__(self, **kwargs):
        try:
            
            ## Use lock to protect list elements from
            ##    corruption while concurrently access. 
            ##    Check Global Interpreter Lock (GIL)
            ##    for more information
            self.threats_lock           = threading.Lock()
            
            ## This variable has to be started before ROS
            ##   params are called
            self.condition              = threading.Condition()

            ## Initialising parent class with all ROS stuff
            super(BandSearch, self).__init__(**kwargs)
            
            self.musix_search           = None
            self.spotify_client         = None
            self.weekly_events          = WeeklyEvents()
            self.api_key                = None
            self.events_collection      = None
            self.database               = None

            ## Initialise node activites
            self.Init()
        except Exception as inst:
              ros_node.ParseException(inst)
              
    def SubscribeCallback(self, msg, topic):
        try:
            if 'weekly_search' in topic:
                self.api_key            = msg.mm_api_key
                self.database           = msg.database
                self.events_collection  = msg.el_collection
                args = {
                    'api_key':      self.api_key,
                    'database':     self.database,
                    'collection':   msg.bs_collection,
                }
                
                if self.api_key is not None:
                    rospy.loginfo("Regenerating MusixMatch API client")
                    self.musix_search = MusixMatch(**args)
                    
                rospy.loginfo("Regenerating Spotify API client")
                self.spotify_client = SpotifySearch(**args)
                    
            elif 'weekly_events' in topic:
                ## Locking incoming message
                with self.threats_lock:
                    rospy.logdebug('  + Setting weekly events')
                    self.weekly_events    = msg

                ## Notify thread that data has arrived
                with self.condition:
                    self.condition.notifyAll()
            else:
                rospy.logwarn('Received unknown message [%s] in topic [%s]'%
                              (str(type(msg))), topic)
            
        except Exception as inst:
              ros_node.ParseException(inst)
              
    def Init(self):
        try:
            ## Setting up MusixMatch event search
            if self.api_key is not None:
                args = {
                    'api_key':      self.api_key,
                    'database':     None,
                    'collection':   None,
                }
                self.musix_search = MusixMatch(**args)
                self.spotify_client = SpotifySearch(**args)
                    
        
            ## Starting publisher thread
            rospy.loginfo('Initialising background thread for band searcher')
            rospy.Timer(rospy.Duration(0.5), self.Run, oneshot=True)
        except Exception as inst:
              ros_node.ParseException(inst)
 
    def Run(self, event):
        ''' Execute this method to... '''
        try:
            ## This event_locator produces calls every 250 ms (40Hz), 
            ##    however we are interested in time passing
            ##    by seconds
            rate_sleep = rospy.Rate(5) 
            
            while not rospy.is_shutdown():
                with self.condition:
                    rospy.loginfo('+ Waiting for incoming data')
                    self.condition.wait()

                if self.musix_search is None:
                    rospy.logwarn('Band search client has not been defined')
                    continue
                
                ## Locking incoming message
                with self.threats_lock:
                    num_events = len(self.weekly_events.events)
                    rospy.loginfo("Looking into [%d] events"%num_events)
                    for i in range(num_events):
                        events      = self.weekly_events.events[i]
                        artist_data = events.artist
                        
                        ## Getting online band information
                        rospy.loginfo('  + Looking for artist/band [%s] in Musix Match'%artist_data.name)
                        artists_info= self.musix_search.search_all(artist_data.name)
                        
                        rospy.loginfo('  + Looking for artist/band [%s] in Spotify'%artist_data.name)
                        spotify_info = self.spotify_client.search(artist_data.name)
                        
                        #####################################################################
                        ### Storing MusixMatch band information
                        posts_id    = self.musix_search.store_events(artists_info)
                        
                        ### Converting to ROS message
                        rospy.logdebug('  + Converting to ROS message')
                        artists_ros = []
                        msg_type    = "events_msgs/MusixMatch"
                        for artist_info in artists_info:
                            
                            ### Removing database ID
                            if '_id' in artist_info.keys():
                                del artist_info['_id']
                            
                            ### ROS message conversion
                            artis_ros = mc.convert_dictionary_to_ros_message(msg_type, artist_info)
                            artists_ros.append(artis_ros)

                        ### Update concerts in weekly events with
                        ###    Musix Match findings
                        rospy.logdebug('  + Update MusixMatch in weekly events ')
                        events.artist.musix_match = artists_ros
                        #self.weekly_events.events[0].artist.musix_match = artists_ros
                        
                        #####################################################################
                        ### Storing Spotify band data
                        rospy.logdebug('  + Update Spotify in weekly events ')
                        spotify_ros_msg = self.spotify_client.parse_events(spotify_info)
                        events.artist.spotify = spotify_ros_msg
                        #self.weekly_events.events[0] = events
                        
                        #####################################################################
                        
                        ## Publishing updated event information
                        week_event = WeeklyEvents()
                        
                        week_event.city         = self.weekly_events.city
                        week_event.country      = self.weekly_events.country
                        week_event.start_date   = self.weekly_events.start_date
                        week_event.end_date     = self.weekly_events.end_date
                        week_event.query_status = self.weekly_events.query_status
                        week_event.total_found  = self.weekly_events.total_found
                        week_event.events_page  = self.weekly_events.events_page
                        week_event.db_record    = self.weekly_events.db_record
                        week_event.events       = [events]
                        self.Publish('/event_locator/updated_events', week_event)
                        rospy.loginfo('-'*80)
                    
#                     ## Update DB record
#                     weeklyEvents= rj.convert_ros_message_to_json(self.weekly_events, debug=False)
#                     weeklyEvents= json.loads(weeklyEvents)
#                     db_record   = ObjectId(weeklyEvents['db_record'])
#                     db_handler  = MongoAccess()
#                     rospy.logdebug('  @ Using [%s] collection in [%s]'%
#                                    ( self.events_collection, self.database))
#                     connected   = db_handler.Connect(self.database, self.events_collection)
#                     
#                     ## Checking if DB connection was successful
#                     if not connected:
#                         rospy.logwarn('Events DB not available')
#                     rospy.logdebug('  @ Update DB record [%s]'%db_record)
#                     cursor      = db_handler.Find({"_id": db_record})
#                     record_num  = cursor.count(with_limit_and_skip=False)
#                     rospy.logdebug('  @ Found [%s] records '%str(record_num))
#                     
#                     ## Checking if record exists
#                     if record_num<1:
#                         rospy.logwarn('Record  was [%s] not available'%str(db_record))
#                         db_record   = db_handler.Insert(weeklyEvents)
#                         updated     = True
#                         rospy.logdebug('  @ Inserting weekly events with record [%s]'%str(db_record))
#                     else:
#                         updated = db_handler.Update(
#                                                 condition   ={"_id": db_record},
#                                                 substitute  ={"events": weeklyEvents['events']}, 
#                                                 upsertValue=False
#                                                )
#                     ## Checking if record update was successful
#                     if not updated:
#                         rospy.logwarn('  @ Record [%s] was not updated'%(str(db_record)))
#                         continue                    
#                     rospy.logdebug('  @ Record [%s] was updated'%(str(db_record)))
# 
#                     ## Closing DB client
#                     db_handler.Close()
        except Exception as inst:
              ros_node.ParseException(inst)
              
if __name__ == '__main__':
    usage       = "usage: %prog option1=string option2=bool"
    parser      = OptionParser(usage=usage)
    parser.add_option('--queue_size',
                type="int",
                action='store',
                default=1000,
                help='Topics to play')
    parser.add_option('--latch',
                action='store_true',
                default=False,
                help='Message latching')
    parser.add_option('--debug',
                action='store_true',
                default=False,
                help='Provide debug level')

    (options, args) = parser.parse_args()
    
    args            = {}
    logLevel        = rospy.DEBUG if options.debug else rospy.INFO
    rospy.init_node('band_search', anonymous=False, log_level=logLevel)
    
    ## Sending logging to syslog
    logging_utils.update_loggers()

    ## Defining static variables for subscribers and publishers
    sub_topics     = [
        ('/event_locator/weekly_events',  WeeklyEvents),
        ('/event_locator/weekly_search',  WeeklySearch)
    ]
    pub_topics     = [
        ('/event_locator/updated_events', WeeklyEvents)
    ]
    system_params  = [
        #'/event_locator_param'
    ]
    
    ## Defining arguments
    args.update({'queue_size':      options.queue_size})
    args.update({'latch':           options.latch})
    args.update({'sub_topics':      sub_topics})
    args.update({'pub_topics':      pub_topics})
    #args.update({'system_params':   system_params})
    
    # Go to class functions that do all the heavy lifting.
    try:
        spinner = BandSearch(**args)
    except rospy.ROSInterruptException:
        pass
    # Allow ROS to go to all callbacks.
    rospy.spin()
