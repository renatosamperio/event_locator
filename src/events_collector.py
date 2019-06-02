#!/usr/bin/env python

import sys, os
import threading
import rospy
import datetime
import time
import json

from optparse import OptionParser, OptionGroup
from pprint import pprint

from hs_utils import ros_node, logging_utils, utilities
from hs_utils import message_converter as mc
from hs_utils import json_message_converter as rj
from hs_utils.mongo_handler import MongoAccess

from events_msgs.msg import WeeklySearch
from events_msgs.msg import WeeklyEvents
from std_msgs.msg import Bool

class EventsCollector(ros_node.RosNode):
    def __init__(self, **kwargs):
        try:
            
            self.condition        = threading.Condition()
            self.is_running       = False
            
            ## Initialising parent class with all ROS stuff
            super(EventsCollector, self).__init__(**kwargs)
            
            ## DB Variables
            self.database        = None
            self.collection      = None
            self.db_handler      = None

            ## Initialise node activites
            self.Init()
        except Exception as inst:
              ros_node.ParseException(inst)
              
    def init_db(self, msg):
        try:
            self.database    = msg.database
            self.collection  = msg.el_collection
            
            ## Creating DB handler
            self.db_handler  = MongoAccess()
            connected        = self.db_handler.Connect(self.database, 
                                                       self.collection)
            ## Checking if DB connection was successful
            if not connected:
                rospy.logwarn('Events DB not available')
            else:
                rospy.loginfo("Created DB handler in %s.%s"%
                              (self.database, self.collection))
                
        except Exception as inst:
              ros_node.ParseException(inst)

    def SubscribeCallback(self, msg, topic):
        try:
            if topic == '/event_finder/clean_events':
                
                rospy.loginfo("Looking for events to clean...")
                if not self.is_running:
                    ## Notify thread that data has arrived
                    with self.condition:
                        self.condition.notifyAll()
            
            elif '/event_finder/weekly_search' in topic:
                ## Connecting to DB
                self.init_db(msg)
                
        except Exception as inst:
              ros_node.ParseException(inst)
      
    def Init(self):
        try:
            rospy.Timer(rospy.Duration(0.2), self.Run)
        except Exception as inst:
              ros_node.ParseException(inst)

    def Run(self, event):
        ''' Run method '''
        try:
            ## Looping while messages are coming
            msg_type    = "events_msgs/WeeklyEvents"
            while not rospy.is_shutdown():
                ## Waiting for new message to come
                with self.condition:
                    rospy.logdebug('Waiting for events to clean')
                    self.condition.wait()
                    
                ## Making sure no more messages would be passed
                self.is_running       = True
                
                ## Checking if DB has been defined
                if self.db_handler is None:
                    rospy.logwarn("No DB as been defined")
                    
                else:
                    ## Looking for expired concerts
                    now   = datetime.datetime.now()
                    today = datetime.datetime(
                                    year    =now.year, 
                                    month   =now.month, 
                                    day     =now.day,
                                    hour    =23,
                                    minute  =59)
                    today_str = str(today)
                    
                    cursor= self.db_handler.Find(
                            { "concert.start_time": { "$lte" : today_str} })

                    for item in cursor:
                        
                        ## Removing database ID
                        if '_id' in item.keys():
                            del item['_id']

                        ## Getting dictionary with python strings
                        item = utilities.convert_to_str(item)
                        
                        ## Getting ROS message
                        ros_msg = mc.convert_dictionary_to_ros_message(msg_type, item)
                        self.Publish('/event_finder/remove_events', ros_msg)
                        
                    ## Closing cursor
                    cursor.close()

                ## Finishing cleaning process
                self.is_running       = False
                rospy.logdebug("Finished processing")
            
        except Exception as inst:
              ros_node.ParseException(inst)

    def ShutdownCallback(self):
        try:
            if self.db_handler is not None:
                rospy.logdebug('+ Shutdown: Closing DB')
                self.db_handler.Close()
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
    parser.add_option('--syslog',
                action='store_true',
                default=False,
                help='Start with syslog logger')

    (options, args) = parser.parse_args()
    
    args            = {}
    logLevel        = rospy.DEBUG if options.debug else rospy.INFO
    rospy.init_node('event_collector', anonymous=False, log_level=logLevel)
    
    ## Sending logging to syslog
    if options.syslog:
        logging_utils.update_loggers()

    ## Defining static variables for subscribers and publishers
    sub_topics     = [
        ('/event_finder/weekly_search',  WeeklySearch),
        ('/event_finder/updated_events', WeeklyEvents),
        ('/event_finder/clean_events',   Bool),
    ]
    pub_topics     = [
        ('/event_finder/remove_events',  WeeklyEvents)
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
        spinner = EventsCollector(**args)
    except rospy.ROSInterruptException:
        pass
    # Allow ROS to go to all callbacks.
    rospy.spin()

