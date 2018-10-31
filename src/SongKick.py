#!/usr/bin/env python
# -*- coding: utf-8 -*-

## Usage:
##        rosrun event_locator SongKick.py --api_key AjMZ6hglQokcqvem --debug --end_date 2019-01-30
##        rosrun event_locator SongKick.py --api_key AjMZ6hglQokcqvem --debug

import eventful
import rospy
import datetime
import time
import math

from unidecode import unidecode
from Finder import Finder
from hs_utils import ros_node
from hs_utils import message_converter as mc
from hs_utils.mongo_handler import MongoAccess
from events_msgs.msg import Venue
from events_msgs.msg import Concert
from events_msgs.msg import WeeklyEvents

from optparse import OptionParser, OptionGroup
from pprint import pprint

class SongKick(Finder):
    def __init__(self, **kwargs):
        try:
            ## Initialising parent class
            super(SongKick, self).__init__(**kwargs)
            
            self.db_handler = None            
            self.database   = None            
            self.collection = None
            
            self.start_date = None
            self.end_date   = None
            self.location   = 'sk:104761'
            self.base_url   = 'https://api.songkick.com/api/3.0/'
            
            ## Generating instance of strategy
            for key, value in kwargs.iteritems():
                if "start_date" == key:
                    self.start_date = value
                elif "end_date" == key:
                    self.end_date = value
                elif "collection" == key:
                    self.collection = value
                elif "database" == key:
                    self.database = value
                elif "api_key" == key:
                    self.api_key = value

            rospy.loginfo("Initialising node")
            self.Init()
        except Exception as inst:
            ros_node.ParseException(inst)
              
    def Init(self):
        
        try:
            if self.api_key is not None:
                rospy.loginfo("Creating SongKick API client")
                self.api = eventful.API(self.api_key, cache='.cache')
            else:
                rospy.logwarn("SongKick API client has not been started")

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

    def search_events(self, event_found=None, date_=None, page_number_=None):
        '''
            Gets a list of events from Eventful
        '''
        if self.api_key is None:
            rospy.logwarn("Search event stopped, SongKick API client has not been started")
            return
        
        next_page = None
        result = None
        try:
            ## Get events in location
            if page_number_ is None:
                current_page = 1
            else:
                current_page = page_number_
                
            rospy.logdebug('  Searching for events in page [%d]'%current_page)
            payload = {
                'apikey':   self.api_key,
                'location': self.location,
                'page':     page_number_,
                'min_date': self.start_date,
                'max_date': self.end_date
            }
            
            ## Requesting specific page
            url             = self.base_url+'events.json'
            result, code, et= self.request_call(url, payload)
            if result is None:
                rospy.logwarn("Invalid event response")
            ## Request elapsed time
            
            ## Collecting results
            resultsPage     = result["resultsPage"]
            totalEntries    = resultsPage["totalEntries"]
            entriesPerPage  = resultsPage["perPage"]
            status          = resultsPage["status"]
            events          = resultsPage["results"]["event"]

            ## Defining events results
            if event_found == None:
                event_found             = WeeklyEvents()
                event_found.status      = status
                event_found.total_found = totalEntries
                event_found.total_found = entriesPerPage
                event_found.events      = []
            
            ## Checking if results is OK
            if status != "ok":
                rospy.logwarn("Error in event response")
                return
            rospy.logdebug('[OK] Initial request took %4.2fs'%et)

            ## Looking for event information
            rospy.logdebug('  Collecting information from [%d] events'%len(events))
            for event in events:
                event_id = str(event["id"])
                if event_id is None:
                    rospy.logdebug('  Invalid event:')
                    pprint(event)
                    continue
                
                ## Collecting event information
                event_url       = self.base_url+'events/'+event_id+'.json'
                payload         = {'apikey':   self.api_key}
                result, code, et= self.request_call(event_url, payload)
                
                ## Getting performance information
                evResultsPage   = result['resultsPage']
                results         = evResultsPage['results']
                
                ## Status would tell if event has been "cancelled"
                status          = evResultsPage['status']
                
                ## Checking if results is OK
                if status != "ok":
                    rospy.logwarn("Error in performance response")
                    continue
        
                ## Collecting event relevant information
                event_parsed = self.parse_events(results)
                concert_message = self.parse_events(results)
                rospy.logdebug('    Parsed event: [%s] in %4.2fs'%
                               (concert_message.name, et))
                
                ## Appending events in iterated object
                event_found.events.append(event_parsed)

            ## Increasing for looking into next page
            current_page    = resultsPage["page"]
            next_page       = current_page+1
            
            ## Calculating condition for iterator
            totalPages      = int(math.ceil((totalEntries*1.0)/entriesPerPage))
            
            ## Stop condition based in current page
            if next_page>totalPages:
                next_page= None
            
        except Exception as inst:
              ros_node.ParseException(inst)
        finally:
            return event_found, next_page

    def search_all_events(self):
        
        try:
            ## Getting first one to calculate all
            page = 1
            rospy.loginfo('Starting search in page [%d]...'%page)
            events, page    = self.search_events()
            last_page       = page
            while page is not None:
                rospy.loginfo_once("Processing events...")
                
                rospy.loginfo('  Going to page [%d]'%page)
                last_page   = page
                events, page= self.search_events(event_found=events, page_number_=page)

            ## Adding last information to concert events
            events.start_date   = self.start_date
            events.end_date     = self.end_date
            events.city         = 'Zurich'
            events.country      = 'Switzerland'
            rospy.loginfo('Finished search')
        except Exception as inst:
              ros_node.ParseException(inst)
        return events

    def parse_events(self, results):
        parsed_result = {}
        concert_message = Concert()
        try:
            
            ## Collecting event relevant information
            event           = results['event']
            event_keys      = event.keys()
            performances    = event['performance']
            venue           = event['venue']
            venue_keys      = venue.keys()

            ## Parsing venue information
            venue_info = {
                'name':     unidecode(venue['displayName']),
                'id':       venue['id'],
                'lat':      event['location']['lat'],
                'lng':      event['location']['lng'],
                'street':   '' if 'street' not in venue_keys else unidecode(venue['street']),
                'zip':      '' if 'zip' not in venue_keys else unidecode(venue['zip']),
            }
            
            if 'website' in venue_keys:
                if venue['website'] is None:
                    venue['website'] = ''
                venue_info.update({'capacity':   venue['capacity']})
                
            if 'capacity' in venue_keys:
                if venue['capacity'] is None:
                    venue['capacity'] = float('nan')
                venue_info.update({'capacity':   venue['capacity']})
            
            ## Concerting to ROS message
            message_type    = "events_msgs/Venue"
            venue_message   = mc.convert_dictionary_to_ros_message(message_type, venue_info)
            
            ## Parsing event response
            parsed_result = {
                'name':         unidecode(event['displayName']),
                'popularity':   event['popularity'],
                'start_time':   str(event['start']['datetime']),
#                'start_time':   event['start']['date'],
                'status':       unidecode(event['status']),
                'venue':        venue_info,
            }
            
            ## Getting artist info
            for performance in performances:
                parsed_result.update({'artist':     unidecode(performance['artist']['displayName'])})
                parsed_result.update({'artist_id':  performance['artist']['id']})
            
            if 'flaggedAsEnded' in event_keys:
                parsed_result.update({'hasEnded':   event['flaggedAsEnded']})
            
            ## Manual conversions
            message_type    = "events_msgs/Concert"
            concert_message = mc.convert_dictionary_to_ros_message(message_type, parsed_result)
            concert_message.venue= venue_message
            
        except Exception as inst:
              ros_node.ParseException(inst)
        finally:
            return concert_message
        
    def store_events(self, events):
        result = True
        try:
            result = False
            for event in events:
                event_id = event["id"]
                print "-->event_id:", event_id
            
        except Exception as inst:
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

    event_group = OptionGroup(parser, 'Event search parameters')
    io_group    = OptionGroup(parser, 'Event I/O parameters')
    
    event_group.add_option('--start_date',
                type="string",
                action='store',
                default=start_date.strftime("%Y-%m-%d"),
                help='A starting date in the form YYYY-MM-DD.')
    event_group.add_option('--end_date',
                type="string",
                action='store',
                default=end_date.strftime("%Y-%m-%d"),
                help='A ending date in the form YYYY-MM-DD.')
    event_group.add_option('--location',
                type="string",
                action='store',
                default='sk:104761',
                help='City of events')
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
                default='concerts',
                help='Provide a valid collection name')
    
    parser.add_option_group(event_group) 
    parser.add_option_group(io_group) 
    (options, args) = parser.parse_args()
    
    if options.api_key is None:
        parser.error("Missing required option: --api_key='ASDASDASD'")
        
    if options.start_date is None:
        parser.error("Missing required option: --start_date='YYYY-MM-DD'")
        
    if options.end_date is None:
        parser.error("Missing required option: --end_date='YYYY-MM-DD'")
        
    logLevel        = rospy.DEBUG if options.debug else rospy.INFO
    rospy.init_node('event_locator_sfl', anonymous=False, log_level=logLevel)
        
    try:
        args = {
            'location':     options.location,
            'api_key':      options.api_key,
            'start_date':   options.start_date,
            'end_date':     options.end_date,
            'database':     options.database,
            'collection':   options.collection,
        }
        
        rospy.logdebug("Crating event finder")
        event_finder = SongKick(**args)
        
        events = event_finder.search_all_events()
        pprint (events)
        
#         if 'event' in events['events'].keys():
#             rospy.logdebug("Events found: %s"% str(len(events['events']['event'])))
    except Exception as inst:
          ros_node.ParseException(inst)