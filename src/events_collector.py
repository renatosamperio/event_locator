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

from hs_utils import ros_node, logging_utils, utilities
from hs_utils import message_converter as mc
from hs_utils import json_message_converter as rj
from hs_utils.mongo_handler import MongoAccess

from events_msgs.msg import WeeklySearch
from events_msgs.msg import WeeklyEvents
from std_msgs.msg import Bool
from std_msgs.msg import String

class EventsCollector(ros_node.RosNode):
    def __init__(self, **kwargs):
        try:
            
            self.update_condition = threading.Condition()
            self.db_condition     = threading.Condition()
            self.condition        = threading.Condition()
            self.db_queue         = Queue.Queue()
            self.update_queue     = Queue.Queue()
            self.is_running       = False
            
            ## Initialising parent class with all ROS stuff
            super(EventsCollector, self).__init__(**kwargs)
            
            ## DB Variables
            self.database         = None
            self.collection       = None
            self.db_handler       = None
              
            for key, value in kwargs.iteritems():
                if "database" == key:
                    self.database = value
                elif "collection" == key:
                    self.collection = value

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

    def update_db_info(self, weekly_event):
        
        result = False
        try:
            json_msg = rj.convert_ros_message_to_json(weekly_event, debug=False)
            json_msg = json.loads(json_msg)
            json_msg = utilities.convert_to_str(json_msg)
#             print "===> json_msg.type:", type(json_msg)
#             pprint(json_msg)
            json_msg.update({'post_status': 'collected'})
            event_id    = json_msg['concert']['event_id']
            
            ## If DB is not defined returns False
            if self.db_handler is None:
                rospy.logwarn("DB: No DB as been defined")
                return
            cursor      = self.db_handler.Find(
                { "concert.event_id": event_id })
            
            if cursor.count()<1:
                ## This item does not exists in DB, so add item
                post_id = self.db_handler.Insert(json_msg)
                rospy.loginfo("DB: Inserting item with ID %s"%event_id)
                result = True
            else:
                rospy.logdebug("DB: Item %s already exists"%event_id)
                for found_item in cursor:
                    error, output =utilities.compare_dictionaries(
                            json_msg, found_item, 
                            "message", "stored"
                        )
                    
                    ## An error returns False
                    if len(error)>0:
                        rospy.logwarn ("DB: "+error)
                        pprint(output)
                    else:
                        rospy.loginfo("DB:   Found item [%s] is similar to received message"%event_id)
                        result = True
                    
        except Exception as inst:
              ros_node.ParseException(inst)
        finally:
            return result

    def update_msg_status(self, msg):
        try:
            ## If DB is not defined returns False
            if self.db_handler is None:
                rospy.logwarn("UPD: No DB as been defined")
                return
            
            ## Getting available records with given event ID
            event_id        = msg.data
            updated_items   = { 'post_status': 'posted' }
            query_condition = { 'concert.event_id' : event_id }
            
            ## Updating status event in DB
            result          = self.db_handler.Update(query_condition, updated_items)
            if result:
                rospy.loginfo("UPD: Updated post status of %s"%event_id)
            else:
                rospu.logwarn("UPD: Couldn't update event %s"%event_id)
                
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
                
            elif '/event_finder/posted_events' in topic:
                
                rospy.logdebug("UPD: Received message for updating status")
                self.update_queue.put(msg)
                
                ## Notify thread that data has arrived
                with self.update_condition:
                    self.update_condition.notifyAll()
                
            elif '/event_finder/updated_events' in topic:
                
                ## Adding message to a queue
                rospy.logdebug("DB: Adding message to a queue")
                self.db_queue.put(msg)
                
                ## Notify thread that data has arrived
                with self.db_condition:
                    self.db_condition.notifyAll()
                
        except Exception as inst:
              ros_node.ParseException(inst)
      
    def Init(self):
        try:
            if self.database is not None and self.collection is not None:
                fake_msg = WeeklySearch(database=self.database,
                                        el_collection=self.collection)
                rospy.loginfo("Default initialisation of DB")
                self.init_db(fake_msg)
                
            rospy.Timer(rospy.Duration(0.2), self.Run, oneshot=True)
            rospy.Timer(rospy.Duration(0.2), self.StoreMessage, oneshot=True)
            rospy.Timer(rospy.Duration(0.2), self.UpdateStatus, oneshot=True)
        except Exception as inst:
              ros_node.ParseException(inst)

    def UpdateStatus(self, event):
        ''' UpdateStatus method '''
        try:
            while not rospy.is_shutdown():
                ## Waiting for new message to come
                while not self.update_queue.empty():
                    
                    
                    ## Waiting for new message to come
                    with self.update_condition:
                        rospy.logdebug('UPD: Waiting for IDs to update')
                        self.update_condition.wait()
                    
                    ## Getting event from queue
                    ros_msg = self.update_queue.get()
                    
                    ## Updating status of event in DB
                    self.update_msg_status(ros_msg)
                    
        except Exception as inst:
              ros_node.ParseException(inst)
            
    def StoreMessage(self, event):
        ''' StoreMessage method '''
        try:
            while not rospy.is_shutdown():
                ## Waiting for new message to come
                while not self.db_queue.empty():
                    
                    
                    ## Waiting for new message to come
                    with self.db_condition:
                        rospy.logdebug('DB: Waiting for events to store')
                        self.db_condition.wait()
                    
                    ## Getting event from queue
                    weekly_event = self.db_queue.get()             
                    
                    ## Connecting to DB
                    ok = self.update_db_info(weekly_event)
                    if not ok:
                        rospy.logwarn('DB: Message was not added!')
                    else:
                        self.Publish('/event_finder/collected_events', weekly_event)
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

    db_parser = OptionGroup(parser, "Database options")
    db_parser.add_option('--collection',
                type="string",
                action='store',
                default="concerts",
                help='Input collection')
    db_parser.add_option('--database',
                type="string",
                action='store',
                default="events",
                help='Input collection')
    
    parser.add_option_group(db_parser)
    (options, args) = parser.parse_args()
    
    args            = {}
    logLevel        = rospy.DEBUG if options.debug else rospy.INFO
    rospy.init_node('event_collector', anonymous=False, log_level=logLevel)
    
    ## Sending logging to syslog
    if options.syslog:
        logging_utils.update_loggers()

    ## Defining static variables for subscribers and publishers
    sub_topics     = [
        ('/event_finder/weekly_search',    WeeklySearch),
        ('/event_finder/updated_events',   WeeklyEvents),
        ('/event_finder/clean_events',     Bool),
        ('/event_finder/posted_events',    String)
    ]
    pub_topics     = [
        ('/event_finder/collected_events', WeeklyEvents),
        ('/event_finder/remove_events',    WeeklyEvents)
    ]
    system_params  = [
        #'/event_locator_param'
    ]
    
    ## Defining arguments
    args.update({'queue_size':      options.queue_size})
    args.update({'latch':           options.latch})
    args.update({'sub_topics':      sub_topics})
    args.update({'pub_topics':      pub_topics})
    args.update({'database':        options.database})
    args.update({'collection':      options.collection})
    #args.update({'system_params':   system_params})
    
    # Go to class functions that do all the heavy lifting.
    try:
        spinner = EventsCollector(**args)
    except rospy.ROSInterruptException:
        pass
    # Allow ROS to go to all callbacks.
    rospy.spin()

