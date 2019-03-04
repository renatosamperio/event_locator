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

from hs_utils import ros_node
from hs_utils import message_converter as mc
from hs_utils import json_message_converter as rj
from hs_utils.mongo_handler import MongoAccess
from YoutubeSearch import YoutubeSearch
from events_msgs.msg import WeeklyEvents

class MusicCollection(ros_node.RosNode):
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
            super(MusicCollection, self).__init__(**kwargs)
            
            self.musix_search           = None
            self.youtube_client         = None
            self.updated_events         = WeeklyEvents()
            self.api_key                = 'AIzaSyDwTQTUC9CGvqqJjTmPA1KX65EmALWGNRc'
            self.events_collection      = None
            self.database               = None

            ## Initialise node activites
            self.Init()
        except Exception as inst:
              ros_node.ParseException(inst)
              
    def SubscribeCallback(self, msg, topic):
        try:
            ## Locking incoming message
            with self.threats_lock:
                rospy.logdebug('  + Setting weekly events')
                self.updated_events    = msg

            ## Notify thread that data has arrived
            with self.condition:
                self.condition.notifyAll()
            
        except Exception as inst:
              ros_node.ParseException(inst)
              
    def Init(self):
        try:
            ## Setting up MusixMatch event search
            if self.api_key is not None:
                args = {
                    'api_key':      'AIzaSyDwTQTUC9CGvqqJjTmPA1KX65EmALWGNRc',
                    'database':     None,
                    'collection':   None,
                }
                
                ## Initialising youtube client
                self.youtube_client = YoutubeSearch(**args)

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

                ## Locking incoming message
                with self.threats_lock:
                    if self.updated_events.query_status != 'ok':
                        rospy.loginfo("Received query is [%s]"%self.updated_events.query_status)
                        continue
                    
                    rospy.logdebug("Got events from [%s, %s] from [%s] to [%s]"%
                                   (self.updated_events.city, self.updated_events.country,
                                    self.updated_events.start_date, self.updated_events.end_date))
                    
                    for event in self.updated_events.events:
                        if len(event.artist.spotify.name)>0:
                            artst_name = event.artist.spotify.name
                        else:
                            artst_name = event.artist.name
                            rospy.loginfo("Artist [%s] not found in spotify"%artst_name)
                            continue
                        
                        ## Looking for songs in Spotify
                        rospy.loginfo("  Artist [%s] is playing in [%s] at [%s]"%
                                       (artst_name, event.venue.name, self.updated_events.city))
                        
                        for top_track in event.artist.spotify.top_tracks:
                            youtube_query   = artst_name+" - "+top_track.song_name
                            rospy.logdebug("+ Looking for videos of [%s]"%youtube_query)
                            
                            videos          = self.youtube_client.search(youtube_query)
#                             pprint (videos)
#                             print "-"*100
                            for video in videos:
                                rospy.logdebug("    Got video [%s] with [%s] views and duration [%s]"%
                                               (video['title'], 
                                                video['statistics']['viewCount'], 
                                                video['duration']))
                        #break
#                         pprint(event)
#                         print "-"*100
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
    rospy.init_node('music_collection', anonymous=False, log_level=logLevel)
        
    ## Defining static variables for subscribers and publishers
    sub_topics     = [
        ('/event_locator/updated_events', WeeklyEvents)
    ]
    pub_topics     = [
    ]
    system_params  = [
    ]
    
    ## Defining arguments
    args.update({'queue_size':      options.queue_size})
    args.update({'latch':           options.latch})
    args.update({'sub_topics':      sub_topics})
    args.update({'pub_topics':      pub_topics})
    #args.update({'system_params':   system_params})
    
    # Go to class functions that do all the heavy lifting.
    try:
        spinner = MusicCollection(**args)
    except rospy.ROSInterruptException:
        pass
    # Allow ROS to go to all callbacks.
    rospy.spin()
