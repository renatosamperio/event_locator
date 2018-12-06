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
from events_msgs.msg import Artist
from events_msgs.msg import Concert
from events_msgs.msg import WeeklyEvents
from events_msgs.msg import WeeklySearch

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
            self.api_key    = None
            
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

    def search(self, event_found=None, date_=None, page_number_=None):
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
                return
            
            ## Collecting results
            resultsPage     = result["resultsPage"]
            totalEntries    = resultsPage["totalEntries"]
            entriesPerPage  = resultsPage["perPage"]
            query_status    = str(resultsPage["status"])
            events          = resultsPage["results"]["event"]

            ## Defining events results
            if event_found == None:
                event_found             = WeeklyEvents()
                event_found.query_status= query_status
                event_found.total_found = totalEntries
                event_found.events_page = entriesPerPage
                event_found.events      = []
            
            ## Checking if results is OK
            if query_status != "ok":
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
                revResultsPage   = result['resultsPage']
                results         = revResultsPage['results']
                
                ## Status would tell if event has been "cancelled"
                status          = revResultsPage['status']
                
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

    def search_all(self):
        
        if self.api_key is None:
            rospy.logwarn("Weekly search event stopped, SongKick API client has not been started")
            return
        
        try:
            ## Getting first one to calculate all
            page = 1
            rospy.loginfo('Starting search in page [%d]...'%page)
            events, page    = self.search()
            last_page       = page
            while page is not None:
                # rospy.loginfo_once("Processing events search...")
                
                rospy.logdebug('  Going to page [%d]'%page)
                last_page   = page
                events, page= self.search(event_found=events, page_number_=page)
                
                if events is None:
                    rospy.logwarn('Search of all weekly events failed')
                    return
                
            ## Adding last information to concert events
            if events is None:
                events = WeeklyEvents()
                events.query_status = 'failed'

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
                'id':       str(venue['id']),
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
                'popularity':   float(event['popularity']),
                'start_time':   str(event['start']['datetime']),
#                'start_time':   event['start']['date'],
                'status':       unidecode(event['status']),
                'venue':        venue_info,
            }
            if 'flaggedAsEnded' in event_keys:
                parsed_result.update({'hasEnded':   event['flaggedAsEnded']})

            ## Manual conversions
            message_type    = "events_msgs/Concert"
            concert_message = mc.convert_dictionary_to_ros_message(message_type, parsed_result)
            
            ## Getting artist info
            artist = Artist()
            for performance in performances:
                artist.name     = unidecode(performance['artist']['displayName'])
                artist.id       = str(performance['artist']['id'])
#                 parsed_result.update({'artist':     unidecode(performance['artist']['displayName'])})
#                 parsed_result.update({'artist_id':  str(performance['artist']['id'])})
            
            ## Relationship ONE to MANY
            concert_message.venue   = venue_message
            concert_message.artist  = artist
            
        except Exception as inst:
            ros_node.ParseException(inst)
        finally:
            return concert_message

    def store_events(self, events_msg):
        ## Check if database has been defined
        if self.database is None or self.collection is None :
            rospy.logwarn("Event storing stopped, database has not been defined")
            return

        post_id = ''
        try:
            if events_msg is None:
                rospy.logwarn('Could not store events, invalid record')
                return
            
            ## Converting ROS message into dictionary
            events = mc.convert_ros_message_to_dictionary(events_msg)
            
            ## inserting dictionary as DB record
            post_id = self.db_handler.Insert(events)
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
            self.end_date   = weekly_search.end_date
            self.location   = weekly_search.location
            self.api_key    = weekly_search.sk_api_key
            self.database   = weekly_search.database
            self.collection = weekly_search.el_collection
            
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
        
        events = event_finder.search_all()
        pprint (events)
        
#         if 'event' in events['events'].keys():
#             rospy.logdebug("Events found: %s"% str(len(events['events']['event'])))
    except Exception as inst:
          ros_node.ParseException(inst)

# {'city': 'Zurich',
#  'country': 'Switzerland',
#  'end_date': '2018-12-31',
#  'events': [{'artist': 'Ilyas Yalcintas',
#              'artist_id': '9612844',
#              'hasEnded': False,
#              'name': 'Ilyas Yalcintas at Dilaila Club (December 24, 2018)',
#              'popularity': 0.000225,
#              'start_time': '2018-12-24T21:30:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '3717299',
#                        'lat': 47.3667,
#                        'lng': 8.55,
#                        'name': 'Dilaila Club',
#                        'street': '',
#                        'website': '',
#                        'zip': ''}},
#             {'artist': 'cinthie',
#              'artist_id': '714729',
#              'hasEnded': False,
#              'name': "cinthie at Frieda's Buxe (December 25, 2018)",
#              'popularity': 6.7e-05,
#              'start_time': '2018-12-25T23:30:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '1209316',
#                        'lat': 47.37739,
#                        'lng': 8.5109,
#                        'name': "Frieda's Buxe",
#                        'street': 'Friedaustr. 23',
#                        'website': '',
#                        'zip': '8003'}},
#             {'artist': 'Miss Saigon',
#              'artist_id': '4134421',
#              'hasEnded': False,
#              'name': 'Miss Saigon at Theater 11 (December 26, 2018)',
#              'popularity': 0.00042,
#              'start_time': '2018-12-26T18:30:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '584981',
#                        'lat': 47.4106844,
#                        'lng': 8.549689,
#                        'name': 'Theater 11',
#                        'street': 'Thurgauerstrasse 7',
#                        'website': '',
#                        'zip': '8050'}},
#             {'artist': 'MOREEATS',
#              'artist_id': '1736060',
#              'hasEnded': False,
#              'name': 'MOREEATS at Sender (GDS.FM) (December 27, 2018)',
#              'popularity': 2.1e-05,
#              'start_time': '2018-12-27T20:00:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '3541979',
#                        'lat': 47.37726,
#                        'lng': 8.52758,
#                        'name': 'Sender (GDS.FM)',
#                        'street': 'Kurzgasse 4',
#                        'website': '',
#                        'zip': '8004'}},
#             {'artist': 'Miss Saigon',
#              'artist_id': '4134421',
#              'hasEnded': False,
#              'name': 'Miss Saigon at Theater 11 (December 27, 2018)',
#              'popularity': 0.00042,
#              'start_time': '2018-12-27T19:30:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '584981',
#                        'lat': 47.4106844,
#                        'lng': 8.549689,
#                        'name': 'Theater 11',
#                        'street': 'Thurgauerstrasse 7',
#                        'website': '',
#                        'zip': '8050'}},
#             {'artist': 'Erika Stucky',
#              'artist_id': '205652',
#              'hasEnded': False,
#              'name': 'Erika Stucky at Moods (December 27, 2018)',
#              'popularity': 0.000161,
#              'start_time': 'None',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '37717',
#                        'lat': 47.38865,
#                        'lng': 8.5187,
#                        'name': 'Moods',
#                        'street': 'Schiffbaustrasse 6',
#                        'website': '',
#                        'zip': '8005'}},
#             {'artist': 'Hvitling',
#              'artist_id': '8864794',
#              'hasEnded': False,
#              'name': 'Bernstein (CH), Zwillingsmann, Sampayo, and Hvitling at Kauz (December 28, 2018)',
#              'popularity': 0.000188,
#              'start_time': 'None',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '2929708',
#                        'lat': 47.36865,
#                        'lng': 8.53918,
#                        'name': 'Kauz',
#                        'street': '',
#                        'website': '',
#                        'zip': ''}},
#             {'artist': 'Miss Saigon',
#              'artist_id': '4134421',
#              'hasEnded': False,
#              'name': 'Miss Saigon at Theater 11 (December 28, 2018)',
#              'popularity': 0.00042,
#              'start_time': '2018-12-28T19:30:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '584981',
#                        'lat': 47.4106844,
#                        'lng': 8.549689,
#                        'name': 'Theater 11',
#                        'street': 'Thurgauerstrasse 7',
#                        'website': '',
#                        'zip': '8050'}},
#             {'artist': 'Walking With Ghosts',
#              'artist_id': '8769129',
#              'hasEnded': False,
#              'name': 'Uberyou with Peacocks and Walking With Ghosts at Dynamo (December 28, 2018)',
#              'popularity': 0.001063,
#              'start_time': '2018-12-28T20:00:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '69432',
#                        'lat': 47.3834,
#                        'lng': 8.53938,
#                        'name': 'Dynamo',
#                        'street': 'Wasserwerkstrasse 21',
#                        'website': '',
#                        'zip': '8006'}},
#             {'artist': 'Miss Saigon',
#              'artist_id': '4134421',
#              'hasEnded': False,
#              'name': 'Miss Saigon at Theater 11 (December 29, 2018)',
#              'popularity': 0.00042,
#              'start_time': '2018-12-29T19:30:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '584981',
#                        'lat': 47.4106844,
#                        'lng': 8.549689,
#                        'name': 'Theater 11',
#                        'street': 'Thurgauerstrasse 7',
#                        'website': '',
#                        'zip': '8050'}},
#             {'artist': 'Hell & Back',
#              'artist_id': '5794304',
#              'hasEnded': False,
#              'name': 'Uberyou with OBTRUSIVE, Chelsea Deadbeat Combo, and Hell & Back at Dynamo (December 29, 2018)',
#              'popularity': 3.7e-05,
#              'start_time': 'None',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '69432',
#                        'lat': 47.3834,
#                        'lng': 8.53938,
#                        'name': 'Dynamo',
#                        'street': 'Wasserwerkstrasse 21',
#                        'website': '',
#                        'zip': '8006'}},
#             {'artist': 'Miss Saigon',
#              'artist_id': '4134421',
#              'hasEnded': False,
#              'name': 'Miss Saigon at Theater 11 (December 29, 2018)',
#              'popularity': 0.00042,
#              'start_time': '2018-12-29T14:30:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '584981',
#                        'lat': 47.4106844,
#                        'lng': 8.549689,
#                        'name': 'Theater 11',
#                        'street': 'Thurgauerstrasse 7',
#                        'website': '',
#                        'zip': '8050'}},
#             {'artist': 'Johny Blaze',
#              'artist_id': '9644534',
#              'hasEnded': False,
#              'name': 'I Hate Models and Johny Blaze at SpaceMonki (December 29, 2018)',
#              'popularity': 0.000307,
#              'start_time': '2018-12-29T23:00:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '3760149',
#                        'lat': 47.3667,
#                        'lng': 8.55,
#                        'name': 'SpaceMonki',
#                        'street': '',
#                        'website': '',
#                        'zip': ''}},
#             {'artist': 'Digitalism',
#              'artist_id': '11927',
#              'hasEnded': False,
#              'name': 'Digitalism at Hive Club (December 29, 2018)',
#              'popularity': 0.056199,
#              'start_time': 'None',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '3965499',
#                        'lat': 47.3667,
#                        'lng': 8.55,
#                        'name': 'Hive Club',
#                        'street': '',
#                        'website': '',
#                        'zip': ''}},
#             {'artist': 'Underskin',
#              'artist_id': '8869479',
#              'hasEnded': False,
#              'name': 'Underskin at Moods (December 29, 2018)',
#              'popularity': 1e-05,
#              'start_time': 'None',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '37717',
#                        'lat': 47.38865,
#                        'lng': 8.5187,
#                        'name': 'Moods',
#                        'street': 'Schiffbaustrasse 6',
#                        'website': '',
#                        'zip': '8005'}},
#             {'artist': 'Dr. Mo',
#              'artist_id': '9780324',
#              'hasEnded': False,
#              'name': 'Lo & Leduc with Dr. Mo at X-TRA (December 29, 2018)',
#              'popularity': 0.001146,
#              'start_time': '2018-12-29T19:00:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '49813',
#                        'lat': 47.3841,
#                        'lng': 8.53267,
#                        'name': 'X-TRA',
#                        'street': 'Limmatstrasse 118',
#                        'website': '',
#                        'zip': '8005'}},
#             {'artist': 'Miss Saigon',
#              'artist_id': '4134421',
#              'hasEnded': False,
#              'name': 'Miss Saigon at Theater 11 (December 30, 2018)',
#              'popularity': 0.00042,
#              'start_time': '2018-12-30T18:30:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '584981',
#                        'lat': 47.4106844,
#                        'lng': 8.549689,
#                        'name': 'Theater 11',
#                        'street': 'Thurgauerstrasse 7',
#                        'website': '',
#                        'zip': '8050'}},
#             {'artist': 'Miss Saigon',
#              'artist_id': '4134421',
#              'hasEnded': False,
#              'name': 'Miss Saigon at Theater 11 (December 30, 2018)',
#              'popularity': 0.00042,
#              'start_time': '2018-12-30T13:30:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '584981',
#                        'lat': 47.4106844,
#                        'lng': 8.549689,
#                        'name': 'Theater 11',
#                        'street': 'Thurgauerstrasse 7',
#                        'website': '',
#                        'zip': '8050'}},
#             {'artist': 'Iiro Rantala',
#              'artist_id': '273953',
#              'hasEnded': False,
#              'name': 'Iiro Rantala at Moods (December 30, 2018)',
#              'popularity': 0.000525,
#              'start_time': 'None',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '37717',
#                        'lat': 47.38865,
#                        'lng': 8.5187,
#                        'name': 'Moods',
#                        'street': 'Schiffbaustrasse 6',
#                        'website': '',
#                        'zip': '8005'}},
#             {'artist': 'K.o.s Crew',
#              'artist_id': '3664651',
#              'hasEnded': False,
#              'name': 'CALI P and K.o.s Crew at Moods (December 31, 2018)',
#              'popularity': 0.001383,
#              'start_time': '2018-12-31T22:00:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '37717',
#                        'lat': 47.38865,
#                        'lng': 8.5187,
#                        'name': 'Moods',
#                        'street': 'Schiffbaustrasse 6',
#                        'website': '',
#                        'zip': '8005'}},
#             {'artist': 'HUGEL',
#              'artist_id': '8589694',
#              'hasEnded': False,
#              'name': 'HUGEL at Harterei Club (December 31, 2018)',
#              'popularity': 0.003167,
#              'start_time': '2018-12-31T23:30:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '3764314',
#                        'lat': 47.38676,
#                        'lng': 8.51667,
#                        'name': 'Harterei Club',
#                        'street': 'Hardstrasse 219',
#                        'website': '',
#                        'zip': '8005'}},
#             {'artist': 'RB Trio',
#              'artist_id': '8924709',
#              'hasEnded': False,
#              'name': 'RB Trio at George Bar & Grill (December 31, 2018)',
#              'popularity': 0.0,
#              'start_time': 'None',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '3102774',
#                        'lat': 47.3729929,
#                        'lng': 8.5338875,
#                        'name': 'George Bar & Grill',
#                        'street': 'Sihlstrasse 50',
#                        'website': '',
#                        'zip': '8001'}},
#             {'artist': 'Ander',
#              'artist_id': '1844211',
#              'hasEnded': False,
#              'name': 'Ander at Sender (GDS.FM) (December 31, 2018)',
#              'popularity': 8e-05,
#              'start_time': '2018-12-31T23:00:00+0100',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '3541979',
#                        'lat': 47.37726,
#                        'lng': 8.52758,
#                        'name': 'Sender (GDS.FM)',
#                        'street': 'Kurzgasse 4',
#                        'website': '',
#                        'zip': '8004'}},
#             {'artist': 'Jonathan Kaspar',
#              'artist_id': '8689059',
#              'hasEnded': False,
#              'name': 'Jonathan Kaspar at SpaceMonki (December 31, 2018)',
#              'popularity': 0.000105,
#              'start_time': 'None',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '3760149',
#                        'lat': 47.3667,
#                        'lng': 8.55,
#                        'name': 'SpaceMonki',
#                        'street': '',
#                        'website': '',
#                        'zip': ''}},
#             {'artist': 'Vampiria',
#              'artist_id': '8643269',
#              'hasEnded': False,
#              'name': 'Vampiria at Dynamo (December 31, 2018)',
#              'popularity': 1.2e-05,
#              'start_time': 'None',
#              'status': 'ok',
#              'venue': {'capacity': nan,
#                        'id': '69432',
#                        'lat': 47.3834007,
#                        'lng': 8.5393821,
#                        'name': 'Dynamo',
#                        'street': 'Wasserwerkstrasse 21',
#                        'website': '',
#                        'zip': '8006'}},
#             {'artist': 'WAIO',
#              'artist_id': '8300503',
#              'hasEnded': False,
#              'name': 'WAIO at Unknown venue (December 31, 2018)',
#              'popularity': 0.000339,
#              'start_time': 'None',
#              'status': 'ok',
#              'venue': {'capacity': 0.0,
#                        'id': 'None',
#                        'lat': 47.38025,
#                        'lng': 8.53723,
#                        'name': 'Unknown venue',
#                        'street': '',
#                        'website': '',
#                        'zip': ''}}],
#  'events_page': 50,
#  'query_status': 'ok',
#  'start_date': '2018-12-24',
#  'total_found': 26}
