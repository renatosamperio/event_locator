#!/usr/bin/env python

import sys, os
import threading
import rospy
import datetime
import time
import json
import Queue

from optparse import OptionParser, OptionGroup
from pprint import pprint

from hs_utils import ros_node, logging_utils
from SongKick import SongKick
from events_msgs.msg import WeeklyEvents
from events_msgs.msg import WeeklySearch

class EventLocator(ros_node.RosNode):
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
            self.weekly_searches        = Queue.Queue()

            ## Initialising parent class with all ROS stuff
            super(EventLocator, self).__init__(**kwargs)
            
            self.event_finder           = None

            ## Initialise node activites
            self.Init()
        except Exception as inst:
              ros_node.ParseException(inst)
              
    def SubscribeCallback(self, msg, topic):
        try:
            if self.event_finder is None:
                rospy.logwarn("Event client has not been initialised")
                return
            
            ## Setting up search query
            self.weekly_searches.put(msg)
            
            ## Notify thread that data has arrived
            with self.condition:
                self.condition.notifyAll()
            
        except Exception as inst:
              ros_node.ParseException(inst)
              
    def Init(self):
        try:
            ## Setting up SongKick event search
            args = {
                'location':     None,
                'api_key':      None,
                'start_date':   None,
                'end_date':     None,
                'database':     'events',
                'collection':   'concerts',
                'publisher_cb': self.PublishEvent
            }
            self.event_finder = SongKick(**args)
        
            ## Starting publisher thread
            rospy.loginfo('Starting event finder')
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
                    rospy.logdebug('+ Waiting for incoming data')
                    self.condition.wait()

                while not self.weekly_searches.empty():
                    weekly_search = self.weekly_searches.get()
                    ok = self.event_finder.set_search(weekly_search)
                    if not ok:
                        rospy.logwarn('Failed to set search info')
                        break
                    
                    rospy.loginfo("Searching for weekly events")
                    events = self.event_finder.search_all()
                 
#                 ## Storing weekly events in DB
#                 post_id = self.event_finder.store_events(events)
#                 
#                 ## Added DB record ID to ROS message
#                 events.db_record = str(post_id)
#                 self.Publish('~weekly_results', events)

        except Exception as inst:
              ros_node.ParseException(inst)

    def PublishEvent(self, msg):
        self.Publish('~found_events', msg) 

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
    parser.add_option('--syslog',
                action='store_true',
                default=False,
                help='Provide debug level')

    (options, args) = parser.parse_args()
    
    args            = {}
    logLevel        = rospy.DEBUG if options.debug else rospy.INFO
    rospy.init_node('event_finder', anonymous=False, log_level=logLevel)
    
    ## Sending logging to syslog
    if options.syslog:
        logging_utils.update_loggers()
        
    ## Defining static variables for subscribers and publishers
    sub_topics     = [
        ('~weekly_search',  WeeklySearch)
    ]
    pub_topics     = [
        ('~found_events',  WeeklyEvents)
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
        spinner = EventLocator(**args)
    except rospy.ROSInterruptException:
        pass
    # Allow ROS to go to all callbacks.
    rospy.spin()
